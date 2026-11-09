from datetime import date, datetime, timedelta
from io import BytesIO

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from openpyxl import load_workbook

from jor_actividades import servicios as actividades
from jor_actividades.models import Etiqueta, ItemActividad
from jor_diario import servicios as jornadas
from jor_diario.models import Ausencia, Jornada, NotaCalendario, ReporteDiario
from jor_diario.tests import JornadasBase
from jor_empleados.models import ConfigJornadas, Perfil

from . import excel, periodo as per, servicios


def aware(dia, hora=0, minuto=0):
    return timezone.make_aware(datetime(dia.year, dia.month, dia.day, hora, minuto))


class PeriodoTests(SimpleTestCase):
    hoy = date(2026, 6, 15)

    def leer(self, **get):
        return per.leer(get, permitir_todo=get.pop('todo', False), hoy=self.hoy)

    def test_mes_por_defecto_y_tope_en_hoy(self):
        p = self.leer()
        self.assertEqual((p.desde, p.hasta, p.etiqueta), (date(2026, 6, 1), date(2026, 6, 15), 'Junio 2026'))
        p = self.leer(year='2026', month='2')
        self.assertEqual((p.desde, p.hasta), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(len(list(p.dias())), 28)

    def test_mes_futuro_no_se_rompe(self):
        p = self.leer(year='2027', month='3')
        self.assertEqual((p.desde, p.hasta), (date(2027, 3, 1), date(2027, 3, 1)))

    def test_valores_invalidos_caen_al_mes_actual(self):
        for get in ({'month': '13'}, {'month': 'x'}, {'year': '1800'}, {'mode': 'range', 'from': 'x', 'to': 'y'}):
            p = self.leer(**get)
            self.assertEqual(p.desde, date(2026, 6, 1), get)

    def test_rango(self):
        p = self.leer(mode='range', **{'from': '2026-05-10', 'to': '2026-05-12'})
        self.assertEqual((p.desde, p.hasta, p.modo), (date(2026, 5, 10), date(2026, 5, 12), 'range'))
        p = self.leer(mode='range', **{'from': '2026-05-10', 'to': '2026-05-01'})            # invertido
        self.assertEqual((p.desde, p.hasta), (date(2026, 5, 10), date(2026, 5, 10)))

    def test_todo_y_ultimo_solo_si_se_permite(self):
        self.assertEqual(self.leer(mode='all').modo, 'month')
        p = self.leer(mode='all', todo=True)
        self.assertEqual((p.modo, p.desde, p.inicio_dt), ('all', None, None))
        self.assertEqual(self.leer(mode='last', todo=True).modo, 'last')


class DatosBase(JornadasBase):
    def jornada(self, user, dia, h_ini=8, m_ini=0, minutos=540, hecho='', plan='', cierre_auto=False, estado='completada',
                empresa=None):
        empresa = empresa or self.a
        p = self.perfil(user, empresa)
        ini = aware(dia, h_ini, m_ini)
        j = Jornada.objects.create(empresa=empresa, perfil=p, inicio=ini, fin=ini + timedelta(minutes=minutos),
                                   duracion_min=minutos, estado=estado, cierre_auto=cierre_auto)
        if hecho or plan:
            r = ReporteDiario.objects.create(jornada=j, realizado=hecho, planificado=plan)
            actividades.sincronizar_items(r)
        return j

    def periodo(self, desde, hasta):
        return per.Periodo('range', desde, hasta, 'test')


class AsistenciaTests(DatosBase):
    def test_horas_netas_atraso_y_totales(self):
        self.jornada(self.emp, date(2026, 3, 2), 8, 20, 540)           # 9 h − 1 h refrigerio = 8 h; 20 min tarde
        self.jornada(self.emp, date(2026, 3, 3), 7, 50, 480)           # temprano: sin atraso; 7 h netas
        r = servicios.asistencia(self.a, self.periodo(date(2026, 3, 2), date(2026, 3, 4)), self.emp.membresias.get().pk)
        self.assertEqual(len(r), 1)
        p = r[0]
        self.assertEqual((p['dias'], p['horas'], p['atraso_min']), (2, '15:00', 20))
        f = p['filas']
        self.assertEqual((f[0]['ingreso'], f[0]['salida'], f[0]['horas'], f[0]['atraso_min']), ('08:20', '17:20', '08:00', 20))
        self.assertEqual((f[1]['atraso_min'], f[2]['horas'], f[2]['atraso_min']), (0, '', None))        # día sin jornada
        self.assertEqual(f[0]['dia'], 'lunes')

    def test_refrigerio_configurable_y_nunca_negativo(self):
        c = ConfigJornadas.de(self.a)
        c.descuento_refrigerio_min = 30
        c.save()
        self.jornada(self.emp, date(2026, 3, 2), minutos=540)
        self.jornada(self.emp, date(2026, 3, 3), minutos=20)
        p = servicios.asistencia(self.a, self.periodo(date(2026, 3, 2), date(2026, 3, 3)), self.emp.membresias.get().pk)[0]
        self.assertEqual([f['horas'] for f in p['filas']], ['08:30', '00:00'])

    def test_varias_jornadas_el_mismo_dia_se_agregan(self):
        self.jornada(self.emp, date(2026, 3, 2), 8, 0, 240)
        self.jornada(self.emp, date(2026, 3, 2), 14, 0, 240)
        p = servicios.asistencia(self.a, self.periodo(date(2026, 3, 2), date(2026, 3, 2)), self.emp.membresias.get().pk)[0]
        f = p['filas'][0]
        self.assertEqual((f['ingreso'], f['salida'], f['horas'], p['dias']), ('08:00', '18:00', '07:00', 1))

    def test_jornada_en_curso_o_de_otra_persona_o_fuera_de_periodo_no_cuentan(self):
        p = self.perfil(self.emp)
        Jornada.objects.create(empresa=self.a, perfil=p, inicio=aware(date(2026, 3, 2), 8))          # en curso
        self.jornada(self.emp2, date(2026, 3, 2))
        self.jornada(self.emp, date(2026, 4, 2))
        r = servicios.asistencia(self.a, self.periodo(date(2026, 3, 1), date(2026, 3, 31)), self.emp.membresias.get().pk)[0]
        self.assertEqual(r['dias'], 0)

    def test_sin_cerrar_ausencias_y_notas(self):
        self.jornada(self.emp, date(2026, 3, 2), cierre_auto=True, estado='incompleta')
        Ausencia.objects.create(empresa=self.a, perfil=self.perfil(self.emp), desde=date(2026, 3, 3), hasta=date(2026, 3, 4),
                                tipo='vacacion', nota='viaje', estado='aprobada')
        Ausencia.objects.create(empresa=self.a, perfil=self.perfil(self.emp), desde=date(2026, 3, 5), hasta=date(2026, 3, 5),
                                tipo='permiso', estado='pendiente')
        NotaCalendario.objects.create(empresa=self.a, fecha=date(2026, 3, 4), texto='Aniversario', tipo='evento')
        NotaCalendario.objects.create(empresa=self.b, fecha=date(2026, 3, 4), texto='Secreto', tipo='evento')
        p = servicios.asistencia(self.a, self.periodo(date(2026, 3, 2), date(2026, 3, 5)), self.emp.membresias.get().pk)[0]
        f = p['filas']
        self.assertEqual((p['no_cerro'], f[0]['no_cerro']), (1, True))
        self.assertEqual(f[1]['comentarios'], ['Vacación (viaje)'])
        self.assertEqual(f[2]['comentarios'], ['Vacación (viaje)', 'Evento: Aniversario'])
        self.assertEqual(f[3]['comentarios'], [])                          # la pendiente no aparece
        self.assertEqual(p['ausencias'], 2)

    def test_solo_personas_activas_con_perfil_habilitado_de_la_empresa(self):
        Perfil.objects.filter(pk=self.perfil(self.emp2).pk).update(activo=False)
        m = self.vis.membresias.get()
        m.activa = False
        m.save()
        nombres = [p['nombre'] for p in servicios.asistencia(self.a, self.periodo(date(2026, 3, 2), date(2026, 3, 2)))]
        self.assertNotIn(str(self.emp2), nombres)
        self.assertNotIn(str(self.vis), nombres)
        self.assertNotIn(str(self.ajeno), nombres)
        self.assertIn(str(self.emp), nombres)


class EstadisticasTests(DatosBase):
    def setUp(self):
        super().setUp()
        self.jornada(self.emp, date(2026, 3, 2), hecho='Reunión con cliente\nInforme semanal\nAlmuerzo', plan='Visita a obra')
        self.jornada(self.emp, date(2026, 4, 6), hecho='Reunión de coordinación')
        self.jornada(self.emp2, date(2026, 3, 3), hecho='Planos de piping\nReunión de equipo')
        self.p = per.Periodo('range', date(2026, 3, 1), date(2026, 4, 30), 'test')

    def test_totales_y_porcentajes_por_categoria(self):
        d = servicios.estadisticas(self.a, self.p)
        self.assertEqual((d['total'], d['reportes']), (6, 3))
        c = {x['codigo']: x for x in d['categorias']}
        self.assertEqual((c['reuniones']['n'], c['reuniones']['pct']), (3, 50.0))
        self.assertEqual((c['informes']['n'], c['diseno']['n'], c['otros']['n']), (1, 1, 1))
        self.assertEqual(len(d['categorias']), 13)

    def test_planificadas_y_tipo_invalido(self):
        self.assertEqual(servicios.estadisticas(self.a, self.p, 'planificado')['total'], 1)
        self.assertEqual(servicios.estadisticas(self.a, self.p, 'basura')['total'], 6)

    def test_periodo_acota(self):
        marzo = per.Periodo('range', date(2026, 3, 1), date(2026, 3, 31), 'm')
        self.assertEqual(servicios.estadisticas(self.a, marzo)['total'], 5)
        todo = per.Periodo('all', None, None, 'todo')
        self.assertEqual(servicios.estadisticas(self.a, todo)['total'], 6)

    def test_ultimo_dia_con_datos(self):
        d = servicios.estadisticas(self.a, per.Periodo('last', None, None, 'x'))
        self.assertEqual((d['total'], d['periodo'].desde), (1, date(2026, 4, 6)))

    def test_por_persona_y_filtro_de_persona(self):
        d = servicios.estadisticas(self.a, self.p)
        self.assertEqual([(x['nombre'], x['total'], x['reportes']) for x in d['personas']],
                         [(str(self.emp), 4, 2), (str(self.emp2), 2, 1)])
        self.assertEqual(d['personas'][0]['top'], 'reuniones')
        solo = servicios.estadisticas(self.a, self.p, membresia_id=self.emp2.membresias.get().pk)
        self.assertEqual((solo['total'], len(solo['personas'])), (2, 1))
        self.assertEqual(sum(r['personas'] for r in solo['roles']), 2)            # la referencia del grupo ignora el filtro

    def test_filtro_por_rol_base(self):
        self.jornada(self.dir, date(2026, 3, 4), hecho='Informe de avance')
        self.assertEqual(servicios.estadisticas(self.a, self.p, rol_base='COORDINADOR')['total'], 1)
        self.assertEqual(servicios.estadisticas(self.a, self.p, rol_base='MIEMBRO')['total'], 6)
        self.assertEqual(servicios.estadisticas(self.a, self.p, rol_base='inventado')['total'], 7)

    def test_aislamiento_entre_empresas(self):
        self.jornada(self.ajeno, date(2026, 3, 3), hecho='Reunión secreta', empresa=self.b)
        self.assertEqual(servicios.estadisticas(self.a, self.p)['total'], 6)
        self.assertEqual(servicios.estadisticas(self.b, self.p)['total'], 1)

    def test_evolucion_mensual_y_semanal(self):
        d = servicios.estadisticas(self.a, self.p)
        self.assertEqual([(e['clave'], e['total']) for e in d['evolucion']], [('2026-03', 5), ('2026-04', 1)])
        s = servicios.estadisticas(self.a, self.p, granularidad='week')
        self.assertEqual([e['clave'] for e in s['evolucion']], ['2026-03-02', '2026-04-06'])

    def test_granularidad_automatica_y_limites_de_tramo(self):
        corto = servicios.estadisticas(self.a, per.Periodo('range', date(2026, 3, 1), date(2026, 3, 31), 'm'), granularidad='auto')
        self.assertEqual(corto['granularidad'], 'week')
        self.assertEqual(corto['evolucion'][0]['desde'], date(2026, 3, 2))
        self.assertEqual(corto['evolucion'][0]['hasta'], date(2026, 3, 8))
        self.jornada(self.emp, date(2022, 5, 3), hecho='Informe antiguo')
        largo = servicios.estadisticas(self.a, per.Periodo('range', date(2021, 1, 1), date(2026, 4, 30), 'l'), granularidad='auto')
        self.assertEqual(largo['granularidad'], 'quarter')        # amplitud real de los datos: 2022 → 2026
        self.assertEqual([e['clave'] for e in largo['evolucion']], ['2022-T2', '2026-T1', '2026-T2'])
        self.assertEqual(largo['evolucion'][1]['hasta'], date(2026, 3, 31))
        anual = servicios.estadisticas(self.a, self.p, granularidad='year')
        self.assertEqual([(e['clave'], e['total']) for e in anual['evolucion']], [('2026', 6)])
        self.assertEqual(servicios.estadisticas(self.a, self.p, granularidad='raro')['granularidad'], 'month')

    def test_una_sola_lectura_de_items_para_totales_personas_roles_y_evolucion(self):
        with CaptureQueriesContext(connection) as ctx:
            servicios.estadisticas(self.a, self.p, membresia_id=self.emp.membresias.get().pk)
        lecturas = [q for q in ctx.captured_queries if 'jor_actividades_itemactividad' in q['sql'] and 'rol_id' in q['sql'].split('FROM')[0]]
        self.assertEqual(len(lecturas), 1)

    def test_kpis_derivados_y_variacion_vs_periodo_anterior(self):
        d = servicios.estadisticas(self.a, self.p)
        self.assertEqual((d['promedio_por_reporte'], d['dias_con_datos']), (2.0, 3))
        self.assertIsNotNone(d['total_anterior'])
        abril = servicios.estadisticas(self.a, per.Periodo('month', date(2026, 4, 1), date(2026, 4, 30), 'abr'))
        self.assertEqual((abril['total'], abril['total_anterior'], abril['variacion']), (1, 5, -80))
        self.assertIsNone(servicios.estadisticas(self.a, per.Periodo('all', None, None, 'todo'))['variacion'])

    def test_filtro_por_cargo(self):
        self.jornada(self.dir, date(2026, 3, 4), hecho='Informe de avance')
        cargo = self.dir.membresias.get().rol
        d = servicios.estadisticas(self.a, self.p, cargo_id=cargo.pk)
        self.assertEqual(d['total'], 1)
        self.assertEqual([r['rol'] for r in d['roles']], [cargo.nombre])

    def test_etiquetas_y_niveles_traen_desglose_por_categoria(self):
        ub = actividades.resolver_etiqueta(self.a, 'ubicacion', 'Planta Norte')
        for it in ItemActividad.objects.filter(empresa=self.a, tipo='hecho'):
            it.etiquetas.add(ub)
        d = servicios.estadisticas(self.a, self.p)
        e = d['ubicaciones'][0]
        self.assertEqual(sum(e['por_cat'].values()), e['n'])
        self.assertEqual(e['por_cat']['reuniones'], 3)
        r = d['roles'][0]
        self.assertAlmostEqual(sum(r['pct_cat']), 100, delta=0.5)
        self.assertEqual((d['total_global'], d['por_cat_global']['reuniones']), (6, 3))
        self.assertTrue(r['prom_reportes'] and r['prom_por_reporte'])

    def test_horas_por_proyecto_se_redondean_a_horas_enteras(self):
        proy = self.proy
        Jornada.objects.filter(perfil=self.perfil(self.emp), inicio__date=date(2026, 3, 2)).update(proyecto=proy, duracion_min=89)
        por = {r['nombre']: r for r in servicios.estadisticas(self.a, self.p)['horas_proyecto']}
        self.assertEqual((por['Torre 1']['horas'], por['Torre 1']['horas_enteras']), ('01:29', 1))
        Jornada.objects.filter(perfil=self.perfil(self.emp), inicio__date=date(2026, 3, 2)).update(duracion_min=90)
        por = {r['nombre']: r for r in servicios.estadisticas(self.a, self.p)['horas_proyecto']}
        self.assertEqual(por['Torre 1']['horas_enteras'], 2)                       # 1 h 30 min sube

    def test_horas_por_proyecto_respeta_el_nivel_de_acceso(self):
        Jornada.objects.filter(perfil=self.perfil(self.emp), inicio__date=date(2026, 3, 2)).update(duracion_min=120)
        self.assertTrue(servicios.estadisticas(self.a, self.p, rol_base='MIEMBRO')['horas_proyecto'])
        self.assertEqual(servicios.estadisticas(self.a, self.p, rol_base='COORDINADOR')['horas_proyecto'], [])

    def test_etiquetas_se_agrupan_en_la_canonica_y_ignoradas_no_cuentan(self):
        a = actividades.resolver_etiqueta(self.a, 'proyecto', 'Torre A')
        b = actividades.resolver_etiqueta(self.a, 'proyecto', 'Torre Alfa')
        z = actividades.resolver_etiqueta(self.a, 'proyecto', 'Basura')
        actividades.fusionar(b, a)
        items = list(ItemActividad.objects.filter(empresa=self.a).order_by('id'))
        items[0].etiquetas.add(a)
        items[1].etiquetas.add(b)
        items[2].etiquetas.add(b)
        items[3].etiquetas.add(z)
        z.ignorada = True
        z.save()
        d = servicios.estadisticas(self.a, self.p)
        self.assertEqual([(e['nombre'], e['n']) for e in d['proyectos']], [('Torre A', 3)])

    def test_horas_por_proyecto(self):
        proy = self.proy
        Jornada.objects.filter(perfil=self.perfil(self.emp), inicio__date=date(2026, 3, 2)).update(proyecto=proy, duracion_min=120)
        d = servicios.estadisticas(self.a, self.p)
        por = {r['nombre']: r for r in d['horas_proyecto']}
        self.assertEqual((por['Torre 1']['horas'], por['Torre 1']['jornadas']), ('02:00', 1))
        self.assertIn('Sin proyecto', por)

    def test_categoria_borrada_con_items_sigue_apareciendo(self):
        from jor_actividades.models import CategoriaActividad
        CategoriaActividad.objects.filter(empresa=self.a, codigo='riesgos').delete()
        ItemActividad.objects.filter(empresa=self.a).update(categoria='riesgos')
        d = servicios.estadisticas(self.a, self.p)
        self.assertEqual(d['total'], 6)
        self.assertEqual({c['codigo']: c['n'] for c in d['categorias']}['riesgos'], 6)

    def test_sin_datos(self):
        d = servicios.estadisticas(self.b, self.p)
        self.assertEqual((d['total'], d['personas'], d['proyectos']), (0, [], []))


class ExcelTests(DatosBase):
    def test_seguro_neutraliza_formulas(self):
        for peligro in ('=CMD()', '+1', '-1', '@x'):
            self.assertEqual(excel.seguro(peligro), "'" + peligro)
        self.assertEqual(excel.seguro('Normal'), 'Normal')
        self.assertEqual(excel.seguro(5), 5)

    def test_asistencia_xlsx_una_hoja_por_persona_sin_formulas(self):
        self.jornada(self.emp, date(2026, 3, 2))
        self.emp.first_name = '=HYPERLINK("http://malo")'          # un nombre malicioso no debe ejecutarse en Excel
        self.emp.save()
        p = self.periodo(date(2026, 3, 2), date(2026, 3, 3))
        datos = servicios.asistencia(self.a, p)
        wb = load_workbook(BytesIO(excel.asistencia_xlsx(datos, p, self.a)))
        self.assertEqual(wb.sheetnames[0], 'Resumen')
        self.assertEqual(len(wb.sheetnames), 1 + len(datos))
        celdas = [c.value for hoja in wb for fila in hoja.iter_rows() for c in fila if isinstance(c.value, str)]
        self.assertFalse([v for v in celdas if v.startswith('=')])
        self.assertTrue(any(v.startswith("'=HYPERLINK") for v in celdas))

    def test_nombres_de_hoja_repetidos_o_invalidos(self):
        usados = set()
        nombres = [excel._nombre_hoja(n, usados) for n in ('Ana/Pérez', 'Ana/Pérez', 'x' * 60, '[]')]
        self.assertEqual(len(set(n.lower() for n in nombres)), 4)
        self.assertTrue(all(len(n) <= 31 and not set(n) & set('\\/*?:[]') for n in nombres))

    def test_encabezados_de_categoria_neutralizan_formulas(self):
        from jor_actividades.models import CategoriaActividad
        actividades.categorias(self.a)                       # siembra perezosa de las categorías
        CategoriaActividad.objects.filter(empresa=self.a, codigo='otros').update(etiqueta='=HYPERLINK("http://malo")')
        self.jornada(self.emp, date(2026, 3, 2), hecho='Reunión con cliente')
        p = self.periodo(date(2026, 3, 1), date(2026, 3, 31))
        wb = load_workbook(BytesIO(excel.estadisticas_xlsx(servicios.estadisticas(self.a, p), self.a)))
        celdas = [c.value for hoja in wb for fila in hoja.iter_rows() for c in fila if isinstance(c.value, str)]
        self.assertFalse([v for v in celdas if v.startswith('=')])
        self.assertTrue(any(v.startswith("'=HYPERLINK") for v in celdas))

    def test_estadisticas_xlsx(self):
        self.jornada(self.emp, date(2026, 3, 2), hecho='Reunión con cliente')
        p = self.periodo(date(2026, 3, 1), date(2026, 3, 31))
        wb = load_workbook(BytesIO(excel.estadisticas_xlsx(servicios.estadisticas(self.a, p), self.a)))
        self.assertEqual(wb.sheetnames, ['Categorías', 'Por persona', 'Proyectos', 'Sedes', 'Entregables', 'Horas por proyecto'])


class VistasTests(DatosBase):
    def setUp(self):
        super().setUp()
        self.hoy = timezone.localdate()
        self.jornada(self.emp, self.hoy, hecho='Reunión con cliente')

    def test_permisos(self):
        for ruta, permitidos, negados in (
                ('asistencia/', (self.pmo,), (self.dir, self.emp, self.patro, self.vis)),   # dir: Coordinador acotado
                ('estadisticas/', (self.pmo, self.dir), (self.emp, self.patro, self.vis)),   # Jornadas no tiene observadores
                ('asistencia/excel/', (self.pmo,), (self.emp, self.vis, self.patro)),
                ('estadisticas/excel/', (self.pmo,), (self.emp, self.vis, self.patro))):
            for u in permitidos:
                self.assertEqual(self.ir(u, ruta).status_code, 200, (ruta, u))
            for u in negados:
                self.assertEqual(self.ir(u, ruta).status_code, 403, (ruta, u))

    def test_aislamiento_de_empresa(self):
        self.jornada(self.ajeno, self.hoy, hecho='Reunión secreta', empresa=self.b)
        html = self.ir(self.pmo, 'estadisticas/').content.decode()
        self.assertNotIn('Ajeno', html)
        self.assertIn('1</strong> actividades', html)

    def test_pagina_de_asistencia_muestra_las_horas(self):
        r = self.ir(self.pmo, f'asistencia/?persona={self.emp.membresias.get().pk}')
        self.assertContains(r, '08:00 h')
        self.assertContains(r, str(self.emp))

    def test_barra_de_periodo_muestra_solo_el_modo_activo(self):
        mes = self.ir(self.pmo, 'asistencia/?mode=month&year=2026&month=3')
        self.assertContains(mes, 'name="month"')
        self.assertNotContains(mes, 'name="from"')
        self.assertContains(mes, 'Horas netas')
        self.assertEqual(mes.context['resumen']['personas'], len(mes.context['personas']))
        rango = self.ir(self.pmo, 'asistencia/?mode=range&from=2026-03-01&to=2026-03-05')
        self.assertContains(rango, 'name="from"')
        self.assertNotContains(rango, 'name="month"')

    def test_estadisticas_con_filtros_raros_no_rompen(self):
        for q in ('?mode=basura', '?mode=all&tipo=planificado', '?mode=last&gran=week', '?rol=XX&persona=abc',
                  '?mode=range&from=2026-01-01&to=nada', '?persona=999999', '?year=0&month=99'):
            self.assertEqual(self.ir(self.pmo, 'estadisticas/' + q).status_code, 200, q)
            self.assertEqual(self.ir(self.pmo, 'asistencia/' + q).status_code, 200, q)

    def test_descargas(self):
        r = self.ir(self.pmo, 'asistencia/excel/')
        self.assertEqual(r['Content-Type'], excel_tipo := 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('attachment; filename="asistencia-tekon-', r['Content-Disposition'])
        load_workbook(BytesIO(r.content))
        r = self.ir(self.pmo, 'estadisticas/excel/')
        self.assertEqual(r['Content-Type'], excel_tipo)
        load_workbook(BytesIO(r.content))

    def test_estadisticas_todo_dibuja_grafico_con_enlaces_y_persona_filtra(self):
        self.jornada(self.emp, self.hoy - timedelta(days=40), hecho='Informe semanal')
        r = self.ir(self.pmo, 'estadisticas/?mode=all')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['grafico']['barras'])
        self.assertTrue(all(b['url'].startswith('?') for b in r.context['grafico']['barras']))
        mid = self.emp.membresias.get().pk
        r = self.ir(self.pmo, f'estadisticas/?mode=all&persona={mid}')
        self.assertContains(r, 'Quitar filtro')
        self.assertIsNotNone(r.context['comparacion'])

    def test_sedes_tienen_colores_distintos_entre_si(self):
        from .views import COLORES_SEDE, PALETA_SEDES, _color_sede
        todos = list(PALETA_SEDES) + [c for _, c in COLORES_SEDE]
        self.assertEqual(len(set(todos)), len(todos))
        self.assertEqual(len({_color_sede('x', i) for i in range(len(PALETA_SEDES))}), len(PALETA_SEDES))
        self.assertEqual(_color_sede('Sede Santa Cruz', 5), '#15803d')
        self.assertEqual(_color_sede('LA PAZ', 0), '#b3354f')
        self.assertEqual(_color_sede('Cochabamba', 3), '#38bdf8')
        self.assertTrue(_color_sede('Planta Norte', 0).startswith('#'))
        ub = actividades.resolver_etiqueta(self.a, 'ubicacion', 'Planta Norte')
        ItemActividad.objects.filter(empresa=self.a).first().etiquetas.add(ub)
        r = self.ir(self.pmo, 'estadisticas/?mode=all')
        filas = dict(r.context['tops'])['Sedes']
        self.assertEqual(filas[0]['color'], _color_sede('Planta Norte', 0))
        self.assertNotIn('color', dict(r.context['tops'])['Entregables'][0] if dict(r.context['tops'])['Entregables'] else {})

    def test_estadisticas_paridad_skylog_secciones_y_sin_estilos_inline(self):
        r = self.ir(self.pmo, 'estadisticas/?mode=all')
        html = r.content.decode()
        for texto in ('Distribución por categoría', 'Comparación por cargo', 'Métricas por persona',
                      'Desglose por categoría y persona', 'data-imprimir'):
            self.assertIn(texto, html)
        self.assertNotIn(' style="', html)                       # la CSP no admite estilos inline
        self.assertEqual(sum(t['n'] for t in r.context['donut']), r.context['d']['total'])
        self.assertTrue(r.context['matriz']['columnas'] and r.context['matriz']['filas'])
        self.assertEqual(r.context['matriz']['referencias'], [])  # las referencias por nivel solo con una persona

    def test_vista_lineas_y_referencias_con_persona(self):
        lin = self.ir(self.pmo, 'estadisticas/?mode=all&evo=lineas')
        self.assertTrue(lin.context['grafico']['lineas'])
        mid = self.emp.membresias.get().pk
        r = self.ir(self.pmo, f'estadisticas/?mode=all&persona={mid}')
        self.assertTrue(r.context['matriz']['referencias'])
        self.assertTrue(r.context['cmp_categorias'])
        self.assertContains(r, 'Prom. ')

    def test_cargo_limita_la_lista_de_personas_y_agrupa_los_promedios(self):
        cargo = self.dir.membresias.get().rol
        r = self.ir(self.pmo, f'estadisticas/?mode=all&cargo={cargo.pk}')
        self.assertTrue(all(m.rol_id == cargo.pk for m in r.context['miembros']))
        d = self.ir(self.pmo, 'estadisticas/?mode=all').context['d']
        self.assertEqual({x['rol'] for x in d['roles']}, {p['rol'] for p in d['personas']})   # nombres de cargo, no de nivel

    def test_resultados_ordenados_de_mayor_a_menor(self):
        c = self.ir(self.pmo, 'estadisticas/?mode=all').context
        for lista in ([t['n'] for t in c['donut']], [f['count'] for f in c['categorias_barras']],
                      [r['total'] for r in c['roles_res']], [p['total'] for p in c['personas']],
                      [f['count'] for _, filas in c['tops'] for f in filas][:1]):
            self.assertEqual(lista, sorted(lista, reverse=True))
        for _, filas in c['tops']:
            self.assertEqual([f['count'] for f in filas], sorted((f['count'] for f in filas), reverse=True))
        totales = [sum(fila['valores']) for fila in [{'valores': [f['total']]} for f in c['matriz']['filas']]]
        self.assertEqual(totales, sorted(totales, reverse=True))
        cols = [c['d']['categorias'] for _ in [0]][0]
        orden = {x['etiqueta']: x['n'] for x in cols}
        n_cols = [orden[x['etiqueta']] for x in c['matriz']['columnas']]
        self.assertEqual(n_cols, sorted(n_cols, reverse=True))

    def test_sin_proyecto_va_como_nota_y_no_como_barra(self):
        Jornada.objects.filter(perfil=self.perfil(self.emp)).update(duracion_min=120)
        r = self.ir(self.pmo, 'estadisticas/?mode=all')
        self.assertNotIn('Sin proyecto', [f['label'] for f in r.context['horas_proyecto']])
        self.assertTrue(r.context['horas_sin_proyecto'])
        self.assertContains(r, 'sin proyecto asignado')

    def test_estadisticas_vacias_muestran_mensaje(self):
        self.assertContains(self.ir(self.pmo, 'estadisticas/?mode=range&from=2020-01-01&to=2020-01-02'), 'No hay actividades')
