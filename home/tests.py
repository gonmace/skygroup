from django.conf import settings
from django.test import TestCase, override_settings


@override_settings(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class HomeTests(TestCase):
    def test_index(self):
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_healthz(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_sitemap(self):
        self.assertEqual(self.client.get('/sitemap.xml').status_code, 200)

    def test_robots_no_expone_admin(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(settings.ADMIN_URL.strip('/') + '/', response.content.decode().replace('Sitemap', ''))


@override_settings(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class AxesAdminTests(TestCase):
    """Un usuario bloqueado por axes se puede desbloquear desde el admin."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.login_url = f'/{settings.ADMIN_URL}login/'
        self.superuser = get_user_model().objects.create_superuser('boss@example.com', 'pass-12345-xyz')

    def _fail(self, username='intruso'):
        return self.client.post(self.login_url, {'username': username, 'password': 'mal'})

    def test_bloqueo_y_desbloqueo_desde_admin(self):
        from axes.models import AccessAttempt
        for _ in range(settings.AXES_FAILURE_LIMIT):
            self._fail()
        r = self._fail()
        self.assertEqual(r.status_code, 429)  # bloqueado
        self.assertContains(r, 'Acceso bloqueado', status_code=429)
        self.assertTrue(AccessAttempt.objects.filter(username='intruso').exists())

        # El superusuario (otro IP) ve el intento en el admin y lo borra
        from django.test import Client
        admin_client = Client(REMOTE_ADDR='10.0.0.99')
        admin_client.force_login(self.superuser)
        changelist = admin_client.get('/%saxes/accessattempt/' % settings.ADMIN_URL)
        self.assertContains(changelist, 'intruso')
        attempt = AccessAttempt.objects.get(username='intruso')
        resp = admin_client.post(
            '/%saxes/accessattempt/' % settings.ADMIN_URL,
            {'action': 'delete_selected', '_selected_action': [attempt.pk], 'post': 'yes'},
        )
        self.assertEqual(resp.status_code, 302)

        # Ya no está bloqueado
        self.assertEqual(self._fail().status_code, 200)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class EmpresaInicioTests(TestCase):
    def test_la_portada_no_lista_usuarios(self):
        from cuentas.models import User
        from cuentas.roles import RolBase
        from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
        e = crear_empresa(nombre='Embol', slug='emb', modulos=['tar'])
        jefe = User.objects.create_user('jefe@x.cl', 'x', first_name='Jefa')
        agregar_miembro(jefe, e, rol_por_base(e, RolBase.COORDINADOR))
        ejec = User.objects.create_user('ejec@x.cl', 'x', first_name='Eje')
        agregar_miembro(ejec, e, rol_por_base(e, RolBase.MIEMBRO))
        self.client.force_login(jefe)
        r = self.client.get('/emb/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'ejec@x.cl')
        self.client.force_login(ejec)
        r = self.client.get('/emb/')
        self.assertNotContains(r, 'jefe@x.cl')

    def test_portada_con_la_informacion_de_la_empresa_y_plataforma_fuera(self):
        from cuentas.models import User
        from cuentas.roles import RolBase
        from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
        from empresas.models import Contratista
        e = crear_empresa(nombre='Embol', slug='emb', modulos=['tar'], razon_social='Embol SpA', rut='76.000.000-1')
        Contratista.objects.create(empresa=e, nombre='Redes SA', codigo='C1')
        jefe = User.objects.create_user('jefe@x.cl', 'x')
        agregar_miembro(jefe, e, rol_por_base(e, RolBase.COORDINADOR))
        self.client.force_login(jefe)
        r = self.client.get('/emb/')
        for texto in ('Embol SpA', 'Contratistas', 'Roles', 'Usuarios'):
            self.assertContains(r, texto)
        self.assertNotContains(r, 'Plataforma')
        self.assertIsNotNone(r.context['contratistas'])
        ejec = User.objects.create_user('ejec@x.cl', 'x')
        agregar_miembro(ejec, e, rol_por_base(e, RolBase.MIEMBRO))
        self.client.force_login(ejec)
        r = self.client.get('/emb/')
        self.assertContains(r, 'Embol SpA')                      # los datos de la empresa los ve cualquiera
        self.assertIsNone(r.context['contratistas'])
        self.assertIsNone(r.context['roles'])
        root = User.objects.create_superuser('root@x.cl', 'x')
        self.client.force_login(root)
        html = self.client.get('/emb/').content.decode()
        self.assertIn('/emb/panel/', html)                       # enlace en el menú de usuario
        self.assertNotIn('Almacenamiento', html)                 # pero la plataforma no está en la empresa

