import io
from datetime import date, datetime, time

import openpyxl
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.utils import timezone

from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from jor_diario.models import Ausencia, Jornada, NotaCalendario
from jor_empleados.models import ConfigJornadas, Perfil

from . import certificado

AJUSTES = dict(
    SECURE_SSL_REDIRECT=False,
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'privado': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


def plantilla_minima():
    wb = openpyxl.Workbook()
    wb.active.title = 'PL'
    for i in range(1, certificado.T_PERSONAS + 1):
        wb.create_sheet(str(i))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@override_settings(**AJUSTES)
class CertificadoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.e = crear_empresa(nombre='Tekon', slug='tekon', modulos=['jor'])
        cls.pmo = User.objects.create_user('pmo@x.cl', 'x')
        m_pmo = agregar_miembro(cls.pmo, cls.e, rol_por_base(cls.e, RolBase.COORDINADOR))
        # La cabeza de la empresa es Coordinador pero no va en la planilla de pago: su perfil se desactiva.
        Perfil.objects.filter(pk=Perfil.de(m_pmo).pk).update(activo=False)
        cls.ana = User.objects.create_user('ana@x.cl', 'x', first_name='Ana')
        cls.m_ana = agregar_miembro(cls.ana, cls.e, rol_por_base(cls.e, RolBase.MIEMBRO))
        cls.p_ana = Perfil.de(cls.m_ana)
        Perfil.objects.filter(pk=cls.p_ana.pk).update(haber_basico=3000, ciudad_catering='LPZ', cargo='Ingeniera')
        cls.p_ana.refresh_from_db()
        ini = timezone.make_aware(datetime(2026, 10, 5, 8, 10))
        Jornada.objects.create(empresa=cls.e, perfil=cls.p_ana, inicio=ini, fin=ini.replace(hour=17),
                               estado=Jornada.Estado.COMPLETADA)
        Ausencia.objects.create(empresa=cls.e, perfil=cls.p_ana, desde=date(2026, 10, 6), hasta=date(2026, 10, 6),
                                tipo=Ausencia.Tipo.PERMISO, nota='Trámite', creada_por=cls.pmo)
        NotaCalendario.objects.create(empresa=cls.e, fecha=date(2026, 10, 12), texto='Feriado', creada_por=cls.pmo)

    def con_plantilla(self):
        c = ConfigJornadas.de(self.e)
        c.plantilla_certificado.save('p.xlsx', ContentFile(plantilla_minima()), save=True)

    def test_sin_plantilla_usa_la_base(self):
        fechas, valor, _ = certificado.periodo_certificado('month', 2026, 10)
        wb = openpyxl.load_workbook(io.BytesIO(certificado.generar(self.e, fechas, valor)))
        self.assertEqual(wb.sheetnames, ['Resumen', 'Ana', 'Proyectos'])            # sin hoja de ayuda `_Variables`
        self.assertEqual(wb['Resumen']['B7'].value, 'Ana')

    def test_plantilla_ilegible(self):
        c = ConfigJornadas.de(self.e)
        c.plantilla_certificado.save('p.xlsx', ContentFile(b'no es un xlsx'), save=True)
        with self.assertRaises(certificado.CertificadoError):
            certificado.generar(self.e, *certificado.periodo_certificado('month', 2026, 10)[:2])

    def test_periodo(self):
        fechas, valor, etiqueta = certificado.periodo_certificado('month', 2026, 2)
        self.assertEqual((len(fechas), etiqueta, valor), (28, '2026-02', date(2026, 2, 1)))
        fechas, _, _ = certificado.periodo_certificado('range', desde=date(2026, 1, 1), hasta=date(2026, 3, 1))
        self.assertEqual(len(fechas), certificado.MAX_DAYS)

    def test_generar_rellena_hojas(self):
        self.con_plantilla()
        fechas, valor, _ = certificado.periodo_certificado('month', 2026, 10)
        wb = openpyxl.load_workbook(io.BytesIO(certificado.generar(self.e, fechas, valor)))
        self.assertEqual(wb.sheetnames, ['PL', '1'])            # solo hay una persona: sobran 11 hojas
        h = wb['1']
        self.assertEqual((h['B5'].value, h['B6'].value, h['B7'].value), (str(self.ana), 'Ejecutor - Ingeniera', 3000.0))
        fila = certificado.E_FIRST_ROW
        self.assertEqual(h.cell(row=fila + 4, column=3).value, time(8, 10))          # 5 de octubre
        self.assertIn('Trámite', h.cell(row=fila + 5, column=8).value)               # permiso del 6
        self.assertIn('Feriado', h.cell(row=fila + 11, column=8).value)              # nota del 12
        pl, r = wb['PL'], certificado.PL_FIRST_ROW
        self.assertEqual(pl.cell(row=r, column=2).value, str(self.ana))
        self.assertEqual(pl.cell(row=r, column=5 + 6).value, 'SI')                   # el permiso cuenta como trabajado
        self.assertEqual(pl.cell(row=r, column=5 + 5).value, f"=+IF('1'!F{fila + 4}>1,\"SI\",\"NO\")")

    def test_texto_libre_no_es_formula(self):
        Perfil.objects.filter(pk=self.p_ana.pk).update(cargo='=HYPERLINK("http://x","a")')
        Ausencia.objects.filter(perfil=self.p_ana).update(tipo=Ausencia.Tipo.OTRO, nota='=1+1')
        self.con_plantilla()
        fechas, valor, _ = certificado.periodo_certificado('month', 2026, 10)
        wb = openpyxl.load_workbook(io.BytesIO(certificado.generar(self.e, fechas, valor)))
        for celda in (wb['1']['B6'], wb['1'].cell(row=certificado.E_FIRST_ROW + 5, column=8),
                      wb['PL'].cell(row=certificado.PL_FIRST_ROW, column=3)):
            self.assertEqual(celda.data_type, 's', celda.coordinate)

    def test_nombre_configurable_por_empresa(self):
        self.assertEqual(self.e.nombre_certificado, 'Reporte de personal')          # genérico por defecto
        self.con_plantilla()
        self.client.force_login(self.pmo)
        self.assertContains(self.client.get('/tekon/jornadas/certificado/'), 'Reporte de personal')
        self.e.termino_certificado = 'Certificado de pago'
        self.e.save()
        pagina = self.client.get('/tekon/jornadas/certificado/')
        self.assertContains(pagina, 'Certificado de pago')
        r = self.client.get('/tekon/jornadas/certificado/?descargar=1&month=10&year=2026')
        self.assertIn('certificado-de-pago-tekon-2026-10.xlsx', r['Content-Disposition'])
        self.e.termino_certificado = '  '
        self.e.save()
        self.assertEqual(self.e.nombre_certificado, 'Reporte de personal')          # vacío = genérico

    def test_vista(self):
        self.con_plantilla()
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/jornadas/certificado/?descargar=1&month=10&year=2026')
        self.assertEqual(r.status_code, 200)
        self.assertIn('reporte-de-personal-tekon-2026-10.xlsx', r['Content-Disposition'])
        self.assertEqual(self.client.get('/tekon/jornadas/certificado/').status_code, 200)
        self.client.force_login(self.ana)
        self.assertEqual(self.client.get('/tekon/jornadas/certificado/').status_code, 403)

    def test_vista_sin_plantilla_descarga_la_base(self):
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/jornadas/certificado/?descargar=1&month=10&year=2026')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(openpyxl.load_workbook(io.BytesIO(r.content)).sheetnames[0], 'Resumen')

    def test_vista_con_plantilla_ilegible_redirige(self):
        ConfigJornadas.de(self.e).plantilla_certificado.save('p.xlsx', ContentFile(b'x'), save=True)
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/jornadas/certificado/?descargar=1')
        self.assertRedirects(r, '/tekon/jornadas/certificado/', fetch_redirect_response=False)


@override_settings(**AJUSTES)
class NombreDelReporteEnJornadasTests(TestCase):
    def test_se_edita_en_la_configuracion_de_jornadas_y_no_en_marca(self):
        from jor_empleados.forms import ConfigJornadasForm
        from panel.forms import MarcaForm
        e = crear_empresa(nombre='Tekon', slug='tekon', modulos=['jor'])
        self.assertNotIn('termino_certificado', MarcaForm().fields)
        form = ConfigJornadasForm({'descuento_refrigerio_min': 60, 'termino_certificado': ' Certificado de pago '},
                                  instance=ConfigJornadas.de(e))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        e.refresh_from_db()
        self.assertEqual(e.nombre_certificado, 'Certificado de pago')
        form = ConfigJornadasForm({'descuento_refrigerio_min': 60, 'termino_certificado': ''}, instance=ConfigJornadas.de(e))
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        e.refresh_from_db()
        self.assertEqual(e.nombre_certificado, 'Reporte de personal')
