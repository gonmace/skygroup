import json
import time
from datetime import date, datetime, timedelta
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from empresas.models import Contratista, Sede
from jor_empleados.models import ConfigJornadas, EquipoMarcacion, Perfil
from notificaciones.models import Notificacion
from proyectos.models import Proyecto

from . import servicios
from .models import Ausencia, Jornada, NotaCalendario, ReporteDiario

SEDE_LAT, SEDE_LON = -16.500000, -68.150000

AJUSTES = dict(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


def persona(email, empresa, rol_base, contratista=None):
    u = User.objects.create_user(email, 'x', first_name=email.split('@')[0].title())
    agregar_miembro(u, empresa, rol_por_base(empresa, rol_base), contratista)
    return u


@override_settings(**AJUSTES)
class JornadasBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Tekon', slug='tekon', modulos=['jor'])
        cls.b = crear_empresa(nombre='Otra', slug='otra', modulos=['jor'])
        cls.sin = crear_empresa(nombre='Sin', slug='sin', modulos=['tar'])
        cls.pmo = persona('pmo@x.cl', cls.a, RolBase.COORDINADOR)
        # Coordinador acotado a un contratista: gestiona al equipo pero no la configuración de la empresa.
        cls.contratista = Contratista.objects.create(empresa=cls.a, nombre='Redes SA', codigo='C1')
        cls.dir = persona('dir@x.cl', cls.a, RolBase.COORDINADOR, cls.contratista)
        cls.emp = persona('emp@x.cl', cls.a, RolBase.MIEMBRO)
        cls.emp2 = persona('emp2@x.cl', cls.a, RolBase.MIEMBRO)
        cls.patro = persona('patro@x.cl', cls.a, RolBase.OBSERVADOR)
        cls.vis = persona('vis@x.cl', cls.a, RolBase.OBSERVADOR)
        cls.ajeno = persona('ajeno@x.cl', cls.b, RolBase.MIEMBRO)
        cls.proy = Proyecto.objects.create(empresa=cls.a, nombre='Torre 1', codigo='T1')
        cls.proy_b = Proyecto.objects.create(empresa=cls.b, nombre='Otra torre', codigo='T1')
        cls.sede = Sede.objects.create(empresa=cls.a, nombre='Central', lat=SEDE_LAT, lon=SEDE_LON, radio_m=80,
                                       precision_max_m=50)
        for u in (cls.emp, cls.emp2, cls.dir, cls.pmo):
            m = u.membresias.get(empresa=cls.a)
            m.sede = cls.sede
            m.save()

    def setUp(self):
        cache.clear()

    def perfil(self, user, empresa=None):
        return Perfil.de(user.membresias.get(empresa=empresa or self.a))

    # ── Marcación: sesión + ubicación (sin geocerca) + equipo habitual ──
    def lecturas(self, metros_norte=0, acc=10.0, n=3, edad_s=0):
        """n lecturas de GPS recientes, a `metros_norte` metros al norte de la sede."""
        lat = SEDE_LAT + metros_norte / 111_320
        ahora = int(time.time() * 1000) - edad_s * 1000
        return [{'lat': lat + i * 1e-6, 'lon': SEDE_LON, 'accuracy': acc, 'timestamp': ahora - (n - 1 - i) * 1200}
                for i in range(n)]

    def ini(self, p, proyecto=None, lecturas=None, **kw):
        return servicios.iniciar(p, lecturas if lecturas is not None else self.lecturas(), proyecto, **kw)

    def fin(self, jornada_id, p, realizado='', planificado='', lecturas=None, **kw):
        return servicios.finalizar(jornada_id, p, lecturas if lecturas is not None else self.lecturas(),
                                   realizado, planificado, **kw)

    UA_PC = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36'
    UA_MOVIL = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36'

    def ir(self, user, ruta, datos=None, slug='tekon', lecturas=None, ua=None, equipo=None):
        self.client.force_login(user)
        url = f'/{slug}/jornadas/{ruta}'
        if datos is None:
            return self.client.get(url)
        extra = {'HTTP_USER_AGENT': ua or self.UA_PC}
        if equipo is not None:
            self.client.cookies['jor_equipo'] = equipo
        if ruta in ('iniciar/', 'finalizar/'):
            datos = {**datos, 'lecturas': json.dumps(self.lecturas() if lecturas is None else lecturas)}
        return self.client.post(url, datos, **extra)


class ServiciosTests(JornadasBase):
    def test_iniciar_y_finalizar_con_reporte(self):
        p = self.perfil(self.emp)
        j = self.ini(p, proyecto=self.proy)
        self.assertEqual((j.estado, j.proyecto), ('en_curso', self.proy))
        self.assertEqual(servicios.jornada_en_curso(p), j)
        j2 = self.fin(j.pk, p, ' Hice varias tareas de obra durante la jornada de hoy ', 'Haré la revisión mañana')
        self.assertEqual((j2.estado, j2.cierre_auto), ('completada', False))
        self.assertIsNotNone(j2.duracion_min)
        r = ReporteDiario.objects.get()
        self.assertEqual((r.realizado, r.planificado), ('Hice varias tareas de obra durante la jornada de hoy', 'Haré la revisión mañana'))

    def test_sin_reporte_no_se_crea_el_reporte(self):
        p = self.perfil(self.emp)
        p.exige_reporte = False
        p.save()
        self.fin(self.ini(p).pk, p)
        self.assertFalse(ReporteDiario.objects.exists())

    def test_una_sola_jornada_activa(self):
        p = self.perfil(self.emp)
        self.ini(p)
        with self.assertRaisesMessage(servicios.ErrorJornada, 'Ya tienes una jornada activa'):
            self.ini(p)
        self.assertEqual(Jornada.objects.count(), 1)

    def test_el_proyecto_debe_ser_de_la_empresa(self):
        with self.assertRaises(servicios.ErrorJornada):
            self.ini(self.perfil(self.emp), proyecto=self.proy_b)

    def test_perfil_deshabilitado_o_membresia_inactiva_no_ficha(self):
        p = self.perfil(self.emp)
        Perfil.objects.filter(pk=p.pk).update(activo=False)
        p.refresh_from_db()
        with self.assertRaises(servicios.ErrorJornada):
            self.ini(p)

    def test_reporte_obligatorio_exige_ambos_textos(self):
        p = self.perfil(self.emp)
        p.exige_reporte = True
        p.save()
        j = self.ini(p)
        with self.assertRaises(servicios.ErrorJornada) as e:
            self.fin(j.pk, p, 'solo hecho', '')
        self.assertTrue(e.exception.extra.get('reporte_requerido'))
        with self.assertRaises(servicios.ErrorJornada) as e:  # mínimos: 10 palabras realizadas, 3 planificadas
            self.fin(j.pk, p, 'muy pocas palabras', 'Haré la revisión mañana')
        self.assertIn('al menos 10', str(e.exception))
        with self.assertRaises(servicios.ErrorJornada) as e:
            self.fin(j.pk, p, 'Hice varias tareas de obra durante la jornada de hoy', 'dos palabras')
        self.assertIn('al menos 3', str(e.exception))
        self.fin(j.pk, p, 'Hice varias tareas de obra durante la jornada de hoy', 'Haré la revisión mañana')

    def test_no_se_finaliza_la_jornada_de_otro(self):
        j = self.ini(self.perfil(self.emp))
        with self.assertRaises(servicios.ErrorJornada):
            self.fin(j.pk, self.perfil(self.emp2))
        j.refresh_from_db()
        self.assertTrue(j.abierta)

    def test_cierre_automatico_de_jornadas_vencidas(self):
        ayer = timezone.make_aware(datetime.combine(timezone.localdate() - timedelta(days=1), datetime.min.time())).replace(hour=9)
        tarde = ayer.replace(hour=18)
        p1, p2 = self.perfil(self.emp), self.perfil(self.emp2)
        vieja = Jornada.objects.create(empresa=self.a, perfil=p1, inicio=ayer)
        tardia = Jornada.objects.create(empresa=self.a, perfil=p2, inicio=tarde)
        de_hoy = Jornada.objects.create(empresa=self.a, perfil=self.perfil(self.dir), inicio=timezone.now())
        self.assertEqual(servicios.cerrar_vencidas(), 2)
        vieja.refresh_from_db(); tardia.refresh_from_db(); de_hoy.refresh_from_db()
        self.assertEqual((vieja.estado, vieja.cierre_auto, vieja.duracion_min), ('incompleta', True, 8 * 60))
        self.assertEqual(tardia.duracion_min, 1)
        self.assertTrue(de_hoy.abierta)
        self.assertEqual(Notificacion.objects.filter(destinatario=self.emp).count(), 1)
        self.assertEqual(servicios.cerrar_vencidas(), 0)
        call_command('cerrar_jornadas_vencidas')


class VistasTests(JornadasBase):
    def test_iniciar_y_finalizar_desde_la_web(self):
        r = self.ir(self.emp, '')
        self.assertContains(r, 'Iniciar jornada')
        self.assertContains(r, 'Torre 1')
        self.ir(self.emp, 'iniciar/', {'proyecto': self.proy.pk})
        j = Jornada.objects.get()
        self.assertContains(self.ir(self.emp, ''), 'Finalizar jornada')
        self.ir(self.emp, 'finalizar/', {'jornada': j.pk, 'realizado': 'Hice varias tareas de obra durante la jornada de hoy', 'planificado': 'Haré la revisión mañana'})
        j.refresh_from_db()
        self.assertEqual(j.estado, 'completada')
        self.assertContains(self.ir(self.emp, 'mis-reportes/'), 'Hice varias tareas de obra durante la jornada de hoy')

    def inicio_empresa(self, user):
        self.client.force_login(user)
        return self.client.get('/tekon/')

    def test_indicador_del_estado_de_la_jornada_en_mi_jornada_y_en_la_tarjeta_del_modulo(self):
        # Sin iniciar
        r = self.ir(self.emp, '')
        self.assertEqual(r.context['estado_hoy'], 'sin_iniciar')
        self.assertContains(r, 'Aún no has iniciado tu jornada')
        self.assertNotContains(r, 'Sin inicio')          # ya no va en la barra superior
        self.assertContains(self.inicio_empresa(self.emp), 'Sin inicio')   # sino en la tarjeta del módulo
        # En curso
        self.ir(self.emp, 'iniciar/', {'proyecto': self.proy.pk})
        r = self.ir(self.emp, '')
        self.assertEqual(r.context['estado_hoy'], 'en_curso')
        self.assertContains(self.inicio_empresa(self.emp), 'Jornada activa')
        self.assertContains(r, 'data-jor-reloj')
        # Cerrada
        j = Jornada.objects.get()
        self.ir(self.emp, 'finalizar/', {'jornada': j.pk, 'realizado': 'Hice varias tareas de obra durante la jornada de hoy', 'planificado': 'Haré la revisión mañana'})
        r = self.ir(self.emp, '')
        self.assertEqual(r.context['estado_hoy'], 'cerrada')
        self.assertContains(self.inicio_empresa(self.emp), 'Jornada cerrada')

    def test_el_indicador_es_solo_de_los_ejecutores(self):
        for u in (self.pmo, self.patro, self.dir):   # Coordinador, Observador y Coordinador acotado
            self.assertNotContains(self.inicio_empresa(u), 'Sin inicio', msg_prefix=u.email)
        self.assertContains(self.inicio_empresa(self.emp), 'Sin inicio')

    def test_sin_perfil_activo_no_hay_indicador(self):
        p = self.perfil(self.emp)
        Perfil.objects.filter(pk=p.pk).update(activo=False)
        self.assertNotContains(self.inicio_empresa(self.emp), 'Sin inicio')   # la tarjeta no muestra el indicador

    def test_proyecto_de_otra_empresa_o_basura_se_rechaza(self):
        for valor in (self.proy_b.pk, 'abc'):
            self.ir(self.emp, 'iniciar/', {'proyecto': valor})
        self.assertFalse(Jornada.objects.exists())

    def test_finalizar_con_id_basura_no_rompe(self):
        self.assertEqual(self.ir(self.emp, 'finalizar/', {'jornada': 'abc'}).status_code, 400)

    def test_acceso_por_capacidad_y_modulo(self):
        self.assertEqual(self.ir(self.vis, '').status_code, 403)                # el observador no ficha
        self.assertEqual(self.ir(self.emp, 'equipo/').status_code, 403)         # ni ve al equipo
        self.assertEqual(self.ir(self.dir, 'equipo/').status_code, 403)       # Coordinador acotado: jor.equipo.ver es de ámbito empresa
        self.assertEqual(self.ir(self.pmo, 'equipo/').status_code, 200)
        self.assertEqual(self.ir(self.patro, 'equipo/').status_code, 403)      # el observador no ve al equipo
        self.assertEqual(self.ir(self.ajeno, '').status_code, 403)              # miembro de otra empresa
        self.assertEqual(self.ir(self.emp, '', slug='sin').status_code, 403)
        agregar_miembro(self.pmo, self.sin, rol_por_base(self.sin, RolBase.COORDINADOR))
        self.assertEqual(self.ir(self.pmo, '', slug='sin').status_code, 404)    # módulo no habilitado
        self.client.logout()
        self.assertEqual(self.client.get('/tekon/jornadas/').status_code, 302)

    def test_equipo_muestra_estados(self):
        self.ini(self.perfil(self.emp))
        Ausencia.objects.create(empresa=self.a, perfil=self.perfil(self.emp2), desde=date.today(), hasta=date.today(),
                                tipo='permiso', estado='aprobada')
        html = self.ir(self.pmo, 'equipo/').content.decode()
        for t in ('Activa', 'Ausente', 'usuarios'):
            self.assertIn(t, html)
        # Solo el nivel de acceso Ejecutor: el Coordinador (pmo) no figura en la tabla del equipo
        self.assertIn(f'equipo/{self.emp.membresias.get(empresa=self.a).pk}/', html)
        self.assertNotIn(f'equipo/{self.pmo.membresias.get(empresa=self.a).pk}/', html)

    def test_persona_solo_de_la_propia_empresa(self):
        m = self.ajeno.membresias.get()
        self.assertEqual(self.ir(self.pmo, f'equipo/{m.pk}/').status_code, 404)
        self.assertEqual(self.ir(self.pmo, f'equipo/{self.emp.membresias.get().pk}/?mes=2026-02').status_code, 200)
        self.assertEqual(self.ir(self.pmo, f'equipo/{self.emp.membresias.get().pk}/?mes=basura').status_code, 200)

    def test_editar_perfil_solo_pmo(self):
        m = self.emp.membresias.get()
        url = f'/tekon/jornadas/equipo/{m.pk}/perfil/'
        self.client.force_login(self.dir)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.pmo)
        r = self.client.post(url, {'cargo': 'Supervisor', 'hora_entrada': '07:30', 'activo': 'on'})
        self.assertEqual(r.status_code, 302)
        p = self.perfil(self.emp)
        self.assertEqual((p.cargo, p.hora_entrada.hour, p.activo), ('Supervisor', 7, True))
        r = self.client.post(url, {'cargo': 'x', 'hora_entrada': '25:00', 'activo': 'on'})
        self.assertEqual(r.status_code, 200)                                    # hora inválida: vuelve al formulario
        self.assertEqual(self.client.get(f'/tekon/jornadas/equipo/{self.ajeno.membresias.get().pk}/perfil/').status_code, 404)


class AusenciasTests(JornadasBase):
    datos = {'tipo': 'vacacion', 'desde': '2026-07-01', 'hasta': '2026-07-05', 'nota': 'viaje'}

    def test_solicitud_pendiente_notifica_y_se_aprueba(self):
        self.ir(self.emp, 'ausencias/', self.datos)
        a = Ausencia.objects.get()
        self.assertEqual((a.estado, a.perfil), ('pendiente', self.perfil(self.emp)))
        self.assertTrue(Notificacion.objects.filter(destinatario=self.pmo).exists())
        self.assertFalse(Notificacion.objects.filter(destinatario=self.emp).exists())
        self.assertEqual(self.ir(self.emp, f'ausencias/{a.pk}/decidir/', {'decision': 'aprobar'}).status_code, 403)
        self.ir(self.dir, f'ausencias/{a.pk}/decidir/', {'decision': 'aprobar'})
        a.refresh_from_db()
        self.assertEqual((a.estado, a.decidida_por), ('aprobada', self.dir))
        self.assertTrue(Notificacion.objects.filter(destinatario=self.emp, mensaje__contains='aprobada').exists())
        self.assertEqual(self.ir(self.dir, f'ausencias/{a.pk}/decidir/', {'decision': 'rechazar'}).status_code, 404)

    def test_rechazo(self):
        self.ir(self.emp, 'ausencias/', self.datos)
        a = Ausencia.objects.get()
        self.ir(self.pmo, f'ausencias/{a.pk}/decidir/', {'decision': 'rechazar'})
        a.refresh_from_db()
        self.assertEqual(a.estado, 'rechazada')

    def test_quien_gestiona_registra_aprobadas_para_otros(self):
        self.perfil(self.emp)
        self.ir(self.pmo, 'ausencias/', dict(self.datos, perfil=self.perfil(self.emp).pk))
        a = Ausencia.objects.get()
        self.assertEqual((a.estado, a.perfil), ('aprobada', self.perfil(self.emp)))
        self.assertTrue(Notificacion.objects.filter(destinatario=self.emp).exists())

    def test_no_se_puede_registrar_para_el_perfil_de_otra_empresa(self):
        pb = self.perfil(self.ajeno, self.b)
        r = self.ir(self.pmo, 'ausencias/', dict(self.datos, perfil=pb.pk))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Ausencia.objects.exists())

    def test_nota_obligatoria_salvo_vacacion(self):
        r = self.ir(self.emp, 'ausencias/', dict(self.datos, tipo='permiso', nota=''))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Ausencia.objects.exists())
        self.ir(self.emp, 'ausencias/', dict(self.datos, nota=''))             # vacación: sin nota vale
        self.assertEqual(Ausencia.objects.count(), 1)

    def test_fechas_invertidas(self):
        r = self.ir(self.emp, 'ausencias/', dict(self.datos, desde='2026-07-09'))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Ausencia.objects.exists())

    def test_cancelar_solo_la_propia_pendiente(self):
        self.ir(self.emp, 'ausencias/', self.datos)
        a = Ausencia.objects.get()
        self.assertEqual(self.ir(self.emp2, f'ausencias/{a.pk}/eliminar/', {}).status_code, 403)
        self.ir(self.emp, f'ausencias/{a.pk}/eliminar/', {})
        self.assertFalse(Ausencia.objects.exists())

    def test_el_interesado_ve_la_pagina_sin_formulario(self):
        r = self.ir(self.vis, 'ausencias/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Solicitar ausencia')


class CalendarioTests(JornadasBase):
    def test_gestion_de_notas(self):
        self.assertEqual(self.ir(self.emp, 'calendario/', {'fecha': '2026-09-18', 'tipo': 'feriado', 'texto': 'Fiestas'}).status_code, 200)
        self.assertFalse(NotaCalendario.objects.exists())
        r = self.ir(self.dir, 'calendario/', {'fecha': '2026-09-18', 'tipo': 'feriado', 'texto': 'Fiestas'})
        self.assertEqual(r.status_code, 302)
        n = NotaCalendario.objects.get()
        self.assertContains(self.ir(self.emp, 'calendario/?mes=2026-09'), 'Fiestas')
        self.assertNotContains(self.ir(self.emp, 'calendario/?mes=2026-10'), 'Fiestas')
        self.assertEqual(self.ir(self.emp, f'calendario/{n.pk}/eliminar/', {}).status_code, 403)
        self.assertEqual(self.ir(self.ajeno, f'calendario/{n.pk}/eliminar/', {}, slug='otra').status_code, 403)
        self.ir(self.dir, f'calendario/{n.pk}/eliminar/', {})
        self.assertFalse(NotaCalendario.objects.exists())

    def test_notas_aisladas_por_empresa(self):
        NotaCalendario.objects.create(empresa=self.b, fecha=date(2026, 9, 1), texto='Secreta')
        self.assertNotContains(self.ir(self.emp, 'calendario/?mes=2026-09'), 'Secreta')


class ResumenTests(JornadasBase):
    """Resumen de Jornadas: solo Coordinador (administración), Observador y superusuario."""

    def setUp(self):
        super().setUp()
        self.p_emp, self.p_emp2 = self.perfil(self.emp), self.perfil(self.emp2)
        ahora = timezone.now()
        Jornada.objects.create(empresa=self.a, perfil=self.p_emp, proyecto=self.proy, inicio=ahora)   # en curso
        Jornada.objects.create(empresa=self.a, perfil=self.p_emp2, inicio=ahora - timedelta(minutes=1),
                               fin=ahora, duracion_min=120, estado=Jornada.Estado.COMPLETADA)

    def resumen(self, user, slug='tekon'):
        self.client.force_login(user)
        return self.client.get(f'/{slug}/jornadas/resumen/')

    def test_acceso_por_rol(self):
        for u in (self.pmo, self.patro, self.vis):
            self.assertEqual(self.resumen(u).status_code, 200, u.email)
        for u in (self.emp, self.dir):   # Ejecutor y Coordinador acotado a un contratista
            self.assertEqual(self.resumen(u).status_code, 403, u.email)
        self.assertEqual(self.resumen(self.ajeno, 'otra').status_code, 403)

    def test_kpis_y_listas(self):
        hoy = timezone.localdate()
        Ausencia.objects.create(empresa=self.a, perfil=self.perfil(self.dir), desde=hoy, hasta=hoy,
                                tipo=Ausencia.Tipo.PERMISO, estado=Ausencia.Estado.PENDIENTE)
        c = self.resumen(self.pmo).context
        self.assertEqual((c['kpis']['en_curso'], c['kpis']['termino'], c['kpis']['pendientes']), (1, 1, 1))
        self.assertEqual([p['nombre'] for p in c['en_curso']], [str(self.emp)])
        self.assertEqual(c['total'], 4)   # pmo, dir, emp, emp2 (los observadores no fichan)
        self.assertEqual(len(c['serie']), 14)
        self.assertEqual(c['proyectos'][0]['label'], 'Sin proyecto')

    def test_la_empresa_ajena_no_se_mezcla(self):
        c = self.resumen(self.pmo).context
        self.assertEqual(c['total'], 4)
        self.client.force_login(persona('pmob@x.cl', self.b, RolBase.COORDINADOR))
        c = self.client.get('/otra/jornadas/resumen/').context
        self.assertEqual((c['kpis']['presentes'], c['kpis']['horas_30']), (0, '0h 00m'))

    def test_el_resumen_es_la_primera_entrada_del_menu_de_quien_lo_ve(self):
        menu = lambda u: [i['nombre'] for i in (self.client.force_login(u) or self.client.get('/tekon/jornadas/resumen/')).context['menu_lateral']]
        self.assertEqual(menu(self.patro)[0], 'Resumen')
        self.assertEqual(menu(self.pmo)[0], 'Resumen')

    def test_menu_en_tres_grupos_con_el_calendario_en_equipo(self):
        def menu(u):
            self.client.force_login(u)
            return [(i['seccion'], i['nombre']) for i in self.client.get('/tekon/jornadas/resumen/' if u in (self.pmo, self.patro) else '/tekon/jornadas/').context['menu_lateral']]
        pmo = menu(self.pmo)
        self.assertEqual(pmo[0], ('', 'Resumen'))
        self.assertEqual([n for s, n in pmo if s == 'Mi trabajo'], ['Mi jornada', 'Mis reportes', 'Ausencias'])
        self.assertEqual([n for s, n in pmo if s == 'Equipo'][:2], ['Equipo', 'Calendario'])
        self.assertIn(('Equipo', 'Calendario'), menu(self.emp))   # todo miembro ve el calendario
        self.assertIn(('Equipo', 'Calendario'), menu(self.patro))


# ── Verificación de presencia (función pura) ─────────────────────────────────────────────────────
class MarcacionTests(JornadasBase):
    def test_pc_inicia_con_ubicacion_y_queda_verificada(self):
        j = self.ini(self.perfil(self.emp), lecturas=self.lecturas(metros_norte=10), ip='10.0.0.5')
        self.assertEqual((j.estado_verificacion, j.ip_inicio), ('verificada', '10.0.0.5'))
        self.assertAlmostEqual(float(j.lat_inicio), SEDE_LAT, places=3)
        self.assertEqual((j.verificacion['inicio']['motivos'], j.verificacion['inicio']['origen']), ([], 'pc'))

    def test_no_hay_geocerca_lejos_de_la_sede_tambien_queda_verificada(self):
        j = self.ini(self.perfil(self.emp), lecturas=self.lecturas(metros_norte=5000, acc=400))
        self.assertEqual(j.estado_verificacion, 'verificada')
        self.assertEqual(j.precision_inicio, 400)

    def test_se_guarda_la_lectura_mas_precisa(self):
        ls = self.lecturas(acc=60) + self.lecturas(metros_norte=20, acc=5, n=1)
        j = self.ini(self.perfil(self.emp), lecturas=ls)
        self.assertEqual(j.precision_inicio, 5)
        self.assertEqual(j.verificacion['inicio']['n_lecturas'], 4)

    def test_sin_ubicacion_no_se_inicia_ni_se_finaliza(self):
        p = self.perfil(self.emp)
        for malas in ([], [{'lat': 'x'}], 'basura', [{'lat': 999, 'lon': 0, 'accuracy': 5, 'timestamp': 1}]):
            with self.assertRaises(servicios.ErrorJornada) as e:
                self.ini(p, lecturas=malas)
            self.assertTrue(e.exception.extra.get('ubicacion_requerida'))
        j = self.ini(p)
        with self.assertRaises(servicios.ErrorJornada) as e:
            self.fin(j.pk, p, 'Hice varias tareas de obra durante la jornada de hoy', 'Haré la revisión mañana', lecturas=[])
        self.assertTrue(e.exception.extra.get('ubicacion_requerida'))

    def test_finalizar_registra_la_ubicacion_y_el_origen(self):
        p = self.perfil(self.emp)
        j = self.fin(self.ini(p).pk, p, 'Hice varias tareas de obra durante la jornada de hoy', 'Haré la revisión mañana',
                     lecturas=self.lecturas(metros_norte=900), ip='10.0.0.9')
        self.assertEqual((j.estado, j.estado_verificacion, j.ip_fin), ('completada', 'verificada', '10.0.0.9'))
        self.assertEqual(j.verificacion['fin']['origen'], 'pc')
        self.assertIsNotNone(j.lat_fin)

    def test_celular_sin_permiso_no_inicia_ni_finaliza(self):
        p = self.perfil(self.emp)
        with self.assertRaises(servicios.ErrorJornada) as e:
            self.ini(p, movil=True)
        self.assertTrue(e.exception.extra.get('solo_pc'))
        j = self.ini(p)                                    # desde el PC sí
        with self.assertRaises(servicios.ErrorJornada) as e:
            self.fin(j.pk, p, 'Hice varias tareas de obra durante la jornada de hoy', 'Haré la revisión mañana', movil=True)
        self.assertTrue(e.exception.extra.get('solo_pc'))

    def test_celular_con_permiso_inicia_y_finaliza(self):
        p = self.perfil(self.emp)
        Perfil.objects.filter(pk=p.pk).update(puede_movil=True)
        p.refresh_from_db()
        j = self.ini(p, movil=True)
        self.assertEqual(j.verificacion['inicio']['origen'], 'celular')
        j = self.fin(j.pk, p, 'Hice varias tareas de obra durante la jornada de hoy', 'Haré la revisión mañana', movil=True)
        self.assertEqual((j.estado, j.verificacion['fin']['origen']), ('completada', 'celular'))

    def test_perfil_deshabilitado_no_marca(self):
        p = self.perfil(self.emp)
        Perfil.objects.filter(pk=p.pk).update(activo=False)
        p.refresh_from_db()
        with self.assertRaises(servicios.ErrorJornada):
            self.ini(p)


def con_cambio_equipo(p, tipo='pc'):
    """(habitual activo, nuevo inactivo con `.habitual`) como lo deja `equipos.resolver` ante un equipo distinto."""
    habitual = EquipoMarcacion.objects.create(perfil=p, tipo=tipo, token_hash='h' * 64, activo=True)
    nuevo = EquipoMarcacion.objects.create(perfil=p, tipo=tipo, token_hash='n' * 64, activo=False)
    nuevo.habitual = habitual
    return habitual, nuevo


class EquipoHabitualTests(JornadasBase):
    def test_cambio_de_equipo_pide_motivo_y_queda_pendiente(self):
        p = self.perfil(self.emp)
        _, nuevo = con_cambio_equipo(p)
        with self.assertRaises(servicios.ErrorJornada) as e:
            self.ini(p, equipo=nuevo, cambio_equipo=True)
        self.assertTrue(e.exception.extra.get('cambio_equipo'))
        self.assertFalse(Jornada.objects.exists())
        j = self.ini(p, equipo=nuevo, cambio_equipo=True, motivo='Mi PC está en reparación')
        self.assertEqual((j.estado_verificacion, j.equipo_inicio), ('excepcion_pendiente', nuevo))
        self.assertIn('cambio_equipo', j.verificacion['inicio']['motivos'])
        n = Notificacion.objects.filter(destinatario=self.pmo)       # configuración por defecto: admins y coordinadores
        self.assertEqual(n.count(), 1)
        self.assertIn('Mi PC está en reparación', n.get().mensaje)

    def test_cerrar_desde_otro_equipo_pasa_la_jornada_a_revision(self):
        p = self.perfil(self.emp)
        j = self.ini(p)
        _, nuevo = con_cambio_equipo(p)
        args = (j.pk, p, 'Hice varias tareas de obra durante la jornada de hoy', 'Haré la revisión mañana')
        with self.assertRaises(servicios.ErrorJornada):
            self.fin(*args, equipo=nuevo, cambio_equipo=True)
        j = self.fin(*args, equipo=nuevo, cambio_equipo=True, motivo='Otro PC')
        self.assertEqual((j.estado, j.estado_verificacion, j.equipo_fin), ('completada', 'excepcion_pendiente', nuevo))
        self.assertFalse(Jornada.objects.computables().filter(pk=j.pk).exists())

    def test_cerrar_desde_otro_equipo_vuelve_a_revision_aunque_el_inicio_estuviera_aprobado(self):
        p = self.perfil(self.emp)
        _, nuevo = con_cambio_equipo(p)
        j = self.ini(p, equipo=nuevo, cambio_equipo=True, motivo='PC nuevo')
        servicios.decidir_excepcion(j.pk, self.a, self.pmo, True)            # aprobada con la jornada aún abierta
        otro = EquipoMarcacion.objects.create(perfil=p, tipo='pc', token_hash='o' * 64, activo=False)
        otro.habitual = nuevo
        j = self.fin(j.pk, p, 'Hice varias tareas de obra durante la jornada de hoy', 'Haré la revisión mañana',
                     equipo=otro, cambio_equipo=True, motivo='Otro más')
        self.assertEqual(j.estado_verificacion, 'excepcion_pendiente')
        self.assertIsNone(j.revisada_por)
        self.assertFalse(Jornada.objects.computables().filter(pk=j.pk).exists())

    def test_resolver_registra_el_primero_reconoce_y_detecta_el_cambio(self):
        from jor_empleados import equipos
        p = self.perfil(self.emp)
        self.client.force_login(self.emp)
        r1 = self.client.post('/tekon/jornadas/iniciar/', {'lecturas': json.dumps(self.lecturas())}, HTTP_USER_AGENT=self.UA_PC)
        self.assertEqual(r1.status_code, 200)
        token = r1.cookies['jor_equipo'].value
        self.assertEqual(r1.json()['equipo'], token)
        eq = p.equipos.get(activo=True)
        self.assertEqual((eq.tipo, eq.token_hash), ('pc', equipos._hash(token)))
        j = Jornada.objects.get()
        self.assertEqual(j.equipo_inicio, eq)
        self.assertEqual(j.estado_verificacion, 'verificada')
        # mismo equipo (cookie del cliente): cierra sin aviso
        r2 = self.client.post('/tekon/jornadas/finalizar/', {'jornada': j.pk, 'realizado': 'Hice varias tareas de obra durante la jornada de hoy', 'planificado': 'Haré la revisión mañana', 'lecturas': json.dumps(self.lecturas())}, HTTP_USER_AGENT=self.UA_PC)
        self.assertEqual((r2.status_code, r2.json()['ok']), (200, True))
        self.assertEqual(Jornada.objects.get().estado_verificacion, 'verificada')
        # otro equipo (sin cookie): avisa, pide motivo y no marca
        self.client.cookies.clear()
        self.client.force_login(self.emp)
        r3 = self.client.post('/tekon/jornadas/iniciar/', {'lecturas': json.dumps(self.lecturas())}, HTTP_USER_AGENT=self.UA_PC)
        self.assertEqual(r3.status_code, 400)
        self.assertTrue(r3.json()['cambio_equipo'])
        self.assertEqual(Jornada.objects.count(), 1)
        r4 = self.client.post('/tekon/jornadas/iniciar/', {'lecturas': json.dumps(self.lecturas()), 'motivo': 'PC nuevo', 'equipo': r3.json()['equipo']}, HTTP_USER_AGENT=self.UA_PC)
        self.assertEqual(r4.status_code, 200)
        self.assertEqual(Jornada.objects.latest('inicio').estado_verificacion, 'excepcion_pendiente')
        self.assertEqual(p.equipos.filter(activo=True).get(), eq)        # el habitual no cambia solo

    def test_pc_y_celular_tienen_equipos_independientes(self):
        p = self.perfil(self.emp)
        Perfil.objects.filter(pk=p.pk).update(puede_movil=True)
        r = self.ir(self.emp, 'iniciar/', {}, ua=self.UA_MOVIL)
        self.assertEqual(r.status_code, 200)
        r = self.ir(self.emp, 'finalizar/', {'jornada': Jornada.objects.get().pk, 'realizado': 'Hice varias tareas de obra durante la jornada de hoy', 'planificado': 'Haré la revisión mañana'}, ua=self.UA_PC)
        self.assertEqual(r.status_code, 200)       # primer PC: se registra, no es un cambio
        self.assertEqual(sorted(p.equipos.filter(activo=True).values_list('tipo', flat=True)), ['movil', 'pc'])
        self.assertEqual(Jornada.objects.get().estado_verificacion, 'verificada')

    def test_liberar_el_equipo_permite_registrar_otro_sin_revision(self):
        p = self.perfil(self.emp)
        con_cambio_equipo(p)
        m = self.emp.membresias.get(empresa=self.a)
        url = f'/tekon/jornadas/equipo/{m.pk}/equipo/pc/liberar/'
        self.client.force_login(self.dir)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.pmo)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(p.equipos.filter(activo=True).exists())
        self.assertEqual(self.client.post(f'/tekon/jornadas/equipo/{m.pk}/equipo/otro/liberar/').status_code, 404)
        r = self.ir(self.emp, 'iniciar/', {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Jornada.objects.get().estado_verificacion, 'verificada')

    def test_quien_revisa_se_elige_en_la_configuracion(self):
        admin = persona('adm@x.cl', self.a, RolBase.OBSERVADOR)
        admin.empresas_administradas.add(self.a)
        p = self.perfil(self.emp)
        _, nuevo = con_cambio_equipo(p)
        cfg = ConfigJornadas.de(self.a)
        cfg.revisa_cambio_equipo = 'admin'
        cfg.save()
        j = self.ini(p, equipo=nuevo, cambio_equipo=True, motivo='Otro PC')
        self.assertTrue(Notificacion.objects.filter(destinatario=admin).exists())
        self.assertFalse(Notificacion.objects.filter(destinatario=self.pmo).exists())
        with self.assertRaisesMessage(servicios.ErrorJornada, 'revisa'):
            servicios.decidir_excepcion(j.pk, self.a, self.pmo, True)       # un coordinador no la decide
        servicios.decidir_excepcion(j.pk, self.a, admin, True)
        cfg.revisa_cambio_equipo = 'coordinador'
        cfg.save()
        self.assertEqual([u.pk for u in servicios.revisores_cambio_equipo(self.a) if u.pk == admin.pk], [])

    def test_aprobar_y_registrar_adopta_el_equipo(self):
        p = self.perfil(self.emp)
        habitual, nuevo = con_cambio_equipo(p)
        j = self.ini(p, equipo=nuevo, cambio_equipo=True, motivo='PC nuevo')
        servicios.decidir_excepcion(j.pk, self.a, self.pmo, True, adoptar_equipo=True)
        habitual.refresh_from_db()
        nuevo.refresh_from_db()
        self.assertEqual((habitual.activo, nuevo.activo), (False, True))

    def test_aprobar_sin_adoptar_deja_el_habitual(self):
        p = self.perfil(self.emp)
        habitual, nuevo = con_cambio_equipo(p)
        j = self.ini(p, equipo=nuevo, cambio_equipo=True, motivo='Prestado')
        servicios.decidir_excepcion(j.pk, self.a, self.pmo, True)
        habitual.refresh_from_db()
        self.assertTrue(habitual.activo)


class DetectarCelularTests(JornadasBase):
    def test_es_movil(self):
        from django.test import RequestFactory
        from .dispositivo import es_movil
        rf = RequestFactory()
        self.assertFalse(es_movil(rf.post('/', HTTP_USER_AGENT=self.UA_PC)))
        self.assertTrue(es_movil(rf.post('/', HTTP_USER_AGENT=self.UA_MOVIL)))
        self.assertTrue(es_movil(rf.post('/', HTTP_USER_AGENT=self.UA_PC, HTTP_SEC_CH_UA_MOBILE='?1')))
        self.assertTrue(es_movil(rf.post('/', {'tipo': 'movil'}, HTTP_USER_AGENT=self.UA_PC)))     # lo que calcula el JS (iPad…)
        self.assertFalse(es_movil(rf.post('/', HTTP_USER_AGENT=self.UA_PC, HTTP_SEC_CH_UA_MOBILE='?0')))


class ExcepcionesTests(JornadasBase):
    def pendiente(self, user=None):
        p = self.perfil(user or self.emp)
        _, nuevo = con_cambio_equipo(p)
        return self.ini(p, equipo=nuevo, cambio_equipo=True, motivo='Cliente')

    def test_aprobar_la_hace_computable(self):
        j = self.pendiente()
        self.assertFalse(Jornada.objects.computables().filter(pk=j.pk).exists())
        servicios.decidir_excepcion(j.pk, self.a, self.pmo, True)
        j.refresh_from_db()
        self.assertEqual((j.estado_verificacion, j.revisada_por), ('excepcion_aprobada', self.pmo))
        self.assertTrue(Jornada.objects.computables().filter(pk=j.pk).exists())
        self.assertTrue(Notificacion.objects.filter(destinatario=self.emp, mensaje__contains='aprobada').exists())

    def test_rechazar_cierra_la_jornada_abierta_y_libera_a_la_persona(self):
        j = self.pendiente()
        servicios.decidir_excepcion(j.pk, self.a, self.pmo, False)
        j.refresh_from_db()
        self.assertEqual((j.estado_verificacion, j.estado), ('rechazada', 'incompleta'))
        self.assertFalse(Jornada.objects.computables().filter(pk=j.pk).exists())
        self.ini(self.perfil(self.emp))            # puede volver a marcar

    def test_no_se_decide_dos_veces_ni_la_propia(self):
        j = self.pendiente()
        with self.assertRaisesMessage(servicios.ErrorJornada, 'propia'):
            servicios.decidir_excepcion(j.pk, self.a, self.emp, True)
        servicios.decidir_excepcion(j.pk, self.a, self.pmo, True)
        with self.assertRaises(servicios.ErrorJornada):
            servicios.decidir_excepcion(j.pk, self.a, self.pmo, False)

    def test_otra_empresa_no_puede_decidir(self):
        j = self.pendiente()
        with self.assertRaises(servicios.ErrorJornada):
            servicios.decidir_excepcion(j.pk, self.b, self.ajeno, True)

    def test_bandeja_solo_con_capacidad(self):
        j = self.pendiente()
        self.assertEqual(self.ir(self.emp, 'excepciones/').status_code, 403)
        self.assertEqual(self.ir(self.dir, 'excepciones/').status_code, 403)      # Coordinador acotado: capacidad de ámbito empresa
        r = self.ir(self.pmo, 'excepciones/')
        self.assertContains(r, 'Cliente')
        self.assertContains(r, 'Aprobar y registrar este equipo como habitual')
        r = self.ir(self.pmo, f'excepciones/{j.pk}/decidir/', {'decision': 'aprobar'})
        self.assertEqual(r.status_code, 302)
        j.refresh_from_db()
        self.assertEqual(j.estado_verificacion, 'excepcion_aprobada')
        self.assertEqual(self.ir(self.pmo, f'excepciones/{j.pk}/decidir/', {'decision': 'otra'}).status_code, 403)
        self.assertEqual(self.ir(self.emp, f'excepciones/{j.pk}/decidir/', {'decision': 'rechazar'}).status_code, 403)

    def test_los_pendientes_no_cuentan_hasta_aprobarlos(self):
        j = self.pendiente()
        Jornada.objects.filter(pk=j.pk).update(estado='completada', fin=j.inicio + timedelta(hours=8), duracion_min=480)
        self.assertEqual(Jornada.objects.computables().count(), 0)
        servicios.decidir_excepcion(j.pk, self.a, self.pmo, True)
        self.assertEqual(Jornada.objects.computables().count(), 1)


class VistasMarcacionTests(JornadasBase):
    def test_iniciar_desde_el_pc_responde_ok_y_pone_la_cookie_del_equipo(self):
        r = self.ir(self.emp, 'iniciar/', {})
        self.assertEqual((r.status_code, r.json()['ok']), (200, True))
        self.assertIn('jor_equipo', r.cookies)
        self.assertTrue(r.cookies['jor_equipo']['httponly'])

    def test_celular_sin_permiso_recibe_solo_pc_y_no_marca(self):
        r = self.ir(self.emp, 'iniciar/', {}, ua=self.UA_MOVIL)
        self.assertEqual((r.status_code, r.json().get('solo_pc')), (400, True))
        self.assertFalse(Jornada.objects.exists())
        r = self.ir(self.emp, 'iniciar/', {'tipo': 'movil'})        # señal del JS aunque el UA parezca de escritorio
        self.assertEqual(r.status_code, 400)

    def test_celular_con_permiso_marca(self):
        Perfil.objects.filter(pk=self.perfil(self.emp).pk).update(puede_movil=True)
        self.assertEqual(self.ir(self.emp, 'iniciar/', {}, ua=self.UA_MOVIL).status_code, 200)
        j = Jornada.objects.get()
        r = self.ir(self.emp, 'finalizar/', {'jornada': j.pk, 'realizado': 'Hice varias tareas de obra durante la jornada de hoy', 'planificado': 'Haré la revisión mañana'}, ua=self.UA_MOVIL)
        self.assertEqual(r.status_code, 200)

    def test_celular_sin_permiso_no_finaliza_pero_el_pc_si(self):
        j = self.ini(self.perfil(self.emp))
        datos = {'jornada': j.pk, 'realizado': 'Hice varias tareas de obra durante la jornada de hoy', 'planificado': 'Haré la revisión mañana'}
        self.assertEqual(self.ir(self.emp, 'finalizar/', datos, ua=self.UA_MOVIL).status_code, 400)
        self.assertEqual(Jornada.objects.get().estado, 'en_curso')
        self.assertEqual(self.ir(self.emp, 'finalizar/', datos).status_code, 200)

    def test_sin_ubicacion_no_marca(self):
        r = self.ir(self.emp, 'iniciar/', {}, lecturas=[])
        self.assertEqual((r.status_code, r.json()['ubicacion_requerida']), (400, True))

    def test_json_mal_formado(self):
        self.client.force_login(self.emp)
        r = self.client.post('/tekon/jornadas/iniciar/', {'lecturas': 'x'})
        self.assertEqual(r.status_code, 400)

    def test_pagina_de_inicio_segun_dispositivo_y_permiso(self):
        self.client.force_login(self.emp)
        r = self.client.get('/tekon/jornadas/', HTTP_USER_AGENT=self.UA_PC)
        self.assertContains(r, 'Iniciar jornada')
        self.assertNotContains(r, 'desde la computadora')
        r = self.client.get('/tekon/jornadas/', HTTP_USER_AGENT=self.UA_MOVIL)
        self.assertContains(r, 'Inicia tu jornada desde la computadora')
        Perfil.objects.filter(pk=self.perfil(self.emp).pk).update(puede_movil=True)
        r = self.client.get('/tekon/jornadas/', HTTP_USER_AGENT=self.UA_MOVIL)
        self.assertNotContains(r, 'Inicia tu jornada desde la computadora')

    def test_toggle_celular_solo_con_permiso_de_perfiles(self):
        m = self.emp.membresias.get(empresa=self.a)
        url = f'/tekon/jornadas/equipo/{m.pk}/movil/'
        self.client.force_login(self.emp)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.pmo)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertTrue(self.perfil(self.emp).puede_movil)
        self.client.post(url)
        self.assertFalse(self.perfil(self.emp).puede_movil)

    def test_equipo_y_persona_muestran_los_equipos_y_el_toggle(self):
        con_cambio_equipo(self.perfil(self.emp))
        m = self.emp.membresias.get(empresa=self.a)
        r = self.ir(self.pmo, 'equipo/')
        self.assertContains(r, 'Marca desde el celular')
        self.assertContains(r, 'Clic para liberar')
        self.assertContains(self.ir(self.pmo, f'equipo/{m.pk}/'), 'Computador habitual')


class MapaEquipoTests(JornadasBase):
    def test_solo_superusuario_y_administrador(self):
        self.ini(self.perfil(self.emp))
        self.assertEqual(self.ir(self.pmo, 'equipo/mapa/').status_code, 403)       # coordinador sin ser admin
        self.assertEqual(self.ir(self.emp, 'equipo/mapa/').status_code, 403)
        self.assertNotContains(self.ir(self.pmo, 'equipo/'), 'equipo/mapa/')

    def test_superusuario_y_administrador_ven_los_puntos(self):
        self.ini(self.perfil(self.emp))
        su = User.objects.create_user('su@x.cl', 'x', is_superuser=True)
        r = self.ir(su, 'equipo/mapa/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([(p['tipo'], p['nombre']) for p in r.context['puntos']], [('inicio', 'Emp')])
        self.assertContains(self.ir(su, 'equipo/'), 'equipo/mapa/')
        self.pmo.empresas_administradas.add(self.a)
        self.assertEqual(self.ir(self.pmo, 'equipo/mapa/').status_code, 200)


class SinJornadaPropiaTests(JornadasBase):
    """Superusuarios y administradores de la empresa no llevan jornada propia (aunque tengan membresía)."""

    def _admin(self):
        self.pmo.empresas_administradas.add(self.a)
        self.pmo.__dict__.pop('_administra', None)
        self.pmo.__dict__.pop('_caps', None)
        return self.pmo

    def _super(self):
        su = User.objects.create_superuser('root@x.cl', 'x')
        agregar_miembro(su, self.a, rol_por_base(self.a, RolBase.MIEMBRO))
        return su

    def test_lleva_jornada(self):
        self.assertTrue(servicios.lleva_jornada(self.emp, self.a))
        self.assertFalse(servicios.lleva_jornada(self._admin(), self.a))
        self.assertFalse(servicios.lleva_jornada(self._super(), self.a))
        self.assertTrue(servicios.lleva_jornada(self.pmo, self.b))          # administrar una empresa no afecta a otra

    def test_administrador_no_inicia_jornada_y_su_inicio_es_el_resumen(self):
        pmo = self._admin()
        r = self.ir(pmo, 'iniciar/', {})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Jornada.objects.exists())
        self.assertEqual(self.ir(pmo, '').status_code, 302)

    def test_superusuario_con_membresia_no_inicia_jornada(self):
        su = self._super()
        self.assertEqual(self.ir(su, 'iniciar/', {}).status_code, 403)
        self.assertEqual(self.ir(su, '').status_code, 302)
        self.assertFalse(Jornada.objects.exists())

    def test_no_ven_las_entradas_de_mi_trabajo_pero_el_empleado_si(self):
        self.assertContains(self.ir(self.emp, 'mis-reportes/'), 'Mis reportes')
        pmo = self._admin()
        self.client.force_login(pmo)
        r = self.client.get('/tekon/jornadas/equipo/')
        self.assertNotContains(r, 'Mis reportes')
        self.assertNotContains(r, 'Mi jornada')

    def test_el_resumen_no_cuenta_a_administradores_como_sin_iniciar(self):
        from .dashboard import _calcular
        self._admin()
        self._super()
        datos = _calcular(self.a)
        nombres = {p['nombre'] for p in datos['sin_iniciar']}
        self.assertEqual(nombres, {'Dir', 'Emp', 'Emp2'})          # ni el administrador (Pmo) ni el superusuario
        self.assertEqual(datos['total'], 3)


class AdministradorSinMembresiaTests(JornadasBase):
    """El administrador de sistema (Plataforma → Administradores) entra a Asistencia sin ser miembro: solo a las vistas
    que exigen capacidades de ámbito empresa (resumen, equipo…); no a las que piden ser miembro o fichar."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.adm = User.objects.create_user('adm@x.cl', 'x')
        cls.adm.empresas_administradas.add(cls.a)

    def get(self, ruta, user=None):
        self.client.force_login(user or self.adm)
        return self.client.get(f'/tekon/jornadas/{ruta}')

    def test_entra_al_resumen_y_al_equipo(self):
        self.assertEqual(self.get('resumen/').status_code, 200)
        self.assertEqual(self.get('equipo/').status_code, 200)

    def test_no_entra_a_lo_personal(self):
        for ruta in ('', 'ausencias/', 'mis-reportes/'):
            self.assertEqual(self.get(ruta).status_code, 403, ruta)

    def test_el_administrador_de_otra_empresa_no_entra(self):
        otro = User.objects.create_user('otro@x.cl', 'x')
        otro.empresas_administradas.add(self.b)
        self.assertEqual(self.get('resumen/', otro).status_code, 403)

    def test_quien_no_administra_ni_es_miembro_sigue_fuera(self):
        extra = User.objects.create_user('extra@x.cl', 'x')
        self.assertEqual(self.get('resumen/', extra).status_code, 403)
        self.assertEqual(self.get('equipo/', extra).status_code, 403)


