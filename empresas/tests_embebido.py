"""Iframe solo desde el Nextcloud de la empresa (External sites) y desde FRAME_ANCESTORS; nunca desde otros sitios."""
from django.core.cache import cache
from django.test import TestCase, override_settings

from cuentas.models import NextcloudConfig
from cuentas.services import crear_empresa

from .embebido import origen

AJUSTES = dict(SECURE_SSL_REDIRECT=False, FRAME_ANCESTORS=[],
               CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
               STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                         'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})


@override_settings(**AJUSTES)
class EmbebidoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='A', slug='emp-a')
        cls.b = crear_empresa(nombre='B', slug='emp-b')

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def cabeceras(self, ruta='/emp-a/acceso/login/'):
        r = self.client.get(ruta)
        self.assertEqual(r.status_code, 200, ruta)
        return r.headers.get('X-Frame-Options'), r.headers.get('Content-Security-Policy', '')

    def test_por_defecto_nadie_puede_embeber(self):
        xfo, csp = self.cabeceras()
        self.assertEqual(xfo, 'DENY')
        self.assertNotIn('frame-ancestors', csp)

    def test_el_nextcloud_de_la_empresa_puede_embeberla(self):
        NextcloudConfig.objects.create(empresa=self.a, servidor_url='https://sky.redlinegs.com/')
        xfo, csp = self.cabeceras()
        self.assertIsNone(xfo)                                   # X-Frame-Options no admite listas: se omite
        self.assertIn("frame-ancestors 'self' https://sky.redlinegs.com", csp)
        self.assertIn("default-src 'self'", csp)                 # el resto del CSP sigue igual

    def test_no_se_mezclan_empresas(self):
        NextcloudConfig.objects.create(empresa=self.a, servidor_url='https://sky.redlinegs.com')
        xfo, csp = self.cabeceras('/emp-b/acceso/login/')
        self.assertEqual(xfo, 'DENY')
        self.assertNotIn('frame-ancestors', csp)

    def test_cambiar_la_url_se_aplica_sin_esperar_la_cache(self):
        c = NextcloudConfig.objects.create(empresa=self.a, servidor_url='https://uno.example.com')
        self.assertIn('https://uno.example.com', self.cabeceras()[1])
        c.servidor_url = 'https://dos.example.com'
        c.save()
        csp = self.cabeceras()[1]
        self.assertIn('https://dos.example.com', csp)
        self.assertNotIn('https://uno.example.com', csp)

    def test_variable_frame_ancestors(self):
        with override_settings(FRAME_ANCESTORS=['https://portal.example.com', 'no-es-url', 'https://otro.example.com:8443']):
            xfo, csp = self.cabeceras()
            self.assertIsNone(xfo)
            self.assertIn("frame-ancestors 'self' https://portal.example.com https://otro.example.com:8443", csp)
            self.assertNotIn('no-es-url', csp)
            # también rutas sin empresa (la raíz) las usan
            self.assertIsNone(self.client.get('/acceso/login/').headers.get('X-Frame-Options'))

    def test_las_dos_fuentes_se_suman(self):
        NextcloudConfig.objects.create(empresa=self.a, servidor_url='https://sky.redlinegs.com')
        with override_settings(FRAME_ANCESTORS=['https://portal.example.com']):
            csp = self.cabeceras()[1]
        self.assertIn("'self' https://portal.example.com https://sky.redlinegs.com", csp)

    def test_una_url_invalida_no_autoriza_nada(self):
        NextcloudConfig.objects.create(empresa=self.a, servidor_url='javascript:alert(1)')
        xfo, csp = self.cabeceras()
        self.assertEqual(xfo, 'DENY')
        self.assertNotIn('frame-ancestors', csp)

    def test_origen(self):
        self.assertEqual(origen('https://sky.redlinegs.com/apps/x?y=1'), 'https://sky.redlinegs.com')
        self.assertEqual(origen('http://localhost:8080/'), 'http://localhost:8080')
        self.assertEqual(origen('https://usuario:clave@host.example.com/'), 'https://host.example.com')
        self.assertEqual(origen('HTTPS://Sky.RedlineGS.com./x'), 'https://sky.redlinegs.com')
        for malo in ('', 'sky.redlinegs.com', 'ftp://x.test', 'javascript:alert(1)', 'https://*.redlinegs.com',
                     'https://a.com; script-src *', 'https://a.com script-src', "https://a.com' 'unsafe-inline",
                     'https://a.com:abc', 'https://a.com:99999', 'https://-malo.com', 'https://[::1]/'):
            self.assertEqual(origen(malo), '', malo)

    def test_una_url_con_inyeccion_no_llega_a_la_cabecera(self):
        NextcloudConfig.objects.create(empresa=self.a, servidor_url='https://a.example.com; script-src *')
        xfo, csp = self.cabeceras()
        self.assertEqual(xfo, 'DENY')
        self.assertNotIn('script-src *', csp)
        self.assertNotIn('frame-ancestors', csp)
        with override_settings(FRAME_ANCESTORS=['https://b.example.com;default-src *', 'https://ok.example.com']):
            csp = self.cabeceras()[1]
        self.assertIn("frame-ancestors 'self' https://ok.example.com", csp)
        self.assertNotIn('default-src *', csp)
