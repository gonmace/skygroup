from datetime import timedelta

from django.utils import timezone

from cuentas.models import RolEmpresa, RolPermiso, User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro
from notificaciones.models import Notificacion
from proyectos.models import Proyecto

from .models import Asignacion, Comentario, Etiqueta, Evento, Ticket
from .tests_chat import BaseChat, usuario

E = Ticket.Estado


class EditarTests(BaseChat):
    def datos(self, **extra):
        d = {'titulo': 'Tarea editada', 'solicitante': 'Cliente', 'prioridad': 'URGENT', 'ejecutores': [self.ejec1.pk]}
        d.update(extra)
        return d

    def test_solo_edit_any_edita(self):
        for u in (self.ejec1, self.lector):
            self.client.force_login(u)
            self.assertEqual(self.client.get(self.url('/editar/')).status_code, 403)
            self.assertEqual(self.client.post(self.url('/editar/'), self.datos()).status_code, 403)
        self.t.refresh_from_db()
        self.assertEqual(self.t.titulo, 'Tarea')

    def test_registra_cambios_de_prioridad_y_vencimiento(self):
        self.client.force_login(self.director)
        manana = (timezone.localdate() + timedelta(days=1)).isoformat()
        r = self.client.post(self.url('/editar/'), self.datos(vence=manana))
        self.assertRedirects(r, self.url('/'), fetch_redirect_response=False)
        self.t.refresh_from_db()
        self.assertEqual((self.t.titulo, self.t.prioridad, self.t.vence.isoformat()), ('Tarea editada', 'URGENT', manana))
        detalles = list(Evento.objects.filter(ticket=self.t).values_list('tipo', 'detalle'))
        self.assertIn(('priority', 'cambió la prioridad a «Urgente»'), detalles)
        self.assertTrue(any(t == 'due' for t, _ in detalles))

    def test_asignar_nuevo_ejecutor_notifica_y_desasignar_avisa(self):
        self.client.force_login(self.director)
        self.client.post(self.url('/editar/'), self.datos(ejecutores=[self.ejec2.pk]))
        self.assertTrue(Notificacion.objects.filter(destinatario=self.ejec2, mensaje__startswith='te asignó').exists())
        self.assertTrue(Notificacion.objects.filter(destinatario=self.ejec1, mensaje__startswith='te desasignó').exists())
        self.assertEqual(list(self.t.asignaciones.values_list('user', flat=True)), [self.ejec2.pk])

    def test_no_desasigna_a_quien_ya_tiene_trabajo_registrado(self):
        a = self.t.asignaciones.get()
        a.avanzar_a(E.EN_PROGRESO)
        a.save()
        self.client.force_login(self.director)
        r = self.client.post(self.url('/editar/'), self.datos(ejecutores=[self.ejec2.pk]), follow=True)
        self.assertEqual(sorted(self.t.asignaciones.values_list('user', flat=True)), sorted([self.ejec1.pk, self.ejec2.pk]))
        self.assertContains(r, 'No se desasignó a')

    def test_pasar_de_entrada_a_por_hacer_avisa_a_los_involucrados(self):
        t = self.ticket('Sin asignar')
        self.assertEqual(t.estado, E.ENTRADA)
        self.client.force_login(self.director)
        self.client.post(f'/embol/tareas/{t.pk}/editar/', self.datos(ejecutores=[self.ejec2.pk]))
        t.refresh_from_db()
        self.assertEqual(t.estado, E.POR_HACER)
        self.assertTrue(Notificacion.objects.filter(destinatario=self.ejec2, mensaje__contains='Por hacer').exists())

    def test_no_edita_tickets_de_otra_empresa_ni_acepta_datos_ajenos(self):
        ajeno = self.ticket('Ajeno', empresa=self.b, creador=self.director_b)
        self.client.force_login(self.director)
        self.assertEqual(self.client.get(f'/embol/tareas/{ajeno.pk}/editar/').status_code, 404)
        pb = Proyecto.objects.create(empresa=self.b, nombre='P', codigo='P1')
        r = self.client.post(self.url('/editar/'), self.datos(proyecto=pb.pk))
        self.assertEqual(r.status_code, 200)
        self.t.refresh_from_db()
        self.assertEqual(self.t.titulo, 'Tarea')

    def test_formulario_muestra_selectores_de_personas_y_alta_rapida_de_etiquetas(self):
        self.client.force_login(self.director)
        html = self.client.get(self.url('/editar/')).content.decode()
        self.assertIn('data-multiselect', html)
        self.assertIn('data-label-add', html)
        self.assertIn(self.ejec1.email, html)


class DerivarDividirTests(BaseChat):
    def test_derivar_crea_un_hijo_vacio_y_va_a_editarlo(self):
        self.client.force_login(self.director)
        r = self.client.post(self.url('/derivar/'))
        hijo = Ticket.objects.get(padre=self.t)
        self.assertRedirects(r, f'/embol/tareas/{hijo.pk}/editar/', fetch_redirect_response=False)
        self.assertEqual((hijo.codigo, hijo.titulo, hijo.descripcion, hijo.creador, hijo.es_parte_dividida),
                         (f'{self.t.codigo}-1', 'Tarea (derivado)', '', self.director, False))
        self.assertEqual(list(hijo.asignaciones.values_list('user', flat=True)), [self.ejec1.pk])  # hereda asignados
        self.assertTrue(Evento.objects.filter(ticket=hijo, detalle__contains='derivado de').exists())

    def test_dividir_clona_contenido_estado_y_progreso(self):
        self.t.descripcion, self.t.prioridad = 'Detalle largo', 'HIGH'
        self.t.save()
        a = self.t.asignaciones.get()
        a.avanzar_a(E.CONCLUIDO)
        a.conclusion, a.aprobado_en = 'listo', timezone.now()
        a.save()
        self.t.recalcular_estado()
        self.client.force_login(self.director)
        self.client.post(self.url('/dividir/'))
        h = Ticket.objects.get(padre=self.t)
        self.assertTrue(h.es_parte_dividida)
        self.assertEqual((h.titulo, h.descripcion, h.prioridad, h.creador, h.estado),
                         ('Tarea', 'Detalle largo', 'HIGH', self.t.creador, self.t.estado))
        ha = h.asignaciones.get()
        self.assertEqual((ha.estado, ha.conclusion, bool(ha.aprobado_en)), (E.CONCLUIDO, 'listo', True))
        self.assertTrue(Evento.objects.filter(ticket=self.t, tipo='split').exists())

    def test_las_partes_numeran_correlativamente(self):
        self.client.force_login(self.director)
        for _ in range(2):
            self.client.post(self.url('/dividir/'))
        self.assertEqual(sorted(self.t.hijos.values_list('codigo', flat=True)), [f'{self.t.codigo}-1', f'{self.t.codigo}-2'])

    def test_el_hijo_de_un_ticket_suspendido_nace_bloqueado(self):
        from .servicios import alternar_suspension
        alternar_suspension(self.t, self.director)
        self.client.force_login(self.director)
        self.client.post(self.url('/derivar/'))
        hijo = Ticket.objects.get(padre=self.t)
        self.assertIsNotNone(hijo.suspendido_en)

    def test_hereda_etiquetas_y_proyecto(self):
        etq = Etiqueta.objects.create(empresa=self.a, nombre='Obra')
        pr = Proyecto.objects.create(empresa=self.a, nombre='Torre', codigo='T1')
        self.t.etiquetas.add(etq)
        self.t.proyecto = pr
        self.t.save()
        self.client.force_login(self.director)
        self.client.post(self.url('/dividir/'))
        h = Ticket.objects.get(padre=self.t)
        self.assertEqual((list(h.etiquetas.all()), h.proyecto), ([etq], pr))

    def test_permisos(self):
        for u in (self.ejec1, self.lector):
            self.client.force_login(u)
            self.assertEqual(self.client.post(self.url('/derivar/')).status_code, 403)
            self.assertEqual(self.client.post(self.url('/dividir/')).status_code, 403)
        self.assertEqual(self.client.get(self.url('/derivar/')).status_code, 405)
        self.assertFalse(Ticket.objects.filter(padre=self.t).exists())

    def test_no_deriva_tickets_de_otra_empresa(self):
        ajeno = self.ticket('x', empresa=self.b, creador=self.director_b)
        self.client.force_login(self.director)
        self.assertEqual(self.client.post(f'/embol/tareas/{ajeno.pk}/derivar/').status_code, 404)

    def test_el_detalle_ofrece_las_acciones_segun_permisos(self):
        self.client.force_login(self.director)
        html = self.client.get(self.url('/')).content.decode()
        for texto in ('Dividir', 'Derivar', 'Editar ticket', 'Suspender'):
            self.assertIn(texto, html)
        self.client.force_login(self.ejec1)
        html = self.client.get(self.url('/')).content.decode()
        for texto in ('Dividir', 'Derivar', 'Editar ticket'):
            self.assertNotIn(texto, html)
        self.assertIn('Concluir la tarea', html)


class ArchivarTests(BaseChat):
    def cerrar(self):
        a = self.t.asignaciones.get()
        a.avanzar_a(E.CONCLUIDO)
        a.aprobado_en = timezone.now()
        a.save()
        self.t.recalcular_estado()

    def test_solo_se_archivan_concluidos_o_suspendidos(self):
        self.client.force_login(self.director)
        self.client.post(self.url('/archivar/'))
        self.t.refresh_from_db()
        self.assertIsNone(self.t.archivado_en)
        self.cerrar()
        self.client.post(self.url('/archivar/'))
        self.t.refresh_from_db()
        self.assertIsNotNone(self.t.archivado_en)
        self.assertTrue(Evento.objects.filter(ticket=self.t, tipo='archived').exists())

    def test_un_participante_archiva_el_suyo_pero_otro_miembro_no(self):
        self.cerrar()
        self.client.force_login(self.ejec2)
        self.assertEqual(self.client.post(self.url('/archivar/')).status_code, 403)
        self.client.force_login(self.ejec1)
        self.client.post(self.url('/archivar/'))
        self.t.refresh_from_db()
        self.assertIsNotNone(self.t.archivado_en)

    def test_archivados_salen_del_tablero_y_aparecen_en_la_lista(self):
        self.cerrar()
        self.client.force_login(self.director)
        self.client.post(self.url('/archivar/'))
        cols = {c['value']: c for c in self.client.get('/embol/tareas/').context['columns']}
        self.assertEqual(sum(c['count'] for c in cols.values()), 0)
        self.assertContains(self.client.get('/embol/tareas/archivados/'), self.t.clave)

    def test_desarchivar_exige_su_capacidad(self):
        self.cerrar()
        self.t.archivado_en = timezone.now()
        self.t.save()
        self.client.force_login(self.ejec1)
        self.assertEqual(self.client.post(self.url('/desarchivar/')).status_code, 403)
        self.client.force_login(self.director)
        self.client.post(self.url('/desarchivar/'))
        self.t.refresh_from_db()
        self.assertIsNone(self.t.archivado_en)

    def test_la_lista_de_archivados_respeta_la_visibilidad(self):
        otro = self.ticket('Ajeno', estado=E.CONCLUIDO, archivado_en=timezone.now())
        self.t.archivado_en = timezone.now()
        self.t.estado = E.CONCLUIDO
        self.t.save()
        self.client.force_login(self.ejec1)   # solo ve el suyo
        html = self.client.get('/embol/tareas/archivados/').content.decode()
        self.assertIn(self.t.clave, html)
        self.assertNotIn(otro.clave, html)


class ListadosTests(BaseChat):
    def test_mis_tickets_solo_los_propios_abiertos(self):
        ajeno = self.ticket('De otro')
        self.asignar(ajeno, self.ejec2)
        cerrado = self.ticket('Cerrado')
        a = self.asignar(cerrado, self.ejec1)
        a.avanzar_a(E.CONCLUIDO)
        a.aprobado_en = timezone.now()
        a.save()
        self.client.force_login(self.ejec1)
        r = self.client.get('/embol/tareas/mis-tickets/')
        self.assertEqual([t.titulo for t in r.context['pagina']], ['Tarea'])

    def test_mis_tickets_muestra_el_avance_propio_y_pendiente_de_aprobacion(self):
        a = self.t.asignaciones.get()
        a.avanzar_a(E.CONCLUIDO)
        a.save()
        self.client.force_login(self.ejec1)
        t = self.client.get('/embol/tareas/mis-tickets/').context['pagina'][0]
        self.assertEqual((t.estado_visual, t.pendiente_aprobacion), (E.CONCLUIDO, True))

    def test_mis_tickets_ordena_y_muestra_el_ultimo_mensaje(self):
        urgente = self.ticket('Urgente', prioridad='URGENT')
        self.asignar(urgente, self.ejec1)
        Comentario.objects.create(ticket=self.t, autor=self.director, texto='ojo con esto')
        self.client.force_login(self.ejec1)
        r = self.client.get('/embol/tareas/mis-tickets/', {'sort': 'prioridad'})
        self.assertEqual([t.titulo for t in r.context['pagina']], ['Urgente', 'Tarea'])
        self.assertContains(r, 'ojo con esto')
        self.assertEqual(self.client.get('/embol/tareas/mis-tickets/', {'sort': 'inexistente'}).context['orden'], 'vence')

    def test_seguimiento_requiere_chat_view_all_y_oculta_entrada_y_archivados(self):
        self.client.force_login(self.ejec1)
        self.assertEqual(self.client.get('/embol/tareas/seguimiento/').status_code, 403)
        self.ticket('En entrada')
        self.ticket('Archivado', estado=E.CONCLUIDO, archivado_en=timezone.now())
        Comentario.objects.create(ticket=self.t, autor=self.ejec1, texto='primero')
        Comentario.objects.create(ticket=self.t, autor=self.director, texto='segundo')
        self.client.force_login(self.lector)
        r = self.client.get('/embol/tareas/seguimiento/')
        self.assertEqual([t.titulo for t in r.context['pagina']], ['Tarea'])
        self.assertContains(r, 'segundo')
        self.assertContains(r, 'primero')

    def test_dashboard_kpis_y_aislamiento_por_empresa(self):
        ayer = timezone.localdate() - timedelta(days=1)
        self.ticket('Vencido', vence=ayer)
        cerrado = self.ticket('Cerrado hoy', estado=E.CONCLUIDO, cerrado_en=timezone.now())
        self.ticket('De otra empresa', empresa=self.b, creador=self.director_b)
        self.client.force_login(self.director)
        r = self.client.get('/embol/tareas/dashboard/')
        k = r.context['kpis']
        self.assertEqual((k['activos'], k['abiertos'], k['vencidos'], k['concluidos_30']), (3, 2, 1, 1))
        self.assertEqual(len(r.context['serie']), 8)
        self.assertEqual(r.context['serie'][-1]['concluidos'], 1)
        self.assertEqual(sum(w['concluidos'] for w in r.context['serie']), 1)
        self.assertContains(r, 'Creados y concluidos por semana')

    def test_dashboard_listas_de_seguimiento(self):
        hoy = timezone.localdate()
        self.ticket('Atrasado', vence=hoy - timedelta(days=3))
        self.ticket('Por vencer', vence=hoy + timedelta(days=2))
        self.ticket('Lejano', vence=hoy + timedelta(days=30))
        self.ticket('De otra empresa', empresa=self.b, creador=self.director_b, vence=hoy - timedelta(days=1))
        self.client.force_login(self.director)
        r = self.client.get('/embol/tareas/dashboard/')
        self.assertEqual([(t['titulo'], t['dias']) for t in r.context['vencidos']], [('Atrasado', 3)])
        self.assertEqual([t['titulo'] for t in r.context['proximos']], ['Por vencer'])
        self.assertEqual(r.context['kpis']['proximos'], 1)

    def test_dashboard_por_aprobar_y_tiempos(self):
        a = self.t.asignaciones.get()
        a.avanzar_a(E.CONCLUIDO)
        a.save()
        self.client.force_login(self.director)
        r = self.client.get('/embol/tareas/dashboard/')
        self.assertEqual(r.context['kpis']['por_aprobar'], 1)
        self.assertEqual(len(r.context['por_aprobar']), 1)
        self.assertEqual(len(r.context['tiempos']), 3)

    def test_dashboard_exige_su_capacidad(self):
        self.client.force_login(self.ejec1)
        self.assertEqual(self.client.get('/embol/tareas/dashboard/').status_code, 403)

    def test_menu_de_tareas_muestra_solo_lo_permitido(self):
        nombres = lambda u: [i['nombre'] for i in (self.client.force_login(u) or self.client.get('/embol/tareas/')).context['menu_lateral']]
        self.assertEqual(nombres(self.ejec1), ['Tablero', 'Mis tickets', 'Archivados'])
        self.assertEqual(nombres(self.director),
                         ['Resumen', 'Tablero', 'Mis tickets', 'Seguimiento', 'Archivados', 'Tipos de actividad'])
        self.assertIn('Seguimiento', nombres(self.lector))


class EtiquetasTests(BaseChat):
    def test_crear_y_eliminar(self):
        self.client.force_login(self.director)
        self.client.post('/embol/tareas/etiquetas/', {'action': 'add', 'name': 'Obra civil', 'color': 'warning'})
        e = Etiqueta.objects.get(empresa=self.a)
        self.assertEqual((e.nombre, e.color), ('Obra civil', 'warning'))
        self.assertContains(self.client.get('/embol/tareas/etiquetas/'), 'Obra civil')
        self.client.post('/embol/tareas/etiquetas/', {'action': 'delete', 'id': e.pk})
        self.assertFalse(Etiqueta.objects.exists())

    def test_color_invalido_o_nombre_vacio_se_ignora(self):
        self.client.force_login(self.director)
        self.client.post('/embol/tareas/etiquetas/', {'action': 'add', 'name': 'X', 'color': 'rosa-fucsia'})
        self.client.post('/embol/tareas/etiquetas/', {'action': 'add', 'name': '  ', 'color': 'info'})
        self.assertFalse(Etiqueta.objects.exists())

    def test_no_borra_etiquetas_de_otra_empresa(self):
        otra = Etiqueta.objects.create(empresa=self.b, nombre='Ajena')
        self.client.force_login(self.director)
        self.client.post('/embol/tareas/etiquetas/', {'action': 'delete', 'id': otra.pk})
        self.assertTrue(Etiqueta.objects.filter(pk=otra.pk).exists())

    def test_alta_rapida_ajax_reutiliza_ignorando_mayusculas(self):
        self.client.force_login(self.director)
        d1 = self.client.post('/embol/tareas/etiquetas/agregar/', {'name': 'Urgente', 'color': 'error'}).json()
        d2 = self.client.post('/embol/tareas/etiquetas/agregar/', {'name': 'urgente', 'color': 'info'}).json()
        self.assertEqual((d1['created'], d2['created'], d1['id']), (True, False, d2['id']))
        self.assertEqual(Etiqueta.objects.count(), 1)
        self.assertEqual(self.client.post('/embol/tareas/etiquetas/agregar/', {'name': '', 'color': 'info'}).status_code, 400)

    def test_permisos(self):
        self.client.force_login(self.ejec1)
        self.assertEqual(self.client.get('/embol/tareas/etiquetas/').status_code, 403)
        self.assertEqual(self.client.post('/embol/tareas/etiquetas/agregar/', {'name': 'x', 'color': 'info'}).status_code, 403)

    def test_rol_personalizado_con_el_permiso_gestiona(self):
        rol = RolEmpresa.objects.create(empresa=self.a, nombre='Coordinador de obra', rol_base=RolBase.MIEMBRO)
        RolPermiso.objects.create(rol_empresa=rol, capacidad='tar.etiquetas.manage', habilitado=True)
        u = User.objects.create_user('coord@example.com', 'x')
        agregar_miembro(u, self.a, rol)
        self.client.force_login(u)
        self.assertEqual(self.client.get('/embol/tareas/etiquetas/').status_code, 200)
