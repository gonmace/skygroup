from django.test import TestCase, override_settings

from cuentas.models import RolEmpresa, RolPermiso, User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from proyectos.models import Proyecto

from .models import Asignacion, Etiqueta, Evento, Ticket

AJUSTES = dict(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
E = Ticket.Estado


def usuario(email, empresa, rol_base):
    u = User.objects.create_user(email, 'x', first_name=email.split('@')[0].title())
    agregar_miembro(u, empresa, rol_por_base(empresa, rol_base))
    return u


@override_settings(**AJUSTES)
class TableroTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Embol', slug='embol', modulos=['tar'])
        cls.b = crear_empresa(nombre='Otra', slug='otra', modulos=['tar'])
        cls.sin_tar = crear_empresa(nombre='Sin', slug='sintar', modulos=['reg'])
        cls.director = usuario('dir@example.com', cls.a, RolBase.COORDINADOR)
        cls.ejec1 = usuario('ejec1@example.com', cls.a, RolBase.MIEMBRO)
        cls.ejec2 = usuario('ejec2@example.com', cls.a, RolBase.MIEMBRO)
        cls.experto = usuario('exp@example.com', cls.a, RolBase.ESPECIALISTA)
        cls.lector = usuario('lector@example.com', cls.a, RolBase.OBSERVADOR)
        cls.director_b = usuario('dirb@example.com', cls.b, RolBase.COORDINADOR)

    def ticket(self, titulo='Tarea', empresa=None, creador=None, **kw):
        return Ticket.objects.create(empresa=empresa or self.a, titulo=titulo, solicitante='Cliente',
                                     creador=creador or self.director, **kw)

    def asignar(self, t, user, tipo='EJECUTOR', estado=E.POR_HACER):
        a = Asignacion.objects.create(ticket=t, user=user, tipo=tipo, estado=estado)
        t.recalcular_estado()  # como hace la app al asignar
        return a

    def columnas(self, user, empresa='embol', query=''):
        self.client.force_login(user)
        r = self.client.get(f'/{empresa}/tareas/{query}')
        self.assertEqual(r.status_code, 200)
        return {c['value']: c for c in r.context['columns']}, r

    # ── Acceso al módulo ──
    def test_modulo_no_habilitado_es_404(self):
        u = usuario('x@example.com', self.sin_tar, RolBase.COORDINADOR)
        self.client.force_login(u)
        self.assertEqual(self.client.get('/sintar/tareas/').status_code, 404)

    def test_anonimo_va_al_login(self):
        self.assertEqual(self.client.get('/embol/tareas/').status_code, 302)

    def test_no_miembro_no_entra_a_otra_empresa(self):
        self.client.force_login(self.director_b)
        self.assertEqual(self.client.get('/embol/tareas/').status_code, 403)

    # ── Columnas por rol ──
    def test_columnas_visibles_segun_capacidades(self):
        nombres = lambda u: [c['value'] for c in self.columnas(u)[0].values()]
        self.assertEqual(nombres(self.director), ['BACKLOG', 'TODO', 'IN_PROGRESS', 'DONE', 'WAITING'])
        self.assertEqual(nombres(self.ejec1), ['TODO', 'IN_PROGRESS', 'DONE'])        # sin Entrada ni Suspendido
        self.assertEqual(nombres(self.lector), ['TODO', 'IN_PROGRESS', 'DONE', 'WAITING'])
        self.assertEqual(nombres(self.experto), ['TODO', 'IN_PROGRESS', 'DONE'])

    def test_director_ve_todo_y_ejecutor_solo_lo_suyo(self):
        t1, t2 = self.ticket('Mio'), self.ticket('Ajeno')
        self.asignar(t1, self.ejec1)
        self.asignar(t2, self.ejec2)
        cols, r = self.columnas(self.director)
        self.assertEqual(r.context['board_mode'], 'ticket')
        self.assertEqual(cols['TODO']['count'], 2)
        cols, r = self.columnas(self.ejec1)
        self.assertEqual(r.context['board_mode'], 'subticket')
        titulos = [i['a'].ticket.titulo for i in cols['TODO']['items']]
        self.assertEqual(titulos, ['Mio'])

    def test_ticket_sin_ejecutores_cae_en_entrada(self):
        self.ticket('Nuevo')
        cols, _ = self.columnas(self.director)
        self.assertEqual(cols['BACKLOG']['count'], 1)

    def test_pendiente_de_aprobacion_se_ve_en_concluido(self):
        t = self.ticket()
        self.asignar(t, self.ejec1, estado=E.CONCLUIDO)  # concluyó, sin aprobar
        t.recalcular_estado()
        self.assertEqual(Ticket.objects.get(pk=t.pk).estado, E.EN_PROGRESO)
        cols, _ = self.columnas(self.director)
        self.assertEqual(cols['DONE']['count'], 1)
        self.assertTrue(cols['DONE']['items'][0]['t'].pendiente_aprobacion)
        self.assertContains(self.client.get('/embol/tareas/'), 'Pendiente de aprobación')

    def test_archivados_y_divididos_no_aparecen(self):
        from django.utils import timezone
        self.ticket('Visible')
        self.ticket('Archivado', archivado_en=timezone.now())
        self.ticket('Contenedor', dividido_en=timezone.now())
        cols, _ = self.columnas(self.director)
        self.assertEqual(sum(c['count'] for c in cols.values()), 1)

    # ── Subproductos ──
    def test_con_subproductos_el_director_ve_una_tarjeta_por_ejecutor_y_se_fusionan(self):
        t = self.ticket(tiene_subproductos=True)
        self.asignar(t, self.ejec1)
        self.asignar(t, self.ejec2)
        cols, _ = self.columnas(self.director)
        items = cols['TODO']['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['type'], 'merged')  # mismo estado → fusionadas
        self.assertEqual(len(items[0]['group']), 2)
        # Una avanza: se separan y se vinculan con el mismo color.
        a = t.asignaciones.get(user=self.ejec1)
        a.avanzar_a(E.EN_PROGRESO)
        a.save()
        cols, _ = self.columnas(self.director)
        self.assertEqual((cols['TODO']['count'], cols['IN_PROGRESS']['count']), (1, 1))
        colores = {cols[k]['items'][0]['a'].color_vinculo for k in ('TODO', 'IN_PROGRESS')}
        self.assertEqual(len(colores), 1)
        self.assertNotIn(None, colores)

    def test_ejecutor_ve_fantasmas_solo_con_subproductos(self):
        colab = self.ticket('Colaborativa')
        self.asignar(colab, self.ejec1)
        self.asignar(colab, self.ejec2)
        multi = self.ticket('Multi', tiene_subproductos=True)
        self.asignar(multi, self.ejec1)
        a2 = self.asignar(multi, self.ejec2)
        a2.avanzar_a(E.EN_PROGRESO)
        a2.save()
        cols, _ = self.columnas(self.ejec1)
        todo = cols['TODO']['items']
        self.assertEqual(sorted(i['a'].ticket.titulo if i['type'] == 'subticket' else i['ticket'].titulo for i in todo),
                         ['Colaborativa', 'Multi'])
        # La colaborativa fusiona (mismo estado) y la de multi muestra al otro ejecutor como fantasma.
        fantasmas = [i['a'] for i in cols['IN_PROGRESS']['items'] if i['type'] == 'subticket']
        self.assertTrue(all(a.es_fantasma for a in fantasmas))
        self.assertEqual(len(fantasmas), 1)

    def test_ticket_suspendido_bloquea_las_tarjetas(self):
        from django.utils import timezone
        t = self.ticket(suspendido_en=timezone.now())
        t.recalcular_estado()
        cols, _ = self.columnas(self.director)
        self.assertEqual(cols['WAITING']['count'], 1)
        self.assertContains(self.client.get('/embol/tareas/'), 'data-locked="1"')

    # ── Filtros ──
    def test_filtros_busqueda_asignado_proyecto(self):
        pr = Proyecto.objects.create(empresa=self.a, nombre='Torre', codigo='T1')
        t1 = self.ticket('Cambiar antena', proyecto=pr)
        t2 = self.ticket('Pintar poste')
        self.asignar(t1, self.ejec1)
        self.asignar(t2, self.ejec2)
        titulos = lambda q: sorted(i['t'].titulo for c in self.columnas(self.director, query=q)[0].values() for i in c['items'])
        self.assertEqual(titulos('?q=antena'), ['Cambiar antena'])
        self.assertEqual(titulos(f'?asignado={self.ejec2.pk}'), ['Pintar poste'])
        self.assertEqual(titulos(f'?proyecto={pr.pk}'), ['Cambiar antena'])
        self.assertEqual(titulos('?q=%'), [])

    def test_solo_ve_sus_tickets_si_no_tiene_view_all(self):
        propio, ajeno = self.ticket('Del experto'), self.ticket('Ajeno')
        self.asignar(propio, self.ejec1)  # con ejecutor sale de «Entrada», columna que el especialista no ve
        self.asignar(propio, self.experto, tipo='EXPERTO')
        self.asignar(ajeno, self.ejec2)
        cols, _ = self.columnas(self.experto)
        titulos = [i['t'].titulo for c in cols.values() for i in c['items']]
        self.assertEqual(titulos, ['Del experto'])

    # ── Aislamiento entre empresas ──
    def test_tickets_de_otra_empresa_no_aparecen_ni_se_abren(self):
        ajeno = self.ticket('Secreto', empresa=self.b, creador=self.director_b)
        cols, _ = self.columnas(self.director)
        self.assertEqual(sum(c['count'] for c in cols.values()), 0)
        self.client.force_login(self.director)
        self.assertEqual(self.client.get(f'/embol/tareas/{ajeno.pk}/').status_code, 404)

    def test_leyenda_agrupa_roles_por_rango_visible(self):
        self.client.force_login(self.director)
        filas = self.client.get('/embol/tareas/').context['status_legend']['rows']
        por_nombre = {n: (f['start'], f['end']) for f in filas for n in f['label'].split(' / ')}
        self.assertEqual(por_nombre['Coordinador'], (0, 4))
        self.assertEqual(por_nombre['Ejecutor'], (1, 3))
        self.assertNotIn('Observador', por_nombre)  # observador: no figura

    def test_rol_personalizado_cambia_las_columnas(self):
        ito = RolEmpresa.objects.create(empresa=self.a, nombre='ITO', rol_base=RolBase.MIEMBRO)
        RolPermiso.objects.create(rol_empresa=ito, capacidad='tar.tickets.view_waiting', habilitado=True)
        u = User.objects.create_user('ito@example.com', 'x')
        agregar_miembro(u, self.a, ito)
        cols, _ = self.columnas(u)
        self.assertIn('WAITING', cols)  # el ajuste del rol «ITO» no afecta a los demás Miembros
        self.assertNotIn('WAITING', self.columnas(self.ejec1)[0])


@override_settings(**AJUSTES)
class CrearTicketTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Embol', slug='embol', modulos=['tar'])
        cls.b = crear_empresa(nombre='Otra', slug='otra', modulos=['tar'])
        cls.director = usuario('dir@example.com', cls.a, RolBase.COORDINADOR)
        cls.ejec = usuario('ejec@example.com', cls.a, RolBase.MIEMBRO)
        cls.exp = usuario('exp@example.com', cls.a, RolBase.ESPECIALISTA)
        cls.ajeno = usuario('ajeno@example.com', cls.b, RolBase.MIEMBRO)
        cls.proy = Proyecto.objects.create(empresa=cls.a, nombre='Torre', codigo='T1')
        cls.etq = Etiqueta.objects.create(empresa=cls.a, nombre='Urgente')

    def datos(self, **extra):
        d = {'titulo': 'Revisar enlace', 'solicitante': 'Cliente SA', 'prioridad': 'HIGH'}
        d.update(extra)
        return d

    def test_crear_sin_asignar_queda_en_entrada(self):
        self.client.force_login(self.director)
        r = self.client.post('/embol/tareas/nuevo/', self.datos())
        t = Ticket.objects.get(titulo='Revisar enlace')
        self.assertRedirects(r, f'/embol/tareas/{t.pk}/', fetch_redirect_response=False)
        self.assertEqual((t.codigo, t.estado, t.creador, t.empresa), ('EMBOL-0001', E.ENTRADA, self.director, self.a))
        self.assertTrue(Evento.objects.filter(ticket=t, tipo='created').exists())

    def test_crear_con_ejecutores_pasa_a_por_hacer_y_notifica(self):
        from notificaciones.models import Notificacion
        self.client.force_login(self.director)
        self.client.post('/embol/tareas/nuevo/', self.datos(
            ejecutores=[self.ejec.pk], expertos=[self.exp.pk], proyecto=self.proy.pk, etiquetas=[self.etq.pk]))
        t = Ticket.objects.get()
        self.assertEqual(t.estado, E.POR_HACER)
        self.assertEqual(sorted(t.asignaciones.values_list('tipo', flat=True)), ['EJECUTOR', 'EXPERTO'])
        self.assertEqual((t.proyecto, list(t.etiquetas.all())), (self.proy, [self.etq]))
        n = Notificacion.objects.get(destinatario=self.ejec)
        self.assertEqual((n.url, n.actor), (f'/tareas/{t.pk}/', self.director))

    def test_el_director_no_puede_asignarse_a_si_mismo(self):
        self.client.force_login(self.director)
        r = self.client.post('/embol/tareas/nuevo/', self.datos(ejecutores=[self.director.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Ticket.objects.exists())

    def test_no_se_pueden_usar_personas_proyectos_ni_etiquetas_de_otra_empresa(self):
        pb = Proyecto.objects.create(empresa=self.b, nombre='P', codigo='P1')
        eb = Etiqueta.objects.create(empresa=self.b, nombre='Otra')
        self.client.force_login(self.director)
        for extra in ({'ejecutores': [self.ajeno.pk]}, {'proyecto': pb.pk}, {'etiquetas': [eb.pk]}):
            r = self.client.post('/embol/tareas/nuevo/', self.datos(**extra))
            self.assertEqual(r.status_code, 200, extra)
        self.assertFalse(Ticket.objects.exists())

    def test_un_especialista_no_es_ejecutor_y_un_miembro_no_es_experto(self):
        self.client.force_login(self.director)
        self.assertEqual(self.client.post('/embol/tareas/nuevo/', self.datos(ejecutores=[self.exp.pk])).status_code, 200)
        self.assertEqual(self.client.post('/embol/tareas/nuevo/', self.datos(expertos=[self.ejec.pk])).status_code, 200)
        self.assertFalse(Ticket.objects.exists())

    def test_miembro_sin_permiso_no_crea(self):
        self.client.force_login(self.ejec)
        self.assertEqual(self.client.get('/embol/tareas/nuevo/').status_code, 403)
        self.assertEqual(self.client.post('/embol/tareas/nuevo/', self.datos()).status_code, 403)
        self.assertFalse(Ticket.objects.exists())

    def test_quien_crea_sin_permiso_de_asignar_no_ve_los_campos(self):
        rol = RolEmpresa.objects.create(empresa=self.a, nombre='Creador', rol_base=RolBase.MIEMBRO)
        RolPermiso.objects.create(rol_empresa=rol, capacidad='tar.tickets.create', habilitado=True)
        u = User.objects.create_user('c@example.com', 'x')
        agregar_miembro(u, self.a, rol)
        self.client.force_login(u)
        r = self.client.get('/embol/tareas/nuevo/')
        self.assertNotIn('ejecutores', r.context['form'].fields)
        self.client.post('/embol/tareas/nuevo/', self.datos(ejecutores=[self.ejec.pk]))  # se ignora
        t = Ticket.objects.get()
        self.assertEqual((t.estado, t.asignaciones.count()), (E.ENTRADA, 0))

    def test_solicitante_obligatorio(self):
        self.client.force_login(self.director)
        r = self.client.post('/embol/tareas/nuevo/', self.datos(solicitante='   '))
        self.assertEqual(r.status_code, 200)

    def test_el_correlativo_es_por_empresa(self):
        self.client.force_login(self.director)
        self.client.post('/embol/tareas/nuevo/', self.datos())
        self.client.post('/embol/tareas/nuevo/', self.datos(titulo='Otro'))
        db = usuario('dirb@example.com', self.b, RolBase.COORDINADOR)
        self.client.force_login(db)
        self.client.post('/otra/tareas/nuevo/', self.datos(titulo='De la otra'))
        self.assertEqual(list(Ticket.objects.order_by('pk').values_list('codigo', flat=True)),
                         ['EMBOL-0001', 'EMBOL-0002', 'OTRA-0001'])


@override_settings(**AJUSTES)
class DetalleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Embol', slug='embol', modulos=['tar'])
        cls.director = usuario('dir@example.com', cls.a, RolBase.COORDINADOR)
        cls.ejec = usuario('ejec@example.com', cls.a, RolBase.MIEMBRO)
        cls.otro = usuario('otro@example.com', cls.a, RolBase.MIEMBRO)
        cls.t = Ticket.objects.create(empresa=cls.a, titulo='Detalle', solicitante='C', creador=cls.director)
        Asignacion.objects.create(ticket=cls.t, user=cls.ejec)

    def test_participante_y_director_ven_el_detalle(self):
        for u in (self.director, self.ejec):
            self.client.force_login(u)
            self.assertContains(self.client.get(f'/embol/tareas/{self.t.pk}/'), 'Detalle')

    def test_miembro_no_participante_recibe_403(self):
        self.client.force_login(self.otro)
        self.assertEqual(self.client.get(f'/embol/tareas/{self.t.pk}/').status_code, 403)

    def test_el_hilo_incluye_historial_del_padre(self):
        hijo = self.t.crear_hijo(titulo='Hijo', solicitante='C', creador=self.director)
        Evento.objects.create(ticket=self.t, actor=self.director, tipo='status', detalle='movió el padre')
        self.client.force_login(self.director)
        self.assertContains(self.client.get(f'/embol/tareas/{hijo.pk}/'), 'movió el padre')

    def test_el_tablero_esta_en_el_menu_de_tareas(self):
        self.client.force_login(self.director)
        r = self.client.get('/embol/tareas/')
        self.assertEqual(r.context['app_activa']['codigo'], 'tar')
        self.assertIn('Tablero', [i['nombre'] for i in r.context['menu_lateral']])


@override_settings(**AJUSTES)
class AdministradorSoloLecturaTests(TestCase):
    """El administrador de sistema que no es miembro ve el tablero, los tickets y el resumen de la empresa, pero no
    crea, mueve, edita, comenta, archiva ni elimina nada."""

    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Embol', slug='embol', modulos=['tar'])
        cls.b = crear_empresa(nombre='Otra', slug='otra', modulos=['tar'])
        cls.ejec = usuario('ejec@example.com', cls.a, RolBase.MIEMBRO)
        cls.adm = User.objects.create_user('adm@example.com', 'x')
        cls.adm.empresas_administradas.add(cls.a)
        cls.t = Ticket.objects.create(empresa=cls.a, titulo='Montar tablero', solicitante='Cliente')
        Asignacion.objects.create(ticket=cls.t, user=cls.ejec, tipo='EJECUTOR', estado=E.POR_HACER)

    def get(self, ruta, user=None):
        self.client.force_login(user or self.adm)
        return self.client.get(f'/embol/tareas/{ruta}')

    def post(self, ruta, **datos):
        self.client.force_login(self.adm)
        return self.client.post(f'/embol/tareas/{ruta}', datos)

    def test_ve_tablero_ticket_y_resumen(self):
        for ruta in ('', 'fragmento/', f'{self.t.pk}/', 'mis-tickets/', 'archivados/', 'seguimiento/', 'dashboard/'):
            self.assertEqual(self.get(ruta).status_code, 200, ruta)
        self.assertContains(self.get(''), 'Montar tablero')

    def test_no_crea_mueve_edita_comenta_archiva_ni_elimina(self):
        for ruta in ('nuevo/', 'mover/', f'{self.t.pk}/editar/', f'{self.t.pk}/comentar/', f'{self.t.pk}/archivar/',
                     f'{self.t.pk}/eliminar/', f'{self.t.pk}/aprobar/', f'{self.t.pk}/derivar/', 'etiquetas/'):
            self.assertEqual(self.post(ruta, texto='hola').status_code, 403, ruta)
        self.t.refresh_from_db()
        self.assertEqual((self.t.titulo, self.t.archivado_en), ('Montar tablero', None))
        self.assertEqual(self.t.comentarios.count(), 0)

    def test_el_administrador_de_otra_empresa_no_entra(self):
        otro = User.objects.create_user('otro@example.com', 'x')
        otro.empresas_administradas.add(self.b)
        self.assertEqual(self.get('', otro).status_code, 403)
        self.assertEqual(self.get(f'{self.t.pk}/', otro).status_code, 403)

    def test_los_cargos_no_cambian(self):
        lector = usuario('lector@example.com', self.a, RolBase.OBSERVADOR)
        self.client.force_login(lector)
        self.assertEqual(self.client.post(f'/embol/tareas/{self.t.pk}/editar/').status_code, 403)
