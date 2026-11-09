import json

from django.test import TestCase, override_settings

from cuentas.models import RolEmpresa, RolPermiso, User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from notificaciones.models import Notificacion

from .models import Asignacion, Comentario, Evento, Ticket

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
class BaseFlujo(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Embol', slug='embol', modulos=['tar'])
        cls.b = crear_empresa(nombre='Otra', slug='otra', modulos=['tar'])
        cls.sin_tar = crear_empresa(nombre='Sin', slug='sintar', modulos=['reg'])
        cls.director = usuario('dir@example.com', cls.a, RolBase.COORDINADOR)
        cls.ejec1 = usuario('ejec1@example.com', cls.a, RolBase.MIEMBRO)
        cls.ejec2 = usuario('ejec2@example.com', cls.a, RolBase.MIEMBRO)
        cls.lector = usuario('lector@example.com', cls.a, RolBase.OBSERVADOR)
        cls.director_b = usuario('dirb@example.com', cls.b, RolBase.COORDINADOR)

    def ticket(self, titulo='Tarea', empresa=None, **kw):
        kw.setdefault('creador', self.director)
        return Ticket.objects.create(empresa=empresa or self.a, titulo=titulo, solicitante='C', **kw)

    def asignar(self, t, user, estado=E.POR_HACER, tipo='EJECUTOR'):
        a = Asignacion.objects.create(ticket=t, user=user, tipo=tipo, estado=estado)
        t.recalcular_estado()
        return a

    def post_json(self, url, datos, user=None, slug='embol'):
        self.client.force_login(user or self.director)
        return self.client.post(f'/{slug}{url}', json.dumps(datos), content_type='application/json')

    def recargar(self, *objs):
        return [type(o).objects.get(pk=o.pk) for o in objs]


class MoverTicketTests(BaseFlujo):
    def test_ticket_sin_ejecutores_se_mueve_y_notifica_al_pasar_a_por_hacer(self):
        t = self.ticket()
        r = self.post_json('/tareas/mover/', {'status': 'TODO', 'order': [t.pk]})
        self.assertEqual(r.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.estado, E.POR_HACER)
        self.assertTrue(Evento.objects.filter(ticket=t, tipo='status', detalle__contains='Por hacer').exists())

    def test_con_ejecutores_sincroniza_los_subtickets(self):
        t = self.ticket()
        a1, a2 = self.asignar(t, self.ejec1), self.asignar(t, self.ejec2)
        self.post_json('/tareas/mover/', {'status': 'IN_PROGRESS', 'order': [t.pk]})
        t, a1, a2 = self.recargar(t, a1, a2)
        self.assertEqual((t.estado, a1.estado, a2.estado), (E.EN_PROGRESO, E.EN_PROGRESO, E.EN_PROGRESO))
        self.assertIsNotNone(a1.iniciado_en)

    def test_a_concluido_cierra_los_subtickets_pero_el_ticket_espera_aprobacion(self):
        t = self.ticket()
        a = self.asignar(t, self.ejec1)
        self.post_json('/tareas/mover/', {'status': 'DONE', 'order': [t.pk]})
        t, a = self.recargar(t, a)
        self.assertEqual((a.estado, a.necesita_aprobacion), (E.CONCLUIDO, True))
        self.assertEqual(t.estado, E.EN_PROGRESO)  # falta aprobar

    def test_con_ejecutores_no_vuelve_a_entrada(self):
        t = self.ticket()
        self.asignar(t, self.ejec1)
        self.post_json('/tareas/mover/', {'status': 'BACKLOG', 'order': [t.pk]})
        self.assertEqual(self.recargar(t)[0].estado, E.POR_HACER)

    def test_suspendido_por_el_director_no_se_mueve(self):
        from django.utils import timezone
        t = self.ticket(suspendido_en=timezone.now())
        t.recalcular_estado()
        self.post_json('/tareas/mover/', {'status': 'TODO', 'order': [t.pk]})
        self.assertEqual(self.recargar(t)[0].estado, E.SUSPENDIDO)

    def test_el_orden_se_persiste(self):
        t1, t2, t3 = self.ticket('a'), self.ticket('b'), self.ticket('c')
        self.post_json('/tareas/mover/', {'status': 'BACKLOG', 'order': [t3.pk, t1.pk, t2.pk]})
        self.assertEqual([self.recargar(t)[0].posicion for t in (t3, t1, t2)], [0, 1, 2])

    def test_no_mueve_tickets_de_otra_empresa(self):
        ajeno = self.ticket('Ajeno', empresa=self.b, creador=self.director_b)
        self.post_json('/tareas/mover/', {'status': 'TODO', 'order': [ajeno.pk]})
        self.assertEqual(self.recargar(ajeno)[0].estado, E.ENTRADA)

    def test_payload_y_estado_invalidos(self):
        self.client.force_login(self.director)
        for cuerpo in ('no es json', json.dumps({'order': []}), json.dumps({'status': 'X', 'order': [1]}),
                       json.dumps({'status': 'TODO', 'order': ['a']})):
            r = self.client.post('/embol/tareas/mover/', cuerpo, content_type='application/json')
            self.assertEqual(r.status_code, 400, cuerpo)

    def test_permisos(self):
        t = self.ticket()
        self.assertEqual(self.post_json('/tareas/mover/', {'status': 'TODO', 'order': [t.pk]}, self.ejec1).status_code, 403)
        self.assertEqual(self.post_json('/tareas/mover/', {'status': 'TODO', 'order': [t.pk]}, self.lector).status_code, 403)
        self.assertEqual(self.client.get('/embol/tareas/mover/').status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post('/embol/tareas/mover/', '{}', content_type='application/json').status_code, 302)

    def test_modulo_deshabilitado(self):
        u = usuario('x@example.com', self.sin_tar, RolBase.COORDINADOR)
        r = self.post_json('/tareas/mover/', {'status': 'TODO', 'order': []}, u, slug='sintar')
        self.assertEqual(r.status_code, 404)


class MoverSubticketTests(BaseFlujo):
    def test_ejecutor_mueve_su_subticket(self):
        t = self.ticket(tiene_subproductos=True)
        a1, a2 = self.asignar(t, self.ejec1), self.asignar(t, self.ejec2)
        r = self.post_json('/tareas/subticket/mover/', {'status': 'IN_PROGRESS', 'assignment': a1.pk}, self.ejec1)
        self.assertEqual(r.json()['parent_status'], 'IN_PROGRESS')
        a1, a2 = self.recargar(a1, a2)
        self.assertEqual((a1.estado, a2.estado), (E.EN_PROGRESO, E.POR_HACER))  # con subproductos: solo el propio

    def test_colaborativa_sincroniza_a_todos_los_ejecutores(self):
        t = self.ticket()
        a1, a2 = self.asignar(t, self.ejec1), self.asignar(t, self.ejec2)
        self.post_json('/tareas/subticket/mover/', {'status': 'IN_PROGRESS', 'assignment': a1.pk}, self.ejec1)
        self.assertEqual([a.estado for a in self.recargar(a1, a2)], [E.EN_PROGRESO] * 2)

    def test_ejecutor_no_mueve_el_subticket_de_otro_pero_el_director_si(self):
        t = self.ticket(tiene_subproductos=True)
        a1 = self.asignar(t, self.ejec1)
        self.assertEqual(self.post_json('/tareas/subticket/mover/', {'status': 'IN_PROGRESS', 'assignment': a1.pk},
                                        self.ejec2).status_code, 403)
        self.assertEqual(self.post_json('/tareas/subticket/mover/', {'status': 'IN_PROGRESS', 'assignment': a1.pk},
                                        self.director).status_code, 200)
        self.assertEqual(self.recargar(a1)[0].estado, E.EN_PROGRESO)

    def test_tarjeta_fusionada_mueve_el_grupo(self):
        t = self.ticket(tiene_subproductos=True)
        a1, a2 = self.asignar(t, self.ejec1), self.asignar(t, self.ejec2)
        self.post_json('/tareas/subticket/mover/', {'status': 'IN_PROGRESS', 'assignments': [a1.pk, a2.pk]})
        self.assertEqual([a.estado for a in self.recargar(a1, a2)], [E.EN_PROGRESO] * 2)

    def test_grupo_de_tickets_distintos_o_inexistente_es_rechazado(self):
        a1 = self.asignar(self.ticket('uno'), self.ejec1)
        a2 = self.asignar(self.ticket('dos'), self.ejec1)
        for ids in ([a1.pk, a2.pk], [99999]):
            r = self.post_json('/tareas/subticket/mover/', {'status': 'IN_PROGRESS', 'assignments': ids})
            self.assertEqual(r.status_code, 400, ids)

    def test_no_se_toca_una_asignacion_de_otra_empresa(self):
        ajeno = self.ticket('x', empresa=self.b, creador=self.director_b)
        ab = self.asignar(ajeno, usuario('eb@example.com', self.b, RolBase.MIEMBRO))
        r = self.post_json('/tareas/subticket/mover/', {'status': 'IN_PROGRESS', 'assignment': ab.pk})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.recargar(ab)[0].estado, E.POR_HACER)

    def test_estados_no_permitidos(self):
        a = self.asignar(self.ticket(), self.ejec1)
        self.assertEqual(self.post_json('/tareas/subticket/mover/', {'status': 'BACKLOG', 'assignment': a.pk},
                                        self.ejec1).status_code, 400)
        # El ejecutor no ve «Suspendido»: no se lo acepta aunque lo mande por POST directo.
        self.assertEqual(self.post_json('/tareas/subticket/mover/', {'status': 'WAITING', 'assignment': a.pk},
                                        self.ejec1).status_code, 400)
        self.assertEqual(self.recargar(a)[0].estado, E.POR_HACER)

    def test_ticket_suspendido_bloquea_al_ejecutor(self):
        t = self.ticket()
        a = self.asignar(t, self.ejec1)
        from .servicios import alternar_suspension
        alternar_suspension(t, self.director)
        r = self.post_json('/tareas/subticket/mover/', {'status': 'IN_PROGRESS', 'assignment': a.pk}, self.ejec1)
        self.assertEqual(r.status_code, 400)

    def test_arrastrar_a_concluido_concluye_y_avisa_a_quien_aprueba(self):
        t = self.ticket()
        a = self.asignar(t, self.ejec1)
        self.post_json('/tareas/subticket/mover/', {'status': 'DONE', 'assignment': a.pk}, self.ejec1)
        a, t = self.recargar(a, t)
        self.assertEqual((a.estado, a.necesita_aprobacion), (E.CONCLUIDO, True))
        n = Notificacion.objects.get(destinatario=self.director)
        self.assertIn('pendiente de aprobación', n.mensaje)
        self.assertEqual((n.actor, n.url), (self.ejec1, f'/tareas/{t.pk}/'))

    def test_sin_permiso_de_mover(self):
        a = self.asignar(self.ticket(), self.ejec1)
        r = self.post_json('/tareas/subticket/mover/', {'status': 'IN_PROGRESS', 'assignment': a.pk}, self.lector)
        self.assertEqual(r.status_code, 403)


class ConcluirAprobarTests(BaseFlujo):
    def test_concluir_con_texto_crea_mensaje_y_avisa(self):
        t = self.ticket()
        a = self.asignar(t, self.ejec1)
        self.client.force_login(self.ejec1)
        r = self.client.post(f'/embol/tareas/subticket/{a.pk}/concluir/', {'conclusion': 'Listo: https://x.cl/doc'})
        self.assertRedirects(r, '/embol/tareas/', fetch_redirect_response=False)
        a = self.recargar(a)[0]
        self.assertEqual((a.estado, a.conclusion), (E.CONCLUIDO, 'Listo: https://x.cl/doc'))
        self.assertTrue(Comentario.objects.filter(ticket=t, texto__startswith='Concluyó la tarea: Listo').exists())
        self.assertTrue(Notificacion.objects.filter(destinatario=self.director, mensaje__contains='pendiente').exists())

    def test_solo_se_concluye_el_subticket_propio(self):
        a = self.asignar(self.ticket(), self.ejec1)
        self.client.force_login(self.ejec2)
        self.assertEqual(self.client.post(f'/embol/tareas/subticket/{a.pk}/concluir/').status_code, 404)
        self.client.force_login(self.director)  # ni siquiera el director: es una acción personal
        self.assertEqual(self.client.post(f'/embol/tareas/subticket/{a.pk}/concluir/').status_code, 404)

    def test_no_concluye_si_esta_suspendido(self):
        from .servicios import alternar_suspension
        t = self.ticket()
        a = self.asignar(t, self.ejec1)
        alternar_suspension(t, self.director)
        self.client.force_login(self.ejec1)
        self.client.post(f'/embol/tareas/subticket/{a.pk}/concluir/')
        self.assertEqual(self.recargar(a)[0].estado, E.SUSPENDIDO)

    def concluido(self, ejecutores=1):
        t = self.ticket()
        asigs = [self.asignar(t, u) for u in (self.ejec1, self.ejec2)[:ejecutores]]
        for a in asigs:
            self.client.force_login(a.user)
            self.client.post(f'/embol/tareas/subticket/{a.pk}/concluir/')
        return t, asigs

    def test_aprobar_cierra_el_ticket_y_avisa(self):
        t, (a,) = self.concluido()
        self.client.force_login(self.director)
        self.client.post(f'/embol/tareas/{t.pk}/aprobar/')
        t, a = self.recargar(t, a)
        self.assertEqual(t.estado, E.CONCLUIDO)
        self.assertIsNotNone(t.cerrado_en)
        self.assertIsNotNone(a.aprobado_en)
        self.assertTrue(Notificacion.objects.filter(destinatario=self.ejec1, mensaje__contains='aprobó').exists())

    def test_con_dos_ejecutores_cierra_solo_cuando_ambos_concluyen_y_se_aprueba(self):
        t = self.ticket()
        a1, a2 = self.asignar(t, self.ejec1), self.asignar(t, self.ejec2)
        self.client.force_login(self.ejec1)
        self.client.post(f'/embol/tareas/subticket/{a1.pk}/concluir/')  # colaborativa: concluye a todos
        self.assertEqual([a.estado for a in self.recargar(a1, a2)], [E.CONCLUIDO] * 2)
        self.client.force_login(self.director)
        self.client.post(f'/embol/tareas/{t.pk}/aprobar/')
        self.assertEqual(self.recargar(t)[0].estado, E.CONCLUIDO)

    def test_solo_quien_cierra_puede_aprobar_rechazar_o_suspender(self):
        t, _ = self.concluido()
        self.client.force_login(self.ejec1)
        for accion in ('aprobar', 'rechazar', 'suspender'):
            self.assertEqual(self.client.post(f'/embol/tareas/{t.pk}/{accion}/').status_code, 403, accion)

    def test_rechazar_exige_motivo_y_devuelve_a_en_progreso(self):
        t, (a,) = self.concluido()
        self.client.force_login(self.director)
        self.client.post(f'/embol/tareas/{t.pk}/rechazar/', {'feedback': '   '})
        self.assertEqual(self.recargar(a)[0].estado, E.CONCLUIDO)  # sin motivo no pasa nada
        self.client.post(f'/embol/tareas/{t.pk}/rechazar/', {'feedback': 'Falta el informe'})
        t, a = self.recargar(t, a)
        self.assertEqual((a.estado, a.aprobado_en, a.cerrado_en, t.estado), (E.EN_PROGRESO, None, None, E.EN_PROGRESO))
        self.assertTrue(Comentario.objects.filter(ticket=t, texto='Rechazó la conclusión: Falta el informe').exists())
        self.assertTrue(Notificacion.objects.filter(destinatario=self.ejec1, mensaje__contains='rechazó').exists())

    def test_aprobar_dos_veces_es_inocuo(self):
        t, _ = self.concluido()
        self.client.force_login(self.director)
        self.client.post(f'/embol/tareas/{t.pk}/aprobar/')
        cerrado = self.recargar(t)[0].cerrado_en
        self.client.post(f'/embol/tareas/{t.pk}/aprobar/')
        self.assertEqual(self.recargar(t)[0].cerrado_en, cerrado)

    def test_no_aprueba_tickets_de_otra_empresa(self):
        ajeno = self.ticket('x', empresa=self.b, creador=self.director_b)
        self.client.force_login(self.director)
        self.assertEqual(self.client.post(f'/embol/tareas/{ajeno.pk}/aprobar/').status_code, 404)

    def test_botones_del_detalle_segun_rol(self):
        t, _ = self.concluido()
        self.client.force_login(self.director)
        html = self.client.get(f'/embol/tareas/{t.pk}/').content.decode()
        for texto in ('Aprobar conclusi', 'Rechazar', 'Suspender'):
            self.assertIn(texto, html)
        self.client.force_login(self.ejec2)
        self.assertEqual(self.client.get(f'/embol/tareas/{t.pk}/').status_code, 403)  # no participa


class SuspenderTests(BaseFlujo):
    def test_suspender_y_reactivar_restaura_cada_estado(self):
        t = self.ticket(tiene_subproductos=True)
        a1, a2 = self.asignar(t, self.ejec1), self.asignar(t, self.ejec2)
        a1.avanzar_a(E.EN_PROGRESO)
        a1.save()
        self.client.force_login(self.director)
        self.client.post(f'/embol/tareas/{t.pk}/suspender/')
        t, a1, a2 = self.recargar(t, a1, a2)
        self.assertEqual((t.estado, a1.estado, a2.estado), (E.SUSPENDIDO, E.SUSPENDIDO, E.SUSPENDIDO))
        self.assertIsNotNone(t.suspendido_en)
        self.client.post(f'/embol/tareas/{t.pk}/suspender/')  # reactivar
        t, a1, a2 = self.recargar(t, a1, a2)
        self.assertEqual((a1.estado, a2.estado, t.suspendido_en), (E.EN_PROGRESO, E.POR_HACER, None))
        self.assertEqual(t.estado, E.EN_PROGRESO)

    def test_suspender_no_toca_los_concluidos(self):
        t = self.ticket(tiene_subproductos=True)
        a1, a2 = self.asignar(t, self.ejec1), self.asignar(t, self.ejec2)
        self.client.force_login(self.ejec1)
        self.client.post(f'/embol/tareas/subticket/{a1.pk}/concluir/')
        self.client.force_login(self.director)
        self.client.post(f'/embol/tareas/{t.pk}/suspender/')
        a1, a2 = self.recargar(a1, a2)
        self.assertEqual((a1.estado, a2.estado), (E.CONCLUIDO, E.SUSPENDIDO))
        self.client.post(f'/embol/tareas/{t.pk}/suspender/')
        self.assertEqual(self.recargar(a1)[0].estado, E.CONCLUIDO)

    def test_avisa_a_las_personas_del_ticket(self):
        t = self.ticket()
        self.asignar(t, self.ejec1)
        self.client.force_login(self.director)
        self.client.post(f'/embol/tareas/{t.pk}/suspender/')
        self.assertTrue(Notificacion.objects.filter(destinatario=self.ejec1, mensaje__contains='suspendió').exists())
        self.assertFalse(Notificacion.objects.filter(destinatario=self.director).exists())  # no se avisa a sí mismo

    def test_rol_personalizado_con_close_puede_suspender(self):
        rol = RolEmpresa.objects.create(empresa=self.a, nombre='Jefe de obra', rol_base=RolBase.MIEMBRO)
        RolPermiso.objects.create(rol_empresa=rol, capacidad='tar.tickets.close', habilitado=True)
        u = User.objects.create_user('jefe@example.com', 'x')
        agregar_miembro(u, self.a, rol)
        t = self.ticket()
        self.asignar(t, u)   # además de la capacidad, debe poder ver el ticket (participa en él)
        self.client.force_login(u)
        self.assertEqual(self.client.post(f'/embol/tareas/{t.pk}/suspender/').status_code, 302)
        self.assertIsNotNone(self.recargar(t)[0].suspendido_en)

    def test_sin_visibilidad_no_se_puede_actuar_sobre_el_ticket(self):
        """Tener la capacidad no basta: un ticket que la persona no puede ver responde 403 en todas las acciones."""
        rol = RolEmpresa.objects.create(empresa=self.a, nombre='Jefe de obra', rol_base=RolBase.MIEMBRO)
        for cap in ('tar.tickets.close', 'tar.tickets.create', 'tar.tickets.unarchive'):
            RolPermiso.objects.create(rol_empresa=rol, capacidad=cap, habilitado=True)
        u = User.objects.create_user('jefe@example.com', 'x')
        agregar_miembro(u, self.a, rol)
        t = self.ticket()   # ni lo creó ni participa
        self.client.force_login(u)
        for accion in ('aprobar', 'rechazar', 'suspender', 'derivar', 'dividir', 'desarchivar'):
            self.assertEqual(self.client.post(f'/embol/tareas/{t.pk}/{accion}/').status_code, 403, accion)
        self.assertIsNone(self.recargar(t)[0].suspendido_en)


class BorrarAdjuntoTests(BaseFlujo):
    """Solo el autor del adjunto (o quien tiene edit_any) puede borrarlo, aunque otro pueda escribir en el chat."""

    def adjunto(self, t, subido_por, comentario=None):
        from django.core.files.base import ContentFile
        from tar_adjuntos.models import Adjunto
        a = Adjunto(empresa=self.a, ticket=t, comentario=comentario, nombre='x.txt', mime_type='text/plain',
                    subido_por=subido_por)
        a.archivo.save('x.txt', ContentFile(b'hola'), save=False)
        a.save()
        return a

    def borrar(self, a, user):
        self.client.force_login(user)
        return self.client.post(f'/embol/tareas/adjunto/{a.pk}/borrar/')

    def test_ajeno_no_puede_borrar_adjunto_de_ticket(self):
        t = self.ticket()
        self.asignar(t, self.ejec1)
        self.asignar(t, self.ejec2)
        a = self.adjunto(t, self.ejec1)
        self.assertEqual(self.borrar(a, self.ejec2).status_code, 403)
        a.refresh_from_db()
        self.assertEqual(self.borrar(a, self.ejec1).status_code, 302)

    def test_ajeno_no_puede_borrar_adjunto_de_mensaje(self):
        t = self.ticket()
        self.asignar(t, self.ejec1)
        self.asignar(t, self.ejec2)
        c = Comentario.objects.create(ticket=t, autor=self.ejec1, texto='hola')
        a = self.adjunto(t, self.ejec1, comentario=c)
        self.assertEqual(self.borrar(a, self.ejec2).status_code, 403)
        self.assertEqual(self.borrar(a, self.director).status_code, 302)
