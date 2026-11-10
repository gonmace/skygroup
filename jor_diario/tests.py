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
from jor_empleados.models import DispositivoMarcacion, Perfil
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

    # ── Marcación verificada: passkey del celular + lecturas de GPS ──
    def dispositivo(self, perfil):
        return DispositivoMarcacion.objects.get_or_create(
            perfil=perfil, activo=True, defaults=dict(credential_id=f'cred-{perfil.pk}'.encode(), public_key=b'k'))[0]

    def lecturas(self, metros_norte=0, acc=10.0, n=3, edad_s=0):
        """n lecturas de GPS recientes, a `metros_norte` metros al norte de la sede."""
        lat = SEDE_LAT + metros_norte / 111_320
        ahora = int(time.time() * 1000) - edad_s * 1000
        return [{'lat': lat + i * 1e-6, 'lon': SEDE_LON, 'accuracy': acc, 'timestamp': ahora - (n - 1 - i) * 1200}
                for i in range(n)]

    def ini(self, p, proyecto=None, lecturas=None, **kw):
        return servicios.iniciar(p, self.dispositivo(p), lecturas if lecturas is not None else self.lecturas(),
                                 proyecto, **kw)

    def fin(self, jornada_id, p, realizado='', planificado='', lecturas=None, **kw):
        return servicios.finalizar(jornada_id, p, self.dispositivo(p),
                                   lecturas if lecturas is not None else self.lecturas(), realizado, planificado, **kw)

    def ir(self, user, ruta, datos=None, slug='tekon', lecturas=None):
        self.client.force_login(user)
        url = f'/{slug}/jornadas/{ruta}'
        if datos is None:
            return self.client.get(url)
        if ruta in ('iniciar/', 'finalizar/'):    # el passkey se prueba aparte (PasskeysTests): aquí se da por verificado
            datos = {**datos, 'credencial': '{}',
                     'lecturas': json.dumps(self.lecturas() if lecturas is None else lecturas)}
            with mock.patch('jor_diario.views.passkeys.verificar_aserto', return_value=self.dispositivo(self.perfil(user))):
                return self.client.post(url, datos)
        return self.client.post(url, datos)


class ServiciosTests(JornadasBase):
    def test_iniciar_y_finalizar_con_reporte(self):
        p = self.perfil(self.emp)
        j = self.ini(p, proyecto=self.proy)
        self.assertEqual((j.estado, j.proyecto), ('en_curso', self.proy))
        self.assertEqual(servicios.jornada_en_curso(p), j)
        j2 = self.fin(j.pk, p, ' Hice A ', 'Haré B')
        self.assertEqual((j2.estado, j2.cierre_auto), ('completada', False))
        self.assertIsNotNone(j2.duracion_min)
        r = ReporteDiario.objects.get()
        self.assertEqual((r.realizado, r.planificado), ('Hice A', 'Haré B'))

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
        self.fin(j.pk, p, 'a', 'b')

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
        self.ir(self.emp, 'finalizar/', {'jornada': j.pk, 'realizado': 'x', 'planificado': 'y'})
        j.refresh_from_db()
        self.assertEqual(j.estado, 'completada')
        self.assertContains(self.ir(self.emp, 'mis-reportes/'), 'x')

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
        self.ir(self.emp, 'finalizar/', {'jornada': j.pk, 'realizado': 'x', 'planificado': 'y'})
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
class VerificarPresenciaTests(JornadasBase):
    def v(self, lecturas, sede=None, **kw):
        from .verificacion import verificar_presencia
        return verificar_presencia(self.sede if sede is None else sede, lecturas, **kw)

    def test_dentro_de_la_geocerca_con_buena_precision_es_valida(self):
        r = self.v(self.lecturas(metros_norte=20))
        self.assertTrue(r['ok'], r)
        self.assertLess(r['distancia_m'], 30)

    def test_fuera_del_radio(self):
        r = self.v(self.lecturas(metros_norte=500))
        self.assertFalse(r['ok'])
        self.assertIn('fuera_geocerca', r['motivos'])

    def test_precision_insuficiente(self):
        self.assertIn('precision', self.v(self.lecturas(acc=120))['motivos'])

    def test_precision_irreal_es_sospechosa(self):
        self.assertIn('precision_sospechosa', self.v(self.lecturas(acc=0))['motivos'])

    def test_lecturas_viejas(self):
        self.assertIn('lectura_vieja', self.v(self.lecturas(edad_s=120))['motivos'])

    def test_pocas_lecturas(self):
        r = self.v(self.lecturas(n=1))
        self.assertFalse(r['ok'])
        self.assertIn('pocas_lecturas', r['motivos'])
        self.assertIn('pocas_lecturas', self.v([])['motivos'])
        self.assertIn('pocas_lecturas', self.v('basura')['motivos'])

    def test_lecturas_mal_formadas_se_descartan(self):
        malas = [{'lat': 'x', 'lon': 1, 'accuracy': 5, 'timestamp': 1}, {'lat': 999, 'lon': 1, 'accuracy': 5, 'timestamp': 1},
                 {'lat': 1, 'lon': 1, 'accuracy': -4, 'timestamp': 1}, None, 3, {'lat': float('nan'), 'lon': 1, 'accuracy': 5, 'timestamp': 1}]
        self.assertIn('pocas_lecturas', self.v(malas + self.lecturas(n=1))['motivos'])

    def test_salto_imposible_entre_lecturas(self):
        ls = self.lecturas()
        ls[1]['lat'] += 0.05          # ≈5,5 km en 1,2 s
        self.assertIn('salto_imposible', self.v(ls)['motivos'])

    def test_lecturas_identicas_solo_avisan(self):
        ls = self.lecturas()
        for l in ls:
            l['lat'], l['lon'] = ls[0]['lat'], ls[0]['lon']
        r = self.v(ls)
        self.assertTrue(r['ok'])
        self.assertEqual(r['avisos'], ['lecturas_identicas'])

    def test_sede_sin_ubicacion_solo_captura(self):
        libre = Sede.objects.create(empresa=self.a, nombre='Sin coords')
        for r in (self.v(self.lecturas(), sede=libre), self.v_sin_sede()):
            self.assertTrue(r['ok'])
            self.assertEqual(r['motivos'], [])
            self.assertIn('sin_geocerca', r['avisos'])
            self.assertIsNotNone(r['lat'])
            self.assertIsNone(r['distancia_m'])

    def v_sin_sede(self):
        from .verificacion import verificar_presencia
        return verificar_presencia(None, self.lecturas())



# ── Inicio de jornada: identidad (passkey) + presencia → verificada o excepción ────────────────
class MarcacionTests(JornadasBase):
    def test_en_la_sede_queda_verificada(self):
        j = self.ini(self.perfil(self.emp), lecturas=self.lecturas(metros_norte=10), ip='10.0.0.5')
        self.assertEqual(j.estado_verificacion, 'verificada')
        self.assertEqual((j.ip_inicio, j.dispositivo), ('10.0.0.5', self.dispositivo(self.perfil(self.emp))))
        self.assertAlmostEqual(float(j.lat_inicio), SEDE_LAT, places=3)
        self.assertEqual(j.verificacion['inicio']['motivos'], [])

    def test_sin_celular_vinculado_no_se_marca(self):
        with self.assertRaises(servicios.ErrorJornada) as e:
            servicios.iniciar(self.perfil(self.emp), None, self.lecturas())
        self.assertTrue(e.exception.extra.get('dispositivo_requerido'))

    def test_dispositivo_de_otra_persona_o_liberado_no_sirve(self):
        ajeno = self.dispositivo(self.perfil(self.emp2))
        with self.assertRaises(servicios.ErrorJornada):
            servicios.iniciar(self.perfil(self.emp), ajeno, self.lecturas())
        propio = self.dispositivo(self.perfil(self.emp))
        DispositivoMarcacion.objects.filter(pk=propio.pk).update(activo=False)
        propio.refresh_from_db()
        with self.assertRaises(servicios.ErrorJornada):
            servicios.iniciar(self.perfil(self.emp), propio, self.lecturas())

    def test_fuera_de_la_sede_pide_motivo_y_queda_pendiente(self):
        p, lejos = self.perfil(self.emp), self.lecturas(metros_norte=2000)
        with self.assertRaises(servicios.ErrorJornada) as e:
            self.ini(p, lecturas=lejos)
        self.assertTrue(e.exception.extra.get('motivo_requerido'))
        self.assertFalse(Jornada.objects.exists())
        j = self.ini(p, lecturas=lejos, motivo='Visita a terreno')
        self.assertEqual((j.estado_verificacion, j.motivo_excepcion), ('excepcion_pendiente', 'Visita a terreno'))
        self.assertIn('fuera_geocerca', j.verificacion['inicio']['motivos'])
        n = Notificacion.objects.filter(destinatario=self.pmo)
        self.assertEqual(n.count(), 1)
        self.assertIn('Visita a terreno', n.get().mensaje)
        self.assertFalse(Notificacion.objects.filter(destinatario=self.emp).exists())

    def test_sin_permiso_de_excepcion_se_rechaza(self):
        p = self.perfil(self.emp)
        Perfil.objects.filter(pk=p.pk).update(puede_excepcion=False)
        p.refresh_from_db()
        with self.assertRaisesMessage(servicios.ErrorJornada, 'No se pudo verificar tu presencia'):
            self.ini(p, lecturas=self.lecturas(metros_norte=2000), motivo='da igual')
        self.assertFalse(Jornada.objects.exists())

    def test_sin_sede_con_ubicacion_inicia_y_captura_la_posicion(self):
        m = self.emp.membresias.get(empresa=self.a)
        m.sede = None
        m.save()
        j = self.ini(self.perfil(self.emp))
        self.assertNotEqual(j.estado_verificacion, 'excepcion_pendiente')
        self.assertIsNotNone(j.lat_inicio)

    def test_precision_mala_va_a_revision(self):
        with self.assertRaises(servicios.ErrorJornada):
            self.ini(self.perfil(self.emp), lecturas=self.lecturas(acc=300))

    def test_finalizar_registra_la_ubicacion_sin_cambiar_la_verificacion_del_inicio(self):
        p = self.perfil(self.emp)
        j = self.ini(p)
        j = self.fin(j.pk, p, 'a', 'b', lecturas=self.lecturas(metros_norte=900), ip='10.0.0.9')
        self.assertEqual((j.estado, j.estado_verificacion, j.ip_fin), ('completada', 'verificada', '10.0.0.9'))
        self.assertIn('fuera_geocerca', j.verificacion['fin']['motivos'])
        self.assertIsNotNone(j.lat_fin)

    def test_finalizar_exige_ubicacion_legible_y_celular(self):
        p = self.perfil(self.emp)
        j = self.ini(p)
        with self.assertRaises(servicios.ErrorJornada) as e:
            self.fin(j.pk, p, 'a', 'b', lecturas=[])
        self.assertTrue(e.exception.extra.get('ubicacion_requerida'))
        with self.assertRaises(servicios.ErrorJornada):
            servicios.finalizar(j.pk, p, None, self.lecturas(), 'a', 'b')


class ExcepcionesTests(JornadasBase):
    def pendiente(self, user=None):
        return self.ini(self.perfil(user or self.emp), lecturas=self.lecturas(metros_norte=3000), motivo='Cliente')

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
        r = self.ir(self.pmo, f'excepciones/{j.pk}/decidir/', {'decision': 'aprobar'})
        self.assertEqual(r.status_code, 302)
        j.refresh_from_db()
        self.assertEqual(j.estado_verificacion, 'excepcion_aprobada')
        self.assertEqual(self.ir(self.pmo, f'excepciones/{j.pk}/decidir/', {'decision': 'otra'}).status_code, 403)
        self.assertEqual(self.ir(self.emp, f'excepciones/{j.pk}/decidir/', {'decision': 'rechazar'}).status_code, 403)

    def test_el_certificado_y_la_asistencia_no_cuentan_pendientes(self):
        from jor_reportes import servicios as rep
        j = self.pendiente()
        Jornada.objects.filter(pk=j.pk).update(estado='completada', fin=j.inicio + timedelta(hours=8), duracion_min=480)
        total = lambda: sum(r['min'] or 0 for r in rep.horas_por_proyecto(self.a)) if hasattr(rep, 'horas_por_proyecto') else None
        self.assertEqual(Jornada.objects.computables().count(), 0)
        servicios.decidir_excepcion(j.pk, self.a, self.pmo, True)
        self.assertEqual(Jornada.objects.computables().count(), 1)


class VistasMarcacionTests(JornadasBase):
    def test_json_de_error_pide_motivo_y_luego_crea_la_excepcion(self):
        lejos = self.lecturas(metros_norte=2000)
        r = self.ir(self.emp, 'iniciar/', {}, lecturas=lejos)
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.json()['motivo_requerido'])
        r = self.ir(self.emp, 'iniciar/', {'motivo': 'Obra'}, lecturas=lejos)
        self.assertEqual((r.status_code, r.json()['ok']), (200, True))
        self.assertEqual(Jornada.objects.get().estado_verificacion, 'excepcion_pendiente')

    def test_passkey_invalido_no_marca(self):
        from jor_empleados.passkeys import ErrorPasskey
        self.client.force_login(self.emp)
        with mock.patch('jor_diario.views.passkeys.verificar_aserto', side_effect=ErrorPasskey('caducó')):
            r = self.client.post('/tekon/jornadas/iniciar/', {'credencial': '{}', 'lecturas': '[]'})
        self.assertEqual((r.status_code, r.json()['error']), (400, 'caducó'))
        self.assertFalse(Jornada.objects.exists())

    def test_sin_credencial_ni_challenge_no_marca(self):
        self.client.force_login(self.emp)
        r = self.client.post('/tekon/jornadas/iniciar/', {'lecturas': json.dumps(self.lecturas())})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Jornada.objects.exists())

    def test_json_mal_formado(self):
        self.client.force_login(self.emp)
        r = self.client.post('/tekon/jornadas/iniciar/', {'credencial': '{', 'lecturas': 'x'})
        self.assertEqual(r.status_code, 400)

    def test_sin_dispositivo_ofrece_vincular(self):
        self.assertContains(self.ir(self.emp, ''), 'Vincular este celular')

    def test_liberar_celular(self):
        d = self.dispositivo(self.perfil(self.emp))
        m = self.emp.membresias.get(empresa=self.a)
        url = f'/tekon/jornadas/equipo/{m.pk}/dispositivo/liberar/'
        self.client.force_login(self.dir)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.pmo)
        self.assertEqual(self.client.post(url).status_code, 302)
        d.refresh_from_db()
        self.assertFalse(d.activo)
        self.assertEqual((d.liberado_por, bool(d.liberado_en)), (self.pmo, True))
        self.assertEqual(self.client.get(f'/tekon/jornadas/equipo/{m.pk}/').status_code, 200)


# ── Passkeys (challenge de un solo uso, caducidad, ataduras) ────────────────────────────────────
class PasskeysTests(JornadasBase):
    def request(self, user):
        from django.test import RequestFactory
        from django.contrib.sessions.backends.signed_cookies import SessionStore
        r = RequestFactory().get('/', HTTP_HOST='localhost')
        r.session = SessionStore()
        r.user = user
        return r

    def test_opciones_de_registro_guardan_challenge_y_exigen_celular_propio(self):
        from jor_empleados import passkeys
        r = self.request(self.emp)
        o = passkeys.opciones_registro(r, self.perfil(self.emp))
        self.assertEqual(o['rp']['id'], 'localhost')
        self.assertEqual(o['authenticatorSelection']['authenticatorAttachment'], 'platform')
        self.assertEqual(o['authenticatorSelection']['userVerification'], 'required')
        self.assertIn(passkeys.CLAVE_SESION, r.session)

    def test_no_se_vincula_un_segundo_celular(self):
        from jor_empleados import passkeys
        self.dispositivo(self.perfil(self.emp))
        with self.assertRaises(passkeys.ErrorPasskey):
            passkeys.opciones_registro(self.request(self.emp), self.perfil(self.emp))

    def test_autenticacion_sin_dispositivo(self):
        from jor_empleados import passkeys
        with self.assertRaises(passkeys.ErrorPasskey):
            passkeys.opciones_autenticacion(self.request(self.emp), self.perfil(self.emp))

    def test_el_challenge_es_de_un_solo_uso_y_caduca(self):
        from jor_empleados import passkeys
        r, p = self.request(self.emp), self.perfil(self.emp)
        self.dispositivo(p)
        passkeys.opciones_autenticacion(r, p)
        with self.assertRaises(passkeys.ErrorPasskey):                  # credencial inválida: el challenge igual se consume
            passkeys.verificar_aserto(r, p, {'id': 'x', 'rawId': 'eA'})
        self.assertNotIn(passkeys.CLAVE_SESION, r.session)
        with self.assertRaises(passkeys.ErrorPasskey):                  # sin challenge pendiente
            passkeys.verificar_aserto(r, p, {'id': 'x', 'rawId': 'eA'})
        passkeys.opciones_autenticacion(r, p)
        r.session[passkeys.CLAVE_SESION]['t'] -= passkeys.TTL_S + 1
        with self.assertRaisesMessage(passkeys.ErrorPasskey, 'caducó'):
            passkeys.verificar_aserto(r, p, {'id': 'x', 'rawId': 'eA'})

    def test_challenge_de_registro_no_sirve_para_marcar(self):
        from jor_empleados import passkeys
        r, p = self.request(self.emp), self.perfil(self.emp)
        passkeys.opciones_registro(r, p)
        self.dispositivo(p)
        with self.assertRaisesMessage(passkeys.ErrorPasskey, 'caducó'):
            passkeys.verificar_aserto(r, p, {'id': 'x', 'rawId': 'eA'})

    def test_credencial_de_otro_celular_o_cross_platform_se_rechaza(self):
        from jor_empleados import passkeys
        r, p = self.request(self.emp), self.perfil(self.emp)
        self.dispositivo(p)
        passkeys.opciones_autenticacion(r, p)
        with self.assertRaisesMessage(passkeys.ErrorPasskey, 'no es el vinculado'):
            passkeys.verificar_aserto(r, p, {'id': 'x', 'rawId': 'AAAA'})
        passkeys.opciones_autenticacion(r, p)
        with self.assertRaisesMessage(passkeys.ErrorPasskey, 'dispositivo externo'):
            passkeys.verificar_aserto(r, p, {'id': 'x', 'rawId': 'AAAA', 'authenticatorAttachment': 'cross-platform'})


class PasskeyFlujoCompletoTests(JornadasBase):
    """Registro y marcación con un autenticador por software (ES256, attestation «none»): valida de verdad la
    cadena challenge → firma → sign_count que usa un celular, sin navegador."""

    def setUp(self):
        super().setUp()
        from cryptography.hazmat.primitives.asymmetric import ec
        self.clave = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = b'credencial-de-prueba-0123456789'

    def request(self, user):
        from django.contrib.sessions.backends.signed_cookies import SessionStore
        from django.test import RequestFactory
        r = RequestFactory().get('/', HTTP_HOST='localhost')
        r.session, r.user = SessionStore(), user
        return r

    def _b64(self, b):
        from webauthn.helpers import bytes_to_base64url
        return bytes_to_base64url(b)

    def _client_data(self, tipo, challenge_b64):
        return json.dumps({'type': tipo, 'challenge': challenge_b64, 'origin': 'http://localhost'}).encode()

    def registro(self, opciones):
        import hashlib
        import struct
        import cbor2
        n = self.clave.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, 'big'), -3: n.y.to_bytes(32, 'big')})
        auth = (hashlib.sha256(b'localhost').digest() + bytes([0x45]) + struct.pack('>I', 0) + bytes(16)
                + struct.pack('>H', len(self.cred_id)) + self.cred_id + cose)
        return {'id': self._b64(self.cred_id), 'rawId': self._b64(self.cred_id), 'type': 'public-key',
                'authenticatorAttachment': 'platform', 'clientExtensionResults': {},
                'response': {'clientDataJSON': self._b64(self._client_data('webauthn.create', opciones['challenge'])),
                             'attestationObject': self._b64(cbor2.dumps({'fmt': 'none', 'attStmt': {}, 'authData': auth}))}}

    def aserto(self, opciones, contador, desafio=None):
        import hashlib
        import struct
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        cdj = self._client_data('webauthn.get', desafio or opciones['challenge'])
        auth = hashlib.sha256(b'localhost').digest() + bytes([0x05]) + struct.pack('>I', contador)
        firma = self.clave.sign(auth + hashlib.sha256(cdj).digest(), ec.ECDSA(hashes.SHA256()))
        return {'id': self._b64(self.cred_id), 'rawId': self._b64(self.cred_id), 'type': 'public-key',
                'authenticatorAttachment': 'platform', 'clientExtensionResults': {},
                'response': {'clientDataJSON': self._b64(cdj), 'authenticatorData': self._b64(auth),
                             'signature': self._b64(firma)}}

    def vincular(self, user=None):
        from jor_empleados import passkeys
        user = user or self.emp
        r, p = self.request(user), self.perfil(user)
        opciones = passkeys.opciones_registro(r, p)
        return passkeys.registrar(r, p, self.registro(opciones), 'Pixel')

    def test_vincular_y_marcar_de_punta_a_punta(self):
        from jor_empleados import passkeys
        d = self.vincular()
        self.assertEqual((d.nombre, d.activo, d.sign_count), ('Pixel', True, 0))
        r, p = self.request(self.emp), self.perfil(self.emp)
        opciones = passkeys.opciones_autenticacion(r, p)
        d2 = passkeys.verificar_aserto(r, p, self.aserto(opciones, 1))
        self.assertEqual((d2.pk, d2.sign_count), (d.pk, 1))
        self.assertIsNotNone(d2.ultimo_uso)
        j = servicios.iniciar(p, d2, self.lecturas())       # la jornada queda atada al celular
        self.assertEqual((j.dispositivo, j.estado_verificacion), (d2, 'verificada'))

    def test_replay_de_la_misma_firma_falla(self):
        from jor_empleados import passkeys
        self.vincular()
        r, p = self.request(self.emp), self.perfil(self.emp)
        opciones = passkeys.opciones_autenticacion(r, p)
        aserto = self.aserto(opciones, 1)
        passkeys.verificar_aserto(r, p, aserto)
        passkeys.opciones_autenticacion(r, p)                                  # nuevo challenge, firma vieja
        with self.assertRaises(passkeys.ErrorPasskey):
            passkeys.verificar_aserto(r, p, aserto)

    def test_contador_no_creciente_se_rechaza(self):
        from jor_empleados import passkeys
        self.vincular()
        r, p = self.request(self.emp), self.perfil(self.emp)
        passkeys.verificar_aserto(r, p, self.aserto(passkeys.opciones_autenticacion(r, p), 5))
        with self.assertRaises(passkeys.ErrorPasskey):                          # clon del celular: contador retrocede
            passkeys.verificar_aserto(r, p, self.aserto(passkeys.opciones_autenticacion(r, p), 3))

    def test_firma_de_otra_clave_se_rechaza(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from jor_empleados import passkeys
        self.vincular()
        r, p = self.request(self.emp), self.perfil(self.emp)
        opciones = passkeys.opciones_autenticacion(r, p)
        self.clave = ec.generate_private_key(ec.SECP256R1())                    # atacante con otra clave
        with self.assertRaises(passkeys.ErrorPasskey):
            passkeys.verificar_aserto(r, p, self.aserto(opciones, 1))

    def test_challenge_ajeno_o_adivinado_se_rechaza(self):
        from jor_empleados import passkeys
        self.vincular()
        r, p = self.request(self.emp), self.perfil(self.emp)
        opciones = passkeys.opciones_autenticacion(r, p)
        with self.assertRaises(passkeys.ErrorPasskey):
            passkeys.verificar_aserto(r, p, self.aserto(opciones, 1, desafio=self._b64(b'otro-challenge-cualquiera')))

    def test_la_credencial_de_una_persona_no_sirve_para_otra(self):
        from jor_empleados import passkeys
        self.vincular(self.emp)
        r, p = self.request(self.emp2), self.perfil(self.emp2)
        self.dispositivo(p)                                                     # emp2 tiene otro celular
        opciones = passkeys.opciones_autenticacion(r, p)
        with self.assertRaisesMessage(passkeys.ErrorPasskey, 'no es el vinculado'):
            passkeys.verificar_aserto(r, p, self.aserto(opciones, 1))

    def test_liberar_y_revincular_otro_celular(self):
        from jor_empleados import passkeys
        d = self.vincular()
        with self.assertRaises(passkeys.ErrorPasskey):                          # sin liberar no hay segundo celular
            passkeys.opciones_registro(self.request(self.emp), self.perfil(self.emp))
        self.assertEqual(passkeys.liberar(self.perfil(self.emp), self.pmo), 1)
        d.refresh_from_db()
        self.assertFalse(d.activo)
        with self.assertRaises(passkeys.ErrorPasskey):                          # el celular viejo ya no puede marcar
            passkeys.opciones_autenticacion(self.request(self.emp), self.perfil(self.emp))


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


class CierreExigePasskeyTests(JornadasBase):
    """El cierre siempre exige el passkey del celular vinculado: nada depende del User-Agent."""

    def test_sin_passkey_no_cierra_aunque_el_navegador_diga_que_es_un_computador(self):
        self.ini(self.perfil(self.emp))
        self.client.force_login(self.emp)
        datos = {'jornada': Jornada.objects.get().pk, 'realizado': 'Hice A', 'planificado': 'Haré B',
                 'lecturas': json.dumps(self.lecturas())}
        r = self.client.post('/tekon/jornadas/finalizar/', datos,
                             HTTP_USER_AGENT='Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0 Safari/537.36')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Jornada.objects.get().estado, 'en_curso')

    def test_con_passkey_verificado_cierra_y_captura_la_ubicacion(self):
        self.ini(self.perfil(self.emp))
        r = self.ir(self.emp, 'finalizar/', {'jornada': Jornada.objects.get().pk, 'realizado': 'Hice A', 'planificado': 'Haré B'})
        self.assertEqual(r.status_code, 200)
        j = Jornada.objects.get()
        self.assertEqual(j.estado, 'completada')
        self.assertIsNotNone(j.lat_fin)

    def test_sin_ubicacion_no_cierra(self):
        self.ini(self.perfil(self.emp))
        r = self.ir(self.emp, 'finalizar/', {'jornada': Jornada.objects.get().pk, 'realizado': 'A', 'planificado': 'B'}, lecturas=[])
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.json()['ubicacion_requerida'])
        self.assertEqual(Jornada.objects.get().estado, 'en_curso')


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
