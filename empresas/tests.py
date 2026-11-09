from django.test import TestCase, override_settings

from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base

AJUSTES = dict(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


@override_settings(**AJUSTES)
class TenancyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(
            nombre='Tekon', slug='tekon', termino_proyecto_singular='Sitio',
            termino_proyecto_plural='Sitios', color_primario='#e60000',
        )
        cls.b = crear_empresa(nombre='Embol', slug='embol')
        cls.inactiva = crear_empresa(nombre='Vieja', slug='vieja', activa=False)
        cls.user_a = User.objects.create_user('a@example.com', 'x')
        agregar_miembro(cls.user_a, cls.a, rol_por_base(cls.a, RolBase.MIEMBRO))
        cls.user_multi = User.objects.create_user('m@example.com', 'x')
        agregar_miembro(cls.user_multi, cls.a, rol_por_base(cls.a, RolBase.MIEMBRO))
        agregar_miembro(cls.user_multi, cls.b, rol_por_base(cls.b, RolBase.COORDINADOR))
        cls.root = User.objects.create_superuser('root@example.com', 'x')

    def test_anonimo_en_empresa_activa_va_al_login_de_la_empresa(self):
        r = self.client.get('/tekon/')
        self.assertRedirects(r, '/tekon/acceso/login/?next=/tekon/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/tekon/acceso/login/').status_code, 200)

    def test_empresa_inexistente_cae_al_urlconf(self):
        self.assertEqual(self.client.get('/noexiste/').status_code, 404)

    def test_empresa_inactiva(self):
        self.assertEqual(self.client.get('/vieja/').status_code, 404)
        self.client.force_login(self.user_a)
        self.assertEqual(self.client.get('/vieja/').status_code, 403)

    def test_miembro_no_entra_a_otra_empresa(self):
        self.client.force_login(self.user_a)
        self.assertEqual(self.client.get('/tekon/').status_code, 200)
        self.assertEqual(self.client.get('/embol/').status_code, 403)

    def test_multiempresa_entra_a_ambas(self):
        self.client.force_login(self.user_multi)
        self.assertEqual(self.client.get('/tekon/').status_code, 200)
        self.assertEqual(self.client.get('/embol/').status_code, 200)

    def test_sin_prefijo_redirige_a_su_empresa(self):
        self.client.force_login(self.user_a)
        r = self.client.get('/')
        self.assertRedirects(r, '/tekon/', fetch_redirect_response=False)

    def test_superusuario_entra_a_cualquiera_e_inicio_va_a_la_primera_empresa(self):
        self.client.force_login(self.root)
        self.assertEqual(self.client.get('/embol/').status_code, 200)
        self.assertEqual(self.client.get('/vieja/').status_code, 200)
        self.assertRedirects(self.client.get('/'), '/embol/', fetch_redirect_response=False)

    def test_usuario_sin_empresa_denegado(self):
        huerfano = User.objects.create_user('h@example.com', 'x')
        self.client.force_login(huerfano)
        self.assertEqual(self.client.get('/').status_code, 403)

    def test_slugs_reservados_rechazados(self):
        from django.core.exceptions import ValidationError
        for slug in ('panel', 'api', 'acceso', 'static', 'admin'):
            with self.assertRaises(ValidationError, msg=slug):
                crear_empresa(nombre='X', slug=slug)

    def test_context_processor_termino_proyecto(self):
        r = self.client.get('/tekon/acceso/login/')
        self.assertEqual(r.context['termino_proyectos'], 'Sitios')
        r = self.client.get('/embol/acceso/login/')
        self.assertEqual(r.context['termino_proyectos'], 'Proyectos')

    def test_tema_css_por_empresa(self):
        r = self.client.get('/tekon/marca/tema.css')
        self.assertEqual(r.status_code, 200)
        self.assertIn('--color-primary:#e60000', r.content.decode())
        self.assertEqual(self.client.get('/embol/marca/tema.css').content.decode().count('--color-primary:'), 0)


class PaletaTests(TestCase):
    """`empresas.paleta`: cualquier primario produce texto de marca legible en ambos temas."""
    PRIMARIOS = ['#007aff', '#e4002b', '#ffd400', '#0a3d62', '#00b894', '#7a7a7a', '#000000', '#ffffff', '#ff00ff']

    def _peor_contraste(self, tema, color):
        from empresas.paleta import SUPERFICIES, _fondos, contraste
        return min(contraste(color, f) for f in _fondos(color, tema))

    def test_texto_de_marca_cumple_aa_en_ambos_temas(self):
        from empresas.paleta import generar_tema
        for primario in self.PRIMARIOS:
            t = generar_tema(primario)
            for tema in ('light', 'dark'):
                with self.subTest(primario=primario, tema=tema):
                    self.assertGreaterEqual(self._peor_contraste(tema, t[tema]['--p-text']), 4.5)
                    self.assertGreaterEqual(self._peor_contraste(tema, t[tema]['--a-text']), 4.5)

    def test_el_relleno_de_marca_se_respeta_en_claro(self):
        from empresas.paleta import generar_tema
        for primario in self.PRIMARIOS:
            self.assertEqual(generar_tema(primario)['light']['--color-primary'], primario)

    def test_oscuro_se_deriva_solo_si_hace_falta(self):
        from empresas.paleta import SUPERFICIES, contraste, generar_tema
        self.assertEqual(generar_tema('#ffd400')['dark']['--color-primary'], '#ffd400')   # ya contrasta
        marino = generar_tema('#0a3d62')['dark']['--color-primary']                       # no contrasta: se aclara
        self.assertNotEqual(marino, '#0a3d62')
        self.assertGreaterEqual(contraste(marino, SUPERFICIES['dark'][0]), 3.0)

    def test_primario_oscuro_explicito_gana(self):
        from empresas.paleta import generar_tema
        self.assertEqual(generar_tema('#0a3d62', '#5599ff')['dark']['--color-primary'], '#5599ff')

    def test_acento_derivado_y_explicito(self):
        from empresas.paleta import generar_tema
        self.assertIn('--color-accent', generar_tema('#e4002b')['light'])
        self.assertEqual(generar_tema('#e4002b', acento='#123456')['light']['--color-accent'], '#123456')

    def test_semanticos_se_apartan_de_la_marca(self):
        from empresas.paleta import generar_tema
        self.assertIn('--color-error', generar_tema('#e4002b')['light'])      # rojo de marca ≈ error
        self.assertNotIn('--color-error', generar_tema('#0a3d62')['light'])   # azul: no choca
        self.assertNotIn('--color-warning', generar_tema('#7a7a7a')['dark'])  # un gris no tiene matiz

    def test_sin_colores_no_emite_nada(self):
        from empresas.paleta import a_css, generar_tema
        self.assertEqual(a_css(generar_tema()), '')
