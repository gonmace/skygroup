"""Logo del proveedor del servicio (p. ej. Redline): opcional, arriba a la derecha de los PDF, solo lo define el superusuario."""
import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.test import override_settings
from PIL import Image

from reg_construccion.models import RegConstruccion
from reg_construccion.pdf import reporte as pdf_construccion
from reg_construccion_base.models import RegConstruccionBase
from reg_construccion_base.pdf import reporte as pdf_base
from reg_fotos.tests import STORAGES_TEST
from reg_txtss.models import RegTxtss
from reg_txtss.pdf import reporte as pdf_txtss

from .tests import BaseRegistros


def _png_con_alfa():
    b = BytesIO()
    Image.new('RGBA', (320, 100), (255, 0, 0, 0)).save(b, 'PNG')
    return b.getvalue()


class ProveedorEnLosPdfTests(BaseRegistros):
    def setUp(self):
        super().setUp()
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ctx = override_settings(MEDIA_ROOT=str(tmp), STORAGES=STORAGES_TEST)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.registros = {
            'txtss': (RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1),
                      pdf_txtss, 'reg_txtss/pdf/txtss.html'),
            'construccion': (RegConstruccion.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1),
                             pdf_construccion, 'reg_construccion/pdf/reporte.html'),
            'construccion-base': (RegConstruccionBase.objects.create(empresa=self.a, proyecto=self.t2, user=self.ito1),
                                  pdf_base, 'reg_construccion_base/pdf/reporte.html'),
        }

    def poner_proveedor(self, nombre='Redline'):
        self.a.nombre_proveedor = nombre
        self.a.logo_proveedor.save('proveedor.png', ContentFile(_png_con_alfa()), save=True)

    def test_sin_proveedor_la_celda_queda_vacia(self):
        for clave, (registro, modulo, plantilla) in self.registros.items():
            with self.subTest(clave):
                ctx = modulo.contexto(registro, {})
                self.assertIsNone(ctx['logo_proveedor'])
                self.assertIn('<td class="header-logo right"></td>', render_to_string(plantilla, ctx))

    def test_con_proveedor_aparece_a_la_derecha_en_los_tres_pdf(self):
        self.poner_proveedor()
        for clave, (registro, modulo, plantilla) in self.registros.items():
            with self.subTest(clave):
                ctx = modulo.contexto(registro, {})
                self.assertTrue(ctx['logo_proveedor'].startswith('data:image/png;base64,'))   # conserva la transparencia
                self.assertEqual(ctx['proveedor'], 'Redline')
                html = render_to_string(plantilla, ctx)
                celda = html.split('<td class="header-logo right">')[1].split('</td>')[0]
                self.assertIn('alt="Redline"', celda)
                self.assertTrue(modulo.generar(registro).startswith(b'%PDF'))

    def test_el_logo_de_la_empresa_conserva_la_transparencia(self):
        """El logo del cliente no debe pasar por JPEG (el fondo transparente salía negro), tampoco en TX/TSS."""
        self.a.logo_claro.save('logo.png', ContentFile(_png_con_alfa()), save=True)
        for clave, (registro, modulo, plantilla) in self.registros.items():
            with self.subTest(clave):
                self.assertTrue(modulo.contexto(registro, {})['logo_empresa'].startswith('data:image/png;base64,'))
