"""La API key de n8n es un JWT de ~265 caracteres: el formulario y el modelo deben admitirla completa."""
from django.test import TestCase

from cuentas.models import CredencialesEmpresa
from cuentas.services import crear_empresa
from panel.forms import CredencialesForm

# Una clave con la forma de las de n8n: tres partes en base64url separadas por puntos, de más de 255 caracteres.
CLAVE = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' + 'a' * 208 + '.' + 'b' * 43


class ClaveN8nLargaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = crear_empresa(nombre='Larga SA', slug='larga-sa')

    def test_la_clave_mide_mas_de_255(self):
        self.assertGreater(len(CLAVE), 255)

    def test_el_formulario_no_la_recorta_en_el_navegador(self):
        campo = CredencialesForm(instance=CredencialesEmpresa(empresa=self.empresa)).fields['n8n_api_key']
        self.assertGreaterEqual(campo.max_length, len(CLAVE))
        html = str(CredencialesForm(instance=CredencialesEmpresa(empresa=self.empresa))['n8n_api_key'])
        self.assertIn('maxlength="1024"', html)                                                # el input ya no corta a 255

    def test_se_guarda_completa_y_se_lee_completa(self):
        form = CredencialesForm({'n8n_api_url': 'http://127.0.0.1:8001', 'n8n_api_key': CLAVE}, instance=CredencialesEmpresa(empresa=self.empresa))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        guardada = CredencialesEmpresa.objects.get()
        self.assertEqual(len(guardada.n8n_api_key), len(CLAVE))
        self.assertEqual(guardada.n8n_api_key[-4:], CLAVE[-4:])                                # termina donde termina la original
        self.assertEqual(CredencialesEmpresa.n8n_api(self.empresa), ('http://127.0.0.1:8001', CLAVE))

    def test_una_clave_con_espacios_se_rechaza_y_vacia_conserva_la_guardada(self):
        c = CredencialesEmpresa.objects.create(empresa=self.empresa, n8n_api_url='http://x', n8n_api_key=CLAVE)
        malo = CredencialesForm({'n8n_api_url': 'http://x', 'n8n_api_key': 'abc def'}, instance=c)
        self.assertFalse(malo.is_valid())
        vacio = CredencialesForm({'n8n_api_url': 'http://x', 'n8n_api_key': ''}, instance=c)
        self.assertTrue(vacio.is_valid())
        vacio.save()
        c.refresh_from_db()
        self.assertEqual(c.n8n_api_key, CLAVE)
