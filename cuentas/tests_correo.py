"""Servidor SMTP configurable desde Plataforma → Correo: backend, pruebas y pantalla. Nada sale a la red: el SMTP es simulado."""
import smtplib
import socket
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.test import TestCase, override_settings

from . import correo_backend as cb
from .models import CorreoConfig, User
from .roles import RolBase
from .services import agregar_miembro, crear_empresa, rol_por_base

CACHE_LOCAL = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
AJUSTES = dict(CACHES=CACHE_LOCAL, SECURE_SSL_REDIRECT=False, DEFAULT_FROM_EMAIL='noreply@servidor.test',
               STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                         'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
DATOS = dict(host='smtp.prueba.test', puerto=587, seguridad='starttls', usuario='robot@prueba.test',
             password='secreto-de-prueba', remitente='no-reply@prueba.test', remitente_nombre='SkyGroup')


class SMTPFalso:
    """Reemplaza al backend SMTP de Django: guarda lo enviado."""
    enviados = []
    falla_al_abrir = None

    def __init__(self, **kw):
        self.kw = kw

    def open(self):
        if SMTPFalso.falla_al_abrir:
            raise SMTPFalso.falla_al_abrir
        return True

    def close(self):
        pass

    def send_messages(self, mensajes):
        SMTPFalso.enviados.extend(mensajes)
        return len(mensajes)


def falso():
    return mock.patch('django.core.mail.backends.smtp.EmailBackend', SMTPFalso)


@override_settings(**AJUSTES)
class BackendTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        SMTPFalso.enviados, SMTPFalso.falla_al_abrir = [], None

    def activar(self, **extra):
        return CorreoConfig.objects.create(activo=True, **{**DATOS, **extra})

    def enviar(self, remitente=None):
        m = EmailMessage('Asunto', 'Cuerpo', remitente or 'noreply@servidor.test', ['a@b.test'])
        with falso():
            return cb.EmailBackend().send_messages([m]), m

    def test_sin_configuracion_usa_el_backend_base_del_servidor(self):
        with override_settings(EMAIL_BACKEND_BASE='django.core.mail.backends.locmem.EmailBackend'):
            n, _ = self.enviar()
        self.assertEqual((n, len(mail.outbox), len(SMTPFalso.enviados)), (1, 1, 0))

    def test_configuracion_apagada_o_incompleta_no_se_usa(self):
        CorreoConfig.objects.create(activo=False, **DATOS)
        self.assertIsNone(cb.config_activa())
        CorreoConfig.objects.all().delete()
        CorreoConfig.objects.create(activo=True, host='x.test', remitente='')       # sin remitente: incompleta
        self.assertIsNone(cb.config_activa())

    def test_con_configuracion_activa_envia_por_ese_smtp_con_su_remitente(self):
        self.activar()
        n, m = self.enviar()
        self.assertEqual((n, len(SMTPFalso.enviados)), (1, 1))
        self.assertEqual(SMTPFalso.enviados[0].from_email, 'SkyGroup <no-reply@prueba.test>')   # el remitente por defecto se reemplaza

    def test_un_remitente_propio_de_la_empresa_se_respeta(self):
        self.activar()
        self.enviar(remitente='Empresa <info@cliente.test>')
        self.assertEqual(SMTPFalso.enviados[0].from_email, 'Empresa <info@cliente.test>')

    def test_parametros_del_smtp(self):
        self.activar(seguridad='ssl', puerto=465)
        with mock.patch('django.core.mail.backends.smtp.EmailBackend') as SMTP:
            SMTP.return_value.send_messages.return_value = 1
            cb.EmailBackend().send_messages([EmailMessage('a', 'b', 'noreply@servidor.test', ['a@b.test'])])
        kw = SMTP.call_args.kwargs
        self.assertEqual((kw['host'], kw['port'], kw['use_ssl'], kw['use_tls'], kw['username']),
                         ('smtp.prueba.test', 465, True, False, 'robot@prueba.test'))

    def test_guardar_invalida_la_cache(self):
        self.assertIsNone(cb.config_activa())             # cachea «sin configuración»
        self.activar()
        self.assertEqual(cb.config_activa()['host'], 'smtp.prueba.test')
        CorreoConfig.objects.update(activo=False)         # update() no pasa por save(): el cambio por save() sí
        c = CorreoConfig.objects.get()
        c.activo = False
        c.save()
        self.assertIsNone(cb.config_activa())

    def test_remitente_por_defecto(self):
        self.assertEqual(cb.remitente_por_defecto(), 'noreply@servidor.test')
        self.activar()
        self.assertEqual(cb.remitente_por_defecto(), 'SkyGroup <no-reply@prueba.test>')

    def test_los_correos_de_la_plataforma_usan_el_remitente_configurado(self):
        from cuentas.correos import _remitente
        self.assertEqual(_remitente(None), 'noreply@servidor.test')
        self.activar()
        self.assertEqual(_remitente(None), 'SkyGroup <no-reply@prueba.test>')

    def test_un_nombre_con_caracteres_raros_no_rompe_el_encabezado(self):
        self.activar(remitente_nombre='Sky<Group>\nBcc: x@y.z')
        self.assertNotIn('\n', cb.remitente_por_defecto())
        self.assertNotIn('<Group>', cb.remitente_por_defecto())


@override_settings(**AJUSTES)
class PruebasTests(TestCase):
    def setUp(self):
        SMTPFalso.enviados, SMTPFalso.falla_al_abrir = [], None

    def test_conexion_correcta(self):
        with falso():
            ok, msg = cb.probar_conexion(DATOS)
        self.assertTrue(ok)
        self.assertIn('Conexión correcta', msg)

    def test_errores_explicados(self):
        casos = [(smtplib.SMTPAuthenticationError(535, b'bad'), 'usuario o la contraseña'),
                 (socket.timeout(), 'a tiempo'), (ConnectionRefusedError(), 'No se pudo conectar'),
                 (socket.gaierror(), 'No se pudo conectar'), (smtplib.SMTPException('boom'), 'boom')]
        for error, texto in casos:
            SMTPFalso.falla_al_abrir = error
            with falso():
                ok, msg = cb.probar_conexion(DATOS)
            self.assertFalse(ok)
            self.assertIn(texto, msg, repr(error))

    def test_sin_servidor_no_conecta(self):
        self.assertEqual(cb.probar_conexion({**DATOS, 'host': ''}), (False, 'Falta el servidor SMTP.'))

    def test_correo_de_prueba(self):
        with mock.patch('cuentas.correo_backend._backend_smtp') as smtp:
            smtp.return_value.send_messages.return_value = 1
            ok, msg = cb.enviar_prueba(DATOS, 'destino@prueba.test')
        self.assertTrue(ok)
        self.assertIn('destino@prueba.test', msg)

    def test_correo_de_prueba_que_falla(self):
        with mock.patch('cuentas.correo_backend._backend_smtp') as smtp:
            smtp.return_value.send_messages.side_effect = smtplib.SMTPSenderRefused(550, b'no', 'x@y.z')
            ok, msg = cb.enviar_prueba(DATOS, 'destino@prueba.test')
        self.assertFalse(ok)
        self.assertIn('remitente', msg)


@override_settings(**AJUSTES)
class PantallaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.emp = crear_empresa(nombre='Tekon', slug='tekon')
        cls.su = User.objects.create_superuser('su@example.com', 'x')
        cls.coord = User.objects.create_user('coord@example.com', 'x')
        agregar_miembro(cls.coord, cls.emp, rol_por_base(cls.emp, RolBase.COORDINADOR))

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        SMTPFalso.enviados, SMTPFalso.falla_al_abrir = [], None

    def test_solo_el_superusuario(self):
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get('/panel/correo/').status_code, 403)
        self.assertEqual(self.client.post('/panel/correo/probar/', DATOS).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get('/panel/correo/').status_code, 302)

    def test_guarda_la_configuracion_y_la_contrasena_no_se_muestra(self):
        self.client.force_login(self.su)
        r = self.client.post('/panel/correo/', {**DATOS, 'activo': 'on'})
        self.assertRedirects(r, '/panel/correo/', fetch_redirect_response=False)
        c = CorreoConfig.objects.get()
        self.assertEqual((c.activo, c.host, c.puerto, c.password), (True, 'smtp.prueba.test', 587, 'secreto-de-prueba'))
        pagina = self.client.get('/panel/correo/').content.decode()
        self.assertNotIn('secreto-de-prueba', pagina)
        self.assertIn('smtp.prueba.test', pagina)

    def test_contrasena_vacia_conserva_la_guardada(self):
        CorreoConfig.objects.create(activo=True, **DATOS)
        self.client.force_login(self.su)
        self.client.post('/panel/correo/', {**DATOS, 'password': '', 'activo': 'on', 'host': 'otro.prueba.test'})
        c = CorreoConfig.objects.get()
        self.assertEqual((c.host, c.password), ('otro.prueba.test', 'secreto-de-prueba'))

    def test_activar_exige_servidor_y_remitente(self):
        self.client.force_login(self.su)
        r = self.client.post('/panel/correo/', {**DATOS, 'activo': 'on', 'host': '', 'remitente': ''})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(CorreoConfig.objects.exists())
        r = self.client.post('/panel/correo/', {**DATOS, 'puerto': '70000'})
        self.assertContains(r, 'entre 1 y 65535')

    def test_probar_conexion_con_lo_del_formulario_sin_guardar(self):
        self.client.force_login(self.su)
        with falso():
            r = self.client.post('/panel/correo/probar/', {**DATOS, 'accion': 'conexion'})
        self.assertEqual(r.json()['ok'], True)
        self.assertFalse(CorreoConfig.objects.exists())       # no guardó nada

    def test_probar_usa_la_contrasena_guardada_si_el_formulario_la_trae_vacia(self):
        CorreoConfig.objects.create(activo=False, **DATOS)
        self.client.force_login(self.su)
        with mock.patch('cuentas.correo_backend._backend_smtp') as smtp:
            smtp.return_value.open.return_value = True
            self.client.post('/panel/correo/probar/', {**DATOS, 'password': '', 'accion': 'conexion'})
        self.assertEqual(smtp.call_args.args[0]['password'], 'secreto-de-prueba')

    def test_error_de_conexion_se_explica(self):
        self.client.force_login(self.su)
        SMTPFalso.falla_al_abrir = smtplib.SMTPAuthenticationError(535, b'bad')
        with falso():
            d = self.client.post('/panel/correo/probar/', {**DATOS, 'accion': 'conexion'}).json()
        self.assertFalse(d['ok'])
        self.assertIn('contraseña', d['mensaje'])

    def test_enviar_correo_de_prueba_valida_el_destino(self):
        self.client.force_login(self.su)
        d = self.client.post('/panel/correo/probar/', {**DATOS, 'accion': 'envio', 'destino': 'no-es-correo'}).json()
        self.assertFalse(d['ok'])
        with falso():
            d = self.client.post('/panel/correo/probar/', {**DATOS, 'accion': 'envio', 'destino': 'a@prueba.test'}).json()
        self.assertTrue(d['ok'])
        self.assertEqual(SMTPFalso.enviados[0].to, ['a@prueba.test'])
        self.assertEqual(SMTPFalso.enviados[0].from_email, 'SkyGroup <no-reply@prueba.test>')

    def test_parametros_invalidos(self):
        self.client.force_login(self.su)
        self.assertFalse(self.client.post('/panel/correo/probar/', {**DATOS, 'host': ''}).json()['ok'])
        self.assertFalse(self.client.post('/panel/correo/probar/', {**DATOS, 'puerto': 'abc'}).json()['ok'])

    def test_el_respaldo_solo_se_menciona_si_el_servidor_define_un_smtp(self):
        self.client.force_login(self.su)
        with override_settings(EMAIL_BACKEND_BASE='django.core.mail.backends.console.EmailBackend'):
            self.assertNotContains(self.client.get('/panel/correo/'), 'localhost')
            self.assertContains(self.client.get('/panel/correo/'), 'sin servidor')
        with override_settings(EMAIL_BACKEND_BASE='django.core.mail.backends.smtp.EmailBackend', EMAIL_HOST='smtp.del-env.test'):
            self.assertContains(self.client.get('/panel/correo/'), 'smtp.del-env.test')

    def test_aparece_en_el_menu_de_plataforma(self):
        self.client.force_login(self.su)
        self.assertContains(self.client.get('/panel/'), 'href="/panel/correo/"')
