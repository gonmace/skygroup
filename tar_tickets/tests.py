from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from cuentas.capacidades import tiene_capacidad
from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from proyectos.models import Proyecto

from .models import Asignacion, ConfigTareas, Etiqueta, Ticket

E = Ticket.Estado


class BaseTareas(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Embol', slug='embol', modulos=['tar'])
        cls.b = crear_empresa(nombre='Tekon RL', slug='tekon-rl', modulos=['tar'])
        cls.u1 = User.objects.create_user('u1@example.com', 'x')
        cls.u2 = User.objects.create_user('u2@example.com', 'x')

    def ticket(self, empresa=None, **kw):
        kw.setdefault('titulo', 'T')
        kw.setdefault('solicitante', 'Cliente')
        return Ticket.objects.create(empresa=empresa or self.a, **kw)

    def asignar(self, t, user, tipo='EJECUTOR', estado=E.POR_HACER, **kw):
        return Asignacion.objects.create(ticket=t, user=user, tipo=tipo, estado=estado, **kw)


class CodigosTests(BaseTareas):
    def test_prefijo_por_defecto_desde_el_slug(self):
        self.assertEqual(ConfigTareas.de(self.a).prefijo, 'EMBOL')
        self.assertEqual(ConfigTareas.de(self.b).prefijo, 'TEKONR')  # sin guiones, máx. 6 letras
        ConfigTareas.objects.all().delete()
        corta = crear_empresa(nombre='X', slug='x1')
        self.assertEqual(ConfigTareas.de(corta).prefijo, 'TAR')

    def test_correlativo_independiente_por_empresa(self):
        self.assertEqual([self.ticket().codigo for _ in range(2)], ['EMBOL-0001', 'EMBOL-0002'])
        self.assertEqual(self.ticket(self.b).codigo, 'TEKONR-0001')
        self.assertEqual(self.ticket().codigo, 'EMBOL-0003')

    def test_cambiar_el_prefijo_no_reinicia_la_numeracion(self):
        self.ticket()
        cfg = ConfigTareas.de(self.a)
        cfg.prefijo = 'nuevo'
        cfg.save()
        self.assertEqual(self.ticket().codigo, 'NUEVO-0002')

    def test_hijos_encadenan_el_codigo_del_padre(self):
        p = self.ticket()
        h1, h2 = p.crear_hijo(titulo='a', solicitante='s'), p.crear_hijo(titulo='b', solicitante='s')
        self.assertEqual((h1.codigo, h2.codigo), ('EMBOL-0001-1', 'EMBOL-0001-2'))
        self.assertEqual(h1.crear_hijo(titulo='c', solicitante='s').codigo, 'EMBOL-0001-1-1')
        self.assertEqual(h1.empresa, self.a)
        # El correlativo de la empresa no se consumió por los hijos.
        self.assertEqual(self.ticket().codigo, 'EMBOL-0002')

    def test_hijo_tras_borrar_uno_no_reutiliza_el_numero(self):
        p = self.ticket()
        p.crear_hijo(titulo='a', solicitante='s')
        h2 = p.crear_hijo(titulo='b', solicitante='s')
        p.hijos.filter(codigo__endswith='-1').delete()
        self.assertEqual(p.crear_hijo(titulo='c', solicitante='s').codigo, 'EMBOL-0001-3')
        self.assertEqual(h2.codigo, 'EMBOL-0001-2')

    def test_codigo_unico_por_empresa(self):
        self.ticket(codigo='X-1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.ticket(codigo='X-1')
        self.ticket(self.b, codigo='X-1')  # otra empresa: permitido

    def test_ticket_sin_empresa_falla(self):
        with self.assertRaises(ValueError):
            Ticket(titulo='x', solicitante='y').save()

    def test_hereda_la_empresa_del_padre(self):
        p = self.ticket(self.b)
        h = Ticket.objects.create(titulo='h', solicitante='s', padre=p, codigo='H-1')
        self.assertEqual(h.empresa, self.b)


class AislamientoTests(BaseTareas):
    def test_proyecto_de_otra_empresa_rechazado(self):
        pb = Proyecto.objects.create(empresa=self.b, nombre='P', codigo='P1')
        with self.assertRaises(ValueError):
            self.ticket(proyecto=pb)
        t = Ticket(empresa=self.a, titulo='x', solicitante='y', proyecto=pb)
        with self.assertRaises(ValidationError):
            t.clean()

    def test_proyecto_de_la_misma_empresa_ok(self):
        pa = Proyecto.objects.create(empresa=self.a, nombre='P', codigo='P1')
        self.assertEqual(self.ticket(proyecto=pa).proyecto, pa)

    def test_etiqueta_unica_por_empresa_sin_distinguir_mayusculas(self):
        Etiqueta.objects.create(empresa=self.a, nombre='Urgente')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Etiqueta.objects.create(empresa=self.a, nombre='urgente')
        Etiqueta.objects.create(empresa=self.b, nombre='Urgente')


class EstadoAgregadoTests(BaseTareas):
    def test_sin_ejecutores_es_entrada(self):
        t = self.ticket()
        self.asignar(t, self.u1, tipo='EXPERTO')  # un experto no cuenta
        self.assertEqual(t.recalcular_estado(), E.ENTRADA)

    def test_matriz_de_estados(self):
        t = self.ticket()
        a1, a2 = self.asignar(t, self.u1), self.asignar(t, self.u2)
        self.assertEqual(t.recalcular_estado(), E.POR_HACER)
        a1.estado = E.EN_PROGRESO
        a1.save()
        self.assertEqual(t.recalcular_estado(), E.EN_PROGRESO)
        a1.estado = E.CONCLUIDO  # concluido pero SIN aprobar, y el otro sin empezar
        a1.save()
        self.assertEqual(t.recalcular_estado(), E.EN_PROGRESO)
        for a in (a1, a2):
            a.estado, a.aprobado_en = E.CONCLUIDO, timezone.now()
            a.save()
        self.assertEqual(t.recalcular_estado(), E.CONCLUIDO)
        self.assertIsNotNone(t.cerrado_en)
        a2.estado, a2.aprobado_en = E.SUSPENDIDO, None
        a2.save()
        self.assertEqual(t.recalcular_estado(), E.EN_PROGRESO)  # reabrir limpia el cierre
        self.assertIsNone(t.cerrado_en)

    def test_concluido_requiere_aprobacion(self):
        t = self.ticket()
        a = self.asignar(t, self.u1, estado=E.CONCLUIDO)  # sin aprobado_en
        self.assertTrue(a.necesita_aprobacion)
        self.assertEqual(t.recalcular_estado(), E.EN_PROGRESO)

    def test_todos_suspendidos(self):
        t = self.ticket()
        self.asignar(t, self.u1, estado=E.SUSPENDIDO)
        self.assertEqual(t.recalcular_estado(), E.SUSPENDIDO)

    def test_suspension_del_director_gana_incluso_sin_ejecutores(self):
        t = self.ticket(suspendido_en=timezone.now())
        self.assertTrue(t.esta_suspendido)
        self.assertEqual(t.recalcular_estado(), E.SUSPENDIDO)

    def test_vencido_solo_si_no_esta_concluido(self):
        ayer = timezone.localdate() - timedelta(days=1)
        self.assertTrue(self.ticket(vence=ayer).esta_vencido)
        self.assertFalse(self.ticket(vence=ayer, estado=E.CONCLUIDO).esta_vencido)
        self.assertFalse(self.ticket().esta_vencido)


class TiemposTests(BaseTareas):
    def test_solo_por_hacer_y_en_progreso_acumulan(self):
        t = self.ticket()
        a = self.asignar(t, self.u1)
        t0 = a.estado_cambiado_en
        a.avanzar_a(E.EN_PROGRESO, t0 + timedelta(hours=2))
        self.assertEqual(a.tiempo_por_hacer, timedelta(hours=2))
        self.assertEqual(a.iniciado_en, t0 + timedelta(hours=2))
        a.avanzar_a(E.SUSPENDIDO, t0 + timedelta(hours=5))
        self.assertEqual(a.tiempo_en_progreso, timedelta(hours=3))
        a.avanzar_a(E.EN_PROGRESO, t0 + timedelta(hours=100))  # la suspensión no suma
        a.avanzar_a(E.CONCLUIDO, t0 + timedelta(hours=101))
        self.assertEqual(a.tiempo_en_progreso, timedelta(hours=4))
        self.assertEqual(a.iniciado_en, t0 + timedelta(hours=2))  # el inicio no se pisa

    def test_tiempo_en_incluye_el_tramo_en_curso(self):
        a = self.asignar(self.ticket(), self.u1)
        t0 = a.estado_cambiado_en
        self.assertEqual(a.tiempo_en(E.POR_HACER, t0 + timedelta(hours=1)), timedelta(hours=1))
        self.assertEqual(a.tiempo_en(E.EN_PROGRESO, t0 + timedelta(hours=1)), timedelta())
        self.assertEqual(a.tiempo_en(E.CONCLUIDO), timedelta())

    def test_reabrir_invalida_la_conclusion(self):
        a = self.asignar(self.ticket(), self.u1)
        ahora = timezone.now()
        a.avanzar_a(E.CONCLUIDO, ahora)
        a.aprobado_en, a.cerrado_en = ahora, ahora
        a.avanzar_a(E.EN_PROGRESO, ahora + timedelta(hours=1))
        self.assertIsNone(a.aprobado_en)
        self.assertIsNone(a.cerrado_en)

    def test_una_persona_no_se_asigna_dos_veces_al_mismo_ticket(self):
        t = self.ticket()
        self.asignar(t, self.u1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.asignar(t, self.u1, tipo='EXPERTO')


class HiloTests(BaseTareas):
    def test_ids_hilo_incluye_ancestros_y_corta_ciclos(self):
        p = self.ticket()
        h = p.crear_hijo(titulo='h', solicitante='s')
        n = h.crear_hijo(titulo='n', solicitante='s')
        self.assertEqual(n.ids_hilo(), [n.pk, h.pk, p.pk])
        Ticket.objects.filter(pk=p.pk).update(padre=n)  # ciclo accidental
        self.assertLessEqual(len(Ticket.objects.get(pk=n.pk).ids_hilo()), 12)


class CapacidadesPorRolTests(BaseTareas):
    """El mapeo skydesk → RACI del catálogo registrado por la app."""

    def usuario(self, rol):
        u = User.objects.create_user(f'{rol.lower()}@example.com', 'x')
        agregar_miembro(u, self.a, rol_por_base(self.a, rol))
        return User.objects.get(pk=u.pk)

    def test_coordinador_tiene_todo(self):
        from cuentas.capacidades import claves
        tar = {c for c in claves() if c.startswith('tar.')}
        u = self.usuario(RolBase.COORDINADOR)
        self.assertTrue(all(tiene_capacidad(u, c, self.a) for c in tar))

    def test_miembro_mueve_y_escribe_pero_no_crea_ni_asigna(self):
        u = self.usuario(RolBase.MIEMBRO)
        self.assertTrue(tiene_capacidad(u, 'tar.tickets.move', self.a))
        self.assertTrue(tiene_capacidad(u, 'tar.chat.write', self.a))
        for c in ('tar.tickets.create', 'tar.tickets.assign', 'tar.tickets.view_all', 'tar.tickets.close'):
            self.assertFalse(tiene_capacidad(u, c, self.a), c)

    def test_especialista_tablero_por_ticket_sin_ver_todo(self):
        u = self.usuario(RolBase.ESPECIALISTA)
        self.assertTrue(tiene_capacidad(u, 'tar.tickets.board_by_ticket', self.a))
        self.assertTrue(tiene_capacidad(u, 'tar.dashboard.view', self.a))
        self.assertFalse(tiene_capacidad(u, 'tar.tickets.view_all', self.a))

    def test_observador_solo_lectura(self):
        u = self.usuario(RolBase.OBSERVADOR)
        for c in ('tar.tickets.view_all', 'tar.chat.view_all', 'tar.dashboard.view', 'tar.tickets.view_waiting'):
            self.assertTrue(tiene_capacidad(u, c, self.a), c)
        for c in ('tar.tickets.create', 'tar.tickets.move', 'tar.chat.write'):
            self.assertFalse(tiene_capacidad(u, c, self.a), c)

    def test_observador_no_aprueba_ni_edita(self):
        u = self.usuario(RolBase.OBSERVADOR)
        self.assertFalse(tiene_capacidad(u, 'tar.tickets.close', self.a))
        self.assertFalse(tiene_capacidad(u, 'tar.tickets.view_backlog', self.a))
        self.assertFalse(tiene_capacidad(u, 'tar.tickets.create', self.a))
        self.assertFalse(tiene_capacidad(u, 'tar.tickets.assign', self.a))
