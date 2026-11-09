"""Motor de plantillas con variables del reporte de personal."""
import io
from datetime import date, datetime, time

import openpyxl
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from jor_diario.models import Ausencia, Jornada, NotaCalendario
from jor_empleados.forms import ConfigJornadasForm
from jor_empleados.models import ConfigJornadas, Perfil
from proyectos.models import Proyecto

from . import certificado, plantilla_base, plantilla_motor, variables, xlsx_util
from .tests_certificado import AJUSTES


def libro(*hojas):
    """Libro de prueba: cada hoja es (título, {celda: valor})."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for titulo, celdas in hojas:
        ws = wb.create_sheet(titulo)
        for ref, v in celdas.items():
            ws[ref] = v
    return wb


def persona(i, nombre, dias=2, **extra):
    return {'item': i, 'nombre': nombre, 'cargo_completo': 'Sup', 'horas_netas': 16.5,
            'horas': {str(n): (8.0 if n <= dias else None) for n in range(1, 32)},
            'dias': [{'fecha': date(2026, 10, d + 1), 'horas_netas': 8.0, 'observaciones': ''} for d in range(dias)],
            'proyectos': [{'nombre': 'P1', 'horas': 10.0}, {'nombre': 'P2', 'horas': 6.5}], **extra}


def contexto(*personas):
    return {'empresa': {'nombre': 'Tekon'}, 'reporte': {'nombre': 'Reporte'}, 'personas': list(personas),
            'periodo': {'etiqueta': 'Octubre 2026', 'desde': date(2026, 10, 1), 'dia': {str(n): n for n in range(1, 32)}},
            'proyectos': [{'nombre': 'P1', 'horas': 20.0}], 'total': {'personas': len(personas)}}


class ValidarTests(SimpleTestCase):
    def test_variable_desconocida_con_hoja_y_celda(self):
        errores = plantilla_motor.validar(libro(('Datos', {'B5': '{{ persona.sueldo }}'})))
        self.assertEqual(len(errores), 1)
        self.assertIn('Datos', errores[0])
        self.assertIn('B5', errores[0])
        self.assertIn('persona.sueldo', errores[0])

    def test_fila_mixta_y_dia_fuera_de_hoja_por_persona(self):
        mixta = plantilla_motor.validar(libro(('G', {'A3': '{{ persona.nombre }}', 'B3': '{{ proyecto.nombre }}'})))
        self.assertTrue(any('fila 3' in e and 'mezcla' in e for e in mixta))
        dia = plantilla_motor.validar(libro(('G', {'A3': '{{ dia.fecha }}'})))
        self.assertTrue(any('dia.fecha' in e and 'hoja por persona' in e for e in dia))

    def test_variables_dentro_de_formula_y_titulo_invalido(self):
        self.assertTrue(plantilla_motor.validar(libro(('G', {'A1': '=SUM({{ total.horas_netas }})'}))))
        self.assertTrue(plantilla_motor.validar(libro(('{{ empresa.nombre }}', {'A1': 'x'}))))

    def test_alimentacion_solo_en_la_hoja_general(self):
        general = libro(('G', {'A3': '{{ alimentacion_lpz.nombre }}', 'B3': '{{ alimentacion_lpz.alimentacion.31 }}'}))
        self.assertEqual(plantilla_motor.validar(general), [])
        en_persona = libro(('{{ persona.nombre }}', {'A3': '{{ alimentacion_lpz.nombre }}'}))
        self.assertTrue(any('alimentacion_lpz.nombre' in e and 'hoja general' in e for e in plantilla_motor.validar(en_persona)))
        self.assertTrue(plantilla_motor.validar(libro(('G', {'A3': '{{ alimentacion_xyz.nombre }}'}))))     # ciudad inexistente

    def test_el_modelo_skylog_es_valido(self):
        self.assertEqual(plantilla_motor.validar(openpyxl.load_workbook(plantilla_base.RUTA_MODELO)), [])

    def test_hojas_de_ayuda_se_ignoran_y_la_base_es_valida(self):
        self.assertEqual(plantilla_motor.validar(libro(('_Notas', {'A1': '{{ cualquier.cosa }}'}))), [])
        self.assertEqual(plantilla_motor.validar(plantilla_base.construir()), [])

    def test_catalogo_completo_en_la_base(self):
        """Toda variable del catálogo figura en la hoja `_Variables` de la base (y es válida)."""
        wb = plantilla_base.construir()
        escritas = {c.value for fila in wb['_Variables'].iter_rows() for c in fila if isinstance(c.value, str)}
        for _, nombre, _, _ in variables.CATALOGO:
            self.assertIn('{{ ' + nombre + ' }}', escritas)
        self.assertIn('persona.horas.31', variables.nombres_validos())


class RenderTests(SimpleTestCase):
    def test_escalares_nativos_y_texto(self):
        wb = libro(('Hoja', {'A1': '{{ periodo.desde }}', 'A2': '{{ total.personas }}', 'A3': 'Empresa: {{ empresa.nombre }}',
                             'A4': '{{ periodo.etiqueta }}'}))
        plantilla_motor.renderizar(wb, contexto(persona(1, 'Ana')))
        ws = wb['Hoja']
        self.assertEqual((ws['A1'].value, ws['A2'].value, ws['A3'].value, ws['A4'].value),
                         (date(2026, 10, 1), 1, 'Empresa: Tekon', 'Octubre 2026'))
        self.assertEqual(ws['A1'].number_format, 'dd-mm-yyyy')

    def test_filas_por_persona_formulas_y_total(self):
        wb = libro(('Resumen', {'A1': 'N', 'A2': '{{ persona.item }}', 'B2': '{{ persona.nombre }}',
                                'C2': '=A2*2', 'A3': 'Total', 'C3': '=SUM(C2:C2)'}))
        plantilla_motor.renderizar(wb, contexto(persona(1, 'Ana'), persona(2, 'Luis'), persona(3, 'Eva')))
        ws = wb['Resumen']
        self.assertEqual([ws.cell(row=r, column=2).value for r in (2, 3, 4)], ['Ana', 'Luis', 'Eva'])
        self.assertEqual([ws.cell(row=r, column=3).value for r in (2, 3, 4)], ['=A2*2', '=A3*2', '=A4*2'])   # trasladadas
        self.assertEqual((ws['A5'].value, ws['C5'].value), ('Total', '=SUM(C2:C4)'))                         # el total abarca todo

    def test_matriz_de_dias_y_cabecera(self):
        wb = libro(('M', {'A1': '{{ periodo.dia.1 }}', 'B1': '{{ periodo.dia.2 }}', 'A2': '{{ persona.horas.1 }}',
                          'B2': '{{ persona.horas.3 }}'}))
        plantilla_motor.renderizar(wb, contexto(persona(1, 'Ana', dias=2)))
        ws = wb['M']
        self.assertEqual((ws['A1'].value, ws['B1'].value, ws['A2'].value, ws['B2'].value), (1, 2, 8.0, None))

    def test_hoja_por_persona_con_dias_proyectos_y_nombres_unicos(self):
        wb = libro(('Resumen', {'A1': '{{ reporte.nombre }}'}),
                   ('{{ persona.nombre }}', {'A1': '{{ persona.nombre }}', 'A3': '{{ dia.fecha }}', 'B3': '{{ dia.horas_netas }}',
                                             'A4': 'Total', 'B4': '=SUM(B3:B3)', 'A6': '{{ proyecto.nombre }}',
                                             'B6': '{{ proyecto.horas }}', 'B7': '=SUM(B6:B6)'}))
        plantilla_motor.renderizar(wb, contexto(persona(1, 'Ana', dias=3), persona(2, 'Ana', dias=1),
                                                persona(3, 'Nombre muy largo ' * 3 + '[x]/y', dias=1)))
        self.assertEqual(wb.sheetnames[0], 'Resumen')
        ana, ana2, largo = wb.worksheets[1], wb.worksheets[2], wb.worksheets[3]
        self.assertEqual((ana.title, ana2.title), ('Ana', 'Ana2'))
        self.assertTrue(len(largo.title) <= 31 and not set(largo.title) & set('[]/'))
        self.assertEqual([ana.cell(row=r, column=1).value for r in (3, 4, 5)], [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)])
        self.assertEqual(ana['B6'].value, '=SUM(B3:B5)')                       # 3 días: el total abarca 3 filas
        self.assertEqual((ana['A8'].value, ana['A9'].value), ('P1', 'P2'))      # proyectos tras las 3 filas de días
        self.assertEqual(ana['B10'].value, '=SUM(B8:B9)')
        self.assertEqual(ana2['B4'].value, '=SUM(B3:B3)')                       # 1 día: sin cambios
        self.assertNotIn('{{ persona.nombre }}', wb.sheetnames)

    def test_hojas_de_ayuda_no_salen(self):
        wb = libro(('Datos', {'A1': '{{ empresa.nombre }}'}), ('_Ayuda', {'A1': 'notas'}))
        plantilla_motor.renderizar(wb, contexto())
        self.assertEqual(wb.sheetnames, ['Datos'])

    def test_los_datos_nunca_son_formulas(self):
        peligro = '=HYPERLINK("http://malo","x")'
        wb = libro(('G', {'A1': '{{ persona.nombre }}', 'B1': 'Hola {{ persona.nombre }}'}),
                   ('{{ persona.nombre }}', {'A1': '{{ persona.nombre }}', 'A2': '{{ dia.observaciones }}'}))
        p = persona(1, peligro, dias=1)
        p['dias'][0]['observaciones'] = '=1+1'
        plantilla_motor.renderizar(wb, contexto(p))
        g, h = wb['G'], wb.worksheets[1]
        for c in (g['A1'], g['B1'], h['A1'], h['A2']):
            self.assertEqual(c.data_type, 's', c.coordinate)
        self.assertEqual(g['A1'].value, peligro)

    def test_sin_personas_queda_una_fila_vacia(self):
        wb = libro(('R', {'A2': '{{ persona.nombre }}', 'A3': 'Total', 'B3': '=SUM(B2:B2)'}))
        plantilla_motor.renderizar(wb, contexto())
        self.assertIsNone(wb['R']['A2'].value)
        self.assertEqual(wb['R']['B3'].value, '=SUM(B2:B2)')


class FormulasTests(SimpleTestCase):
    def test_ajustar_referencias(self):
        wb = libro(('H', {'A1': '=SUM(B5:B5)', 'A2': '=B9+B5+LOG10(B6)', 'A3': "='Otra'!B5+B7", 'A4': '=SUM($B$3:$B$5)'}),
                   ('Otra', {'A1': '=H!B5+H!B6+B5', 'B5': 1}))
        xlsx_util.ajustar_formulas(wb, wb['H'], 5, 2)
        h, otra = wb['H'], wb['Otra']
        self.assertEqual(h['A1'].value, '=SUM(B5:B7)')
        self.assertEqual(h['A2'].value, '=B11+B5+LOG10(B8)')                       # LOG10 no es una celda
        self.assertEqual(h['A3'].value, "='Otra'!B5+B9")                           # otra hoja: intacta
        self.assertEqual(h['A4'].value, '=SUM($B$3:$B$7)')
        self.assertEqual(otra['A1'].value, '=H!B5+H!B8+B5')                        # cita a H: se ajusta; lo local no


@override_settings(**AJUSTES)
class IntegracionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.e = crear_empresa(nombre='Tekon', slug='tekon', modulos=['jor'])
        cls.pmo = User.objects.create_user('pmo@x.cl', 'x')
        m = agregar_miembro(cls.pmo, cls.e, rol_por_base(cls.e, RolBase.COORDINADOR))
        Perfil.objects.filter(pk=Perfil.de(m).pk).update(activo=False)
        cls.ana = User.objects.create_user('ana@x.cl', 'x', first_name='Ana')
        cls.p_ana = Perfil.de(agregar_miembro(cls.ana, cls.e, rol_por_base(cls.e, RolBase.MIEMBRO)))
        cls.torre = Proyecto.objects.create(empresa=cls.e, nombre='Torre 1', codigo='T-1')
        ini = timezone.make_aware(datetime(2026, 10, 5, 8, 10))
        for dia, proyecto in ((5, cls.torre), (6, None)):
            Jornada.objects.create(empresa=cls.e, perfil=cls.p_ana, proyecto=proyecto, duracion_min=540,
                                   inicio=ini.replace(day=dia), fin=ini.replace(day=dia, hour=17), estado=Jornada.Estado.COMPLETADA)
        Ausencia.objects.create(empresa=cls.e, perfil=cls.p_ana, desde=date(2026, 10, 7), hasta=date(2026, 10, 7),
                                tipo=Ausencia.Tipo.PERMISO, nota='Trámite', creada_por=cls.pmo, estado=Ausencia.Estado.APROBADA)
        NotaCalendario.objects.create(empresa=cls.e, fecha=date(2026, 10, 12), texto='Feriado', creada_por=cls.pmo)

    def generar(self):
        fechas, valor, _ = certificado.periodo_certificado('month', 2026, 10)
        return openpyxl.load_workbook(io.BytesIO(certificado.generar(self.e, fechas, valor, self.pmo)))

    def test_contexto_trae_lo_que_promete_el_catalogo(self):
        fechas = certificado.periodo_certificado('month', 2026, 10)[0]
        ctx = variables.contexto(self.e, fechas, self.pmo)
        self.assertEqual((ctx['periodo']['etiqueta'], ctx['periodo']['dias'], ctx['generado']['por']), ('Octubre 2026', 31, str(self.pmo)))
        p = ctx['personas'][0]
        self.assertEqual((p['nombre'], p['dias_trabajados'], p['email']), ('Ana', 2, 'ana@x.cl'))
        self.assertEqual(p['horas']['5'], 8.0)                          # 9 h menos 1 h de refrigerio
        self.assertEqual((p['asistio']['5'], p['asistio']['8']), ('SI', 'NO'))
        self.assertTrue(any('Trámite' in d['observaciones'] for d in p['dias']))
        self.assertTrue(any('Feriado' in d['observaciones'] for d in p['dias']))
        self.assertEqual({(x['nombre'], x['jornadas'], x['horas']) for x in p['proyectos']},
                         {('Torre 1', 1, 9.0), ('Sin proyecto', 1, 9.0)})
        self.assertEqual(ctx['total']['personas'], 1)
        self.assertNotIn('pmo@x.cl', str(ctx['personas']))               # el perfil inactivo no figura

    def test_pagado_alimentacion_y_dias_habiles(self):
        Perfil.objects.filter(pk=self.p_ana.pk).update(ciudad_catering='LPZ', haber_basico=3000)
        ctx = variables.contexto(self.e, certificado.periodo_certificado('month', 2026, 10)[0], self.pmo)
        p = ctx['personas'][0]
        self.assertEqual((p['pagado']['5'], p['pagado']['7'], p['pagado']['8']), ('SI', 'SI', 'NO'))             # el permiso cuenta
        self.assertEqual((p['alimentacion']['5'], p['alimentacion']['7'], p['alimentacion']['8']), ('SI', 'NO', 'NO'))
        self.assertEqual((p['dias_pagados'], p['dias_alimentacion'], p['haber_basico'], p['ciudad']), (3, 2, 3000.0, 'La Paz'))
        self.assertEqual([x['nombre'] for x in ctx['alimentacion_lpz']], ['Ana'])
        self.assertEqual((ctx['alimentacion_cba'], ctx['alimentacion_scz']), ([], []))
        self.assertEqual(ctx['periodo']['dias_habiles'], 21)             # octubre 2026: 22 lun-vie menos el feriado del 12
        self.assertEqual((ctx['reporte']['moneda'], float(ctx['reporte']['tipo_cambio'])), ('Bolivianos', 0.461310893326))

    def test_modelo_skylog_de_punta_a_punta(self):
        Perfil.objects.filter(pk=self.p_ana.pk).update(ciudad_catering='LPZ', haber_basico=3000)
        beto = User.objects.create_user('beto@x.cl', 'x', first_name='Beto')
        p_beto = Perfil.de(agregar_miembro(beto, self.e, rol_por_base(self.e, RolBase.MIEMBRO)))
        Perfil.objects.filter(pk=p_beto.pk).update(ciudad_catering='SCZ', haber_basico=2000)
        ConfigJornadas.de(self.e).plantilla_certificado.save('modelo.xlsx', ContentFile(plantilla_base.bytes_modelo()), save=True)
        wb = self.generar()
        self.assertEqual(wb.sheetnames, ['PL', '1', '2'])                  # una hoja por persona; `_Variables` no sale
        pl = wb['PL']
        nombres = [pl.cell(row=r, column=2).value for r in range(1, pl.max_row + 1) if pl.cell(row=r, column=2).value]
        self.assertEqual([n for n in nombres if n in ('Ana', 'Beto')], ['Ana', 'Beto', 'Ana', 'Beto'])   # personal, LPZ, SCZ
        self.assertEqual((pl['AA5'].value, pl['Y7'].value), (21, 'Bolivianos'))
        self.assertEqual(pl['F13'].value, 1)
        fila_ana = next(r for r in range(1, pl.max_row + 1) if pl.cell(row=r, column=2).value == 'Ana')
        self.assertEqual([pl.cell(row=fila_ana, column=5 + d).value for d in (5, 7, 8)], ['SI', 'SI', 'NO'])   # días 5, 7 y 8
        self.assertEqual(pl.cell(row=fila_ana, column=5).value, 3000.0)
        self.assertEqual(pl.cell(row=fila_ana + 1, column=39).value, f'=+AL{fila_ana + 1}/$Y$9')               # fila de Beto
        self.assertEqual(pl.cell(row=fila_ana + 2, column=39).value, f'=SUM(AM{fila_ana}:AM{fila_ana + 1})')   # subtotal abarca ambas
        lpz = next(r for r in range(fila_ana + 3, pl.max_row + 1) if pl.cell(row=r, column=2).value == 'Ana')
        self.assertEqual([pl.cell(row=lpz, column=5 + d).value for d in (5, 7)], ['SI', 'NO'])                 # alimentación: la ausencia excluye
        self.assertTrue(any('Son : ' in str(c.value) for fila in pl.iter_rows() for c in fila))
        self.assertEqual(len(list(pl.conditional_formatting)), 3)
        hoja = wb['1']
        self.assertEqual((hoja['B4'].value, hoja['B5'].value, hoja['B7'].value), (1, 'Ana', 3000.0))
        self.assertEqual(hoja['C14'].value, time(8, 10))                   # día 5, hora nativa de Excel
        self.assertEqual(hoja['C41'].value, '=+COUNT(C10:C40)')           # 31 días de octubre
        celdas = [c.value for h in wb for fila in h.iter_rows() for c in fila if isinstance(c.value, str)]
        self.assertFalse([v for v in celdas if '{{' in v])

    def test_base_de_punta_a_punta(self):
        wb = self.generar()
        self.assertEqual(wb.sheetnames, ['Resumen', 'Ana', 'Proyectos'])
        resumen = wb['Resumen']
        self.assertEqual((resumen['B7'].value, resumen['D7'].value, resumen['E7'].value), ('Ana', 2, 16.0))
        self.assertEqual(resumen['D8'].value, '=SUM(D7:D7)')
        self.assertEqual(resumen['I6'].value, 1)                        # cabecera de días
        self.assertEqual(resumen.cell(row=7, column=9 + 4).value, 8.0)   # día 5
        ana = wb['Ana']
        self.assertEqual(ana['B2'].value, 'Ana')
        self.assertEqual(ana.cell(row=7 + 4, column=1).value.date(), date(2026, 10, 5))   # al releer el archivo, Excel devuelve datetime
        self.assertEqual(ana['E38'].value, '=SUM(E7:E37)')              # 31 días de octubre
        celdas = [c.value for hoja in wb for fila in hoja.iter_rows() for c in fila if isinstance(c.value, str)]
        self.assertFalse([v for v in celdas if '{{' in v])

    def test_plantilla_propia_con_variables(self):
        wb = libro(('Mi reporte', {'A1': '{{ empresa.nombre }} — {{ periodo.etiqueta }}', 'A3': '{{ persona.nombre }}',
                                   'B3': '{{ persona.horas_netas }}', 'A4': 'Horas', 'B4': '=SUM(B3:B3)'}))
        buf = io.BytesIO()
        wb.save(buf)
        ConfigJornadas.de(self.e).plantilla_certificado.save('p.xlsx', ContentFile(buf.getvalue()), save=True)
        generado = self.generar()
        self.assertEqual(generado.sheetnames, ['Mi reporte'])
        h = generado['Mi reporte']
        self.assertEqual((h['A1'].value, h['A3'].value, h['B3'].value), ('Tekon — Octubre 2026', 'Ana', 16.0))

    def test_plantilla_subida_con_error_no_genera(self):
        buf = io.BytesIO()
        libro(('X', {'A1': '{{ persona.sueldo }}'})).save(buf)
        ConfigJornadas.de(self.e).plantilla_certificado.save('p.xlsx', ContentFile(buf.getvalue()), save=True)
        with self.assertRaises(certificado.CertificadoError):
            self.generar()


@override_settings(**AJUSTES)
class FormularioYDescargasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.e = crear_empresa(nombre='Tekon', slug='tekon', modulos=['jor'])
        cls.pmo = User.objects.create_user('pmo@x.cl', 'x')
        agregar_miembro(cls.pmo, cls.e, rol_por_base(cls.e, RolBase.COORDINADOR))
        cls.ana = User.objects.create_user('ana@x.cl', 'x')
        agregar_miembro(cls.ana, cls.e, rol_por_base(cls.e, RolBase.MIEMBRO))

    def subir(self, wb):
        buf = io.BytesIO()
        wb.save(buf)
        archivo = SimpleUploadedFile('p.xlsx', buf.getvalue())
        return ConfigJornadasForm({'descuento_refrigerio_min': 60}, {'plantilla_certificado': archivo},
                                  instance=ConfigJornadas.de(self.e))

    def test_acepta_variables_o_formato_clasico_y_rechaza_el_resto(self):
        self.assertTrue(self.subir(plantilla_base.construir()).is_valid())
        self.assertTrue(self.subir(libro(('PL', {}), ('1', {}))).is_valid())
        malo = self.subir(libro(('X', {'A1': '{{ persona.sueldo }}'})))
        self.assertFalse(malo.is_valid())
        self.assertIn('persona.sueldo', str(malo.errors['plantilla_certificado']))
        sin_nada = self.subir(libro(('X', {'A1': 'hola'})))
        self.assertFalse(sin_nada.is_valid())
        self.assertIn('plantilla base', str(sin_nada.errors['plantilla_certificado']))

    def test_no_es_un_xlsx(self):
        f = ConfigJornadasForm({'descuento_refrigerio_min': 60}, {'plantilla_certificado': SimpleUploadedFile('p.xlsx', b'basura')},
                               instance=ConfigJornadas.de(self.e))
        self.assertFalse(f.is_valid())

    def test_descargas_y_permisos(self):
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/jornadas/certificado/plantilla-base/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('plantilla-reporte-de-personal.xlsx', r['Content-Disposition'])
        self.assertIn('_Variables', openpyxl.load_workbook(io.BytesIO(r.content)).sheetnames)
        modelo = self.client.get('/tekon/jornadas/certificado/plantilla-modelo/')
        self.assertIn('plantilla-modelo-reporte-de-personal.xlsx', modelo['Content-Disposition'])
        self.assertEqual(plantilla_motor.validar(openpyxl.load_workbook(io.BytesIO(modelo.content))), [])
        self.assertEqual(self.client.get('/tekon/jornadas/certificado/plantilla-actual/').status_code, 404)   # aún no hay propia
        ConfigJornadas.de(self.e).plantilla_certificado.save('p.xlsx', ContentFile(plantilla_base.bytes_plantilla()), save=True)
        self.assertEqual(self.client.get('/tekon/jornadas/certificado/plantilla-actual/').status_code, 200)
        self.client.force_login(self.ana)
        for url in ('plantilla-base', 'plantilla-modelo', 'plantilla-actual'):
            self.assertEqual(self.client.get(f'/tekon/jornadas/certificado/{url}/').status_code, 403)

    def test_pantalla_de_configuracion_muestra_estado_y_variables(self):
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/jornadas/config/')
        self.assertContains(r, 'Descargar plantilla base')
        self.assertContains(r, 'Descargar plantilla modelo')
        self.assertContains(r, '{{ persona.nombre }}')
        self.assertNotContains(r, 'Descargar plantilla actual')
