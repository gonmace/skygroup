from datetime import date
from decimal import Decimal

from cuentas.models import RolEmpresa, RolPermiso, User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro
from reg_construccion.models import RegConstruccion
from reg_fotos.tests import imagen, subida
from reg_actividades.tests import MotorBase
from proyectos.models import Proyecto

from . import servicios, widgets
from .models import DatoPaso, Paso, PasoAsignado, PasoWidget, Plantilla
from .widgets.base import Contexto
from .widgets.tabla_avance import calcular_serie, recalcular_avance, serie_proyecto

SLUG = 'tabla_avance_widget'
PLANTILLA = {'nombre': 'Torre', 'partidas': [{'nombre': 'Civil', 'incidencia': 40}, {'nombre': 'Montaje', 'incidencia': 60}]}


def partida(id, nombre, inc, actual=0):
    return {'id': id, 'nombre': nombre, 'incidencia': inc, 'actual': actual}


class CalculoTests(MotorBase):
    def test_acumula_visita_a_visita_con_tope_de_100(self):
        s = calcular_serie([
            [partida('a', 'Civil', 40, 50), partida('b', 'Montaje', 60, 0)],
            [partida('a', 'Civil', 40, 30), partida('b', 'Montaje', 60, 25)],
            [partida('a', 'Civil', 40, 50), partida('b', 'Montaje', 60, 25)],
        ])
        self.assertEqual([r['total'] for r in s], [Decimal('20'), Decimal('0.4') * 80 + Decimal('0.6') * 25, Decimal('40') + Decimal('0.6') * 50])
        ultima = {f['id']: f for f in s[2]['filas']}
        self.assertEqual((ultima['a']['anterior'], ultima['a']['acumulada']), (Decimal('80'), Decimal('100')))   # 80+50 → tope 100
        self.assertEqual(ultima['b']['acumulada'], Decimal('50'))

    def test_una_visita_sin_datos_hereda_la_estructura_con_actual_cero(self):
        s = calcular_serie([[partida('a', 'Civil', 100, 30)], [], [partida('a', 'Civil', 100, 20)]])
        self.assertEqual([r['total'] for r in s], [Decimal('30'), Decimal('30'), Decimal('50')])
        self.assertEqual(s[1]['filas'][0]['actual'], Decimal('0'))

    def test_un_item_nuevo_empieza_desde_cero(self):
        s = calcular_serie([[partida('a', 'A', 50, 100)], [partida('a', 'A', 50, 0), partida('b', 'B', 50, 40)]])
        self.assertEqual(s[1]['total'], Decimal('50') + Decimal('20'))

    def test_valores_raros_no_rompen(self):
        s = calcular_serie([[{'id': 'a', 'nombre': 'A', 'incidencia': 'x', 'actual': None}]])
        self.assertEqual(s[0]['total'], Decimal('0'))

    def test_serie_del_proyecto_ordena_por_fecha_y_aisla_proyectos_y_borrados(self):
        mk = lambda p, f, **kw: RegConstruccion.objects.create(empresa=self.a, proyecto=p, user=self.ito1, fecha=f, **kw)
        v2, v1 = mk(self.t1, date(2026, 4, 1)), mk(self.t1, date(2026, 3, 1))
        otro = mk(self.t2, date(2026, 3, 15))
        borrada = mk(self.t1, date(2026, 3, 10))
        borrada.soft_delete()
        ids = [i for i, _ in serie_proyecto(v2, 'obra_avance')]
        self.assertEqual(ids, [v1.pk, v2.pk])               # sin la borrada ni la de otro proyecto
        self.assertEqual([i for i, _ in serie_proyecto(v1, 'obra_avance')], [v1.pk])      # «hasta» el registro

    def test_validar_config_exige_que_cada_plantilla_sume_100(self):
        w = widgets.obtener(SLUG)
        self.assertEqual(w.validar_config({'plantillas': [PLANTILLA]}), [])
        self.assertEqual(w.validar_config({}), [])
        malas = [{'plantillas': 'x'}, {'plantillas': [{'nombre': 'Mala', 'partidas': [{'nombre': 'a', 'incidencia': 50}]}]},
                 {'plantillas': [{'partidas': [{'nombre': 'a', 'incidencia': 100}]}]},
                 {'plantillas': [{'nombre': 'Vacía', 'partidas': []}]},
                 {'plantillas': [PLANTILLA, PLANTILLA]}]
        for c in malas:
            self.assertTrue(w.validar_config(c), c)


class AvanceBase(MotorBase):
    def setUp(self):
        super().setUp()
        # Plantilla de construcción con el paso de avance (tabla + fotos + comentario) y un paso opcional.
        self.pl = Plantilla.objects.create(empresa=self.a, nombre='Obra', tipo_registro='construccion')
        self.avance = Paso.objects.create(empresa=self.a, nombre='obra_avance', titulo='Avance')
        PasoWidget.objects.create(paso=self.avance, widget_slug=SLUG, orden=1, config={'plantillas': [PLANTILLA]})
        PasoWidget.objects.create(paso=self.avance, widget_slug='camera_widget', orden=2, config={'foto_min': 2})
        PasoWidget.objects.create(paso=self.avance, widget_slug='comentario_widget', orden=3, config={})
        self.libro = Paso.objects.create(empresa=self.a, nombre='obra_libro', titulo='Libro')
        PasoWidget.objects.create(paso=self.libro, widget_slug='camera_libro_widget', orden=1, config={'foto_min': 0, 'opcional': True})
        PasoAsignado.objects.create(plantilla=self.pl, paso=self.avance, orden=1)
        PasoAsignado.objects.create(plantilla=self.pl, paso=self.libro, orden=2)

    def crear_visita(self, fecha, user=None, proyecto=None):
        return RegConstruccion.objects.create(empresa=self.a, proyecto=proyecto or self.t1, user=user or self.ito1, fecha=fecha)

    def post(self, user, v, datos, paso='obra_avance'):
        self.client.force_login(user)
        return self.client.post(f'/tekon/registros/construccion/{v.pk}/paso/{paso}/guardar/', datos)

    def tabla(self, v):
        d = DatoPaso.objects.get(object_id=v.pk, paso_nombre='obra_avance')
        return d.datos[SLUG]

    def filas(self, ids, nombres, incs, actuales):
        return {f'{SLUG}__id': ids, f'{SLUG}__nombre': nombres, f'{SLUG}__incidencia': incs, f'{SLUG}__actual': actuales}

    def definir(self, v, user=None):
        """El PMO aplica la plantilla; devuelve los ids de los ítems."""
        self.post(user or self.pmo, v, {f'{SLUG}__plantilla': 'Torre', f'{SLUG}__aplicar': '1'})
        return [p['id'] for p in self.tabla(v)['partidas']]


class ReglasPorRolTests(AvanceBase):
    def test_el_pmo_aplica_la_plantilla_de_items(self):
        v = self.crear_visita(date(2026, 3, 1))
        r = self.post(self.pmo, v, {f'{SLUG}__plantilla': 'Torre', f'{SLUG}__aplicar': '1'})
        self.assertEqual(r.status_code, 302)
        t = self.tabla(v)
        self.assertEqual(t['plantilla'], 'Torre')
        self.assertEqual([(p['nombre'], p['incidencia'], p['actual']) for p in t['partidas']], [('Civil', 40.0, 0.0), ('Montaje', 60.0, 0.0)])
        self.assertEqual(len({p['id'] for p in t['partidas']}), 2)

    def test_aplicar_una_plantilla_inexistente_no_cambia_nada(self):
        v = self.crear_visita(date(2026, 3, 1))
        r = self.post(self.pmo, v, {f'{SLUG}__plantilla': 'Inventada', f'{SLUG}__aplicar': '1'})
        self.assertEqual(r.status_code, 422)
        self.assertFalse(DatoPaso.objects.filter(tiene_datos=True).exists())

    def test_el_ito_no_puede_aplicar_plantillas_ni_cambiar_la_estructura(self):
        v = self.crear_visita(date(2026, 3, 1))
        ids = self.definir(v)
        self.post(self.ito1, v, {f'{SLUG}__plantilla': 'Torre', f'{SLUG}__aplicar': '1'})        # ignorado: no es su permiso
        self.assertEqual([p['id'] for p in self.tabla(v)['partidas']], ids)
        # Intenta renombrar, cambiar incidencias, agregar un ítem inventado y cargar el %.
        self.post(self.ito1, v, self.filas(ids + ['inventado'], ['HACK', 'HACK', 'Nuevo'], ['1', '1', '98'], ['10', '20', '99']))
        partidas = self.tabla(v)['partidas']
        self.assertEqual([(p['nombre'], p['incidencia'], p['actual']) for p in partidas], [('Civil', 40.0, 10.0), ('Montaje', 60.0, 20.0)])
        self.assertEqual(self.tabla(v)['plantilla'], 'Torre')

    def test_el_pmo_define_y_carga_todo_en_un_solo_envio(self):
        v = self.crear_visita(date(2026, 3, 1))
        self.post(self.pmo, v, self.filas(['', ''], ['Obra civil', 'Montaje'], ['30', '70'], ['50', '10']) | {f'{SLUG}__plantilla': ''})
        self.assertEqual([(p['nombre'], p['incidencia'], p['actual']) for p in self.tabla(v)['partidas']],
                         [('Obra civil', 30.0, 50.0), ('Montaje', 70.0, 10.0)])

    def test_quien_solo_define_la_estructura_conserva_el_porcentaje_ya_cargado(self):
        v = self.crear_visita(date(2026, 3, 1))
        ids = self.definir(v)
        self.post(self.ito1, v, self.filas(ids, ['x', 'x'], ['0', '0'], ['25', '30']))
        w = widgets.obtener(SLUG)
        rol = RolEmpresa.objects.create(empresa=self.a, nombre='Planificador', rol_base=RolBase.MIEMBRO)
        RolPermiso.objects.create(rol_empresa=rol, capacidad='reg.items_obra', habilitado=True)
        RolPermiso.objects.create(rol_empresa=rol, capacidad='reg.cargar_datos', habilitado=False)
        u = User.objects.create_user('plan@x.cl', 'x')
        agregar_miembro(u, self.a, rol)
        c = Contexto(registro=v, paso=self.avance, clave='construccion', user=User.objects.get(pk=u.pk), puede_escribir=True,
                     extra={'previos': self.tabla(v)})
        datos, errs = w.leer(self.filas(ids, ['Civil+', 'Montaje'], ['45', '55'], ['99', '99']) | {f'{SLUG}__plantilla': 'Torre'}, {}, {}, c)
        self.assertEqual(errs, [])
        self.assertEqual([(p['nombre'], p['incidencia'], p['actual']) for p in datos['partidas']], [('Civil+', 45.0, 25.0), ('Montaje', 55.0, 30.0)])

    def test_sin_ningun_permiso_no_se_modifica(self):
        v = self.crear_visita(date(2026, 3, 1))
        w = widgets.obtener(SLUG)
        c = Contexto(registro=v, paso=self.avance, clave='construccion', user=self.visita, puede_escribir=True, extra={'previos': {'partidas': []}})
        datos, errs = w.leer(self.filas(['a'], ['X'], ['100'], ['100']), {}, {}, c)
        self.assertTrue(errs)

    def test_visita_y_patrocinador_no_guardan(self):
        v = self.crear_visita(date(2026, 3, 1))
        for u in (self.visita, self.patro):
            self.assertEqual(self.post(u, v, {f'{SLUG}__plantilla': 'Torre', f'{SLUG}__aplicar': '1'}).status_code, 403)
        self.assertFalse(DatoPaso.objects.exists())


class ValidacionTests(AvanceBase):
    def setUp(self):
        super().setUp()
        self.v = self.crear_visita(date(2026, 3, 1))
        self.ids = self.definir(self.v)

    def test_porcentajes_fuera_de_rango_o_no_numericos_no_guardan_y_repintan(self):
        for actuales in (['150', '10'], ['-5', '10'], ['abc', '10']):
            r = self.post(self.pmo, self.v, self.filas(self.ids, ['Civil', 'Montaje'], ['40', '60'], actuales))
            self.assertEqual(r.status_code, 422, actuales)
        self.assertEqual([p['actual'] for p in self.tabla(self.v)['partidas']], [0.0, 0.0])       # nada cambió
        self.assertContains(r, 'value="abc"', status_code=422)                                      # lo escrito se conserva

    def test_ignora_filas_en_blanco_pero_exige_nombre_si_hay_numeros(self):
        self.post(self.pmo, self.v, self.filas(self.ids + [''], ['Civil', 'Montaje', ''], ['40', '60', ''], ['10', '10', '']))
        self.assertEqual(len(self.tabla(self.v)['partidas']), 2)
        r = self.post(self.pmo, self.v, self.filas(self.ids + [''], ['Civil', 'Montaje', ''], ['40', '60', '5'], ['10', '10', '']))
        self.assertEqual(r.status_code, 422)

    def test_ids_repetidos_y_nombre_demasiado_largo(self):
        r = self.post(self.pmo, self.v, self.filas(['x', 'x'], ['A', 'B'], ['50', '50'], ['0', '0']))
        self.assertEqual(r.status_code, 422)
        r = self.post(self.pmo, self.v, self.filas(['x'], ['n' * 121], ['100'], ['0']))
        self.assertEqual(r.status_code, 422)

    def test_coma_decimal(self):
        self.post(self.pmo, self.v, self.filas(self.ids, ['Civil', 'Montaje'], ['40', '60'], ['12,5', '0']))
        self.assertEqual(self.tabla(self.v)['partidas'][0]['actual'], 12.5)

    def test_maximo_de_items(self):
        n = 101
        r = self.post(self.pmo, self.v, self.filas([f'i{i}' for i in range(n)], [f'it{i}' for i in range(n)], ['1'] * n, ['0'] * n))
        self.assertEqual(r.status_code, 422)

    def test_la_pagina_muestra_los_controles_segun_el_rol(self):
        self.client.force_login(self.pmo)
        html = self.client.get(f'/tekon/registros/construccion/{self.v.pk}/paso/obra_avance/').content.decode()
        for texto in ('Aplicar plantilla', 'Agregar ítem', 'data-quitar-fila'):
            self.assertIn(texto, html)
        self.client.force_login(self.ito1)
        html = self.client.get(f'/tekon/registros/construccion/{self.v.pk}/paso/obra_avance/').content.decode()
        for texto in ('Aplicar plantilla', 'Agregar ítem', 'data-quitar-fila'):
            self.assertNotIn(texto, html)
        self.assertIn('readonly', html)                    # nombre e incidencia no editables para el ITO
        self.assertIn('Avance total', html)


class AcumuladoYSenalesTests(AvanceBase):
    def setUp(self):
        super().setUp()
        self.v1 = self.crear_visita(date(2026, 3, 1))
        self.ids = self.definir(self.v1)

    def carga(self, v, civil, montaje, user=None):
        self.post(user or self.ito1, v, self.filas(self.ids, ['', ''], ['', ''], [str(civil), str(montaje)]))

    def pct(self, v):
        return RegConstruccion.objects.get(pk=v.pk).avance_pct

    def test_avance_pct_acumulado_por_visita(self):
        self.carga(self.v1, 50, 0)
        self.assertEqual(self.pct(self.v1), Decimal('20.00'))
        v2 = self.crear_visita(date(2026, 4, 1))
        self.carga(v2, 30, 50)                       # la estructura se hereda de la primera visita
        self.assertEqual(self.pct(v2), Decimal('0.4') * 80 + Decimal('0.6') * 50)
        self.assertEqual(self.pct(self.v1), Decimal('20.00'))

    def test_la_segunda_visita_muestra_lo_anterior(self):
        self.carga(self.v1, 50, 20)
        v2 = self.crear_visita(date(2026, 4, 1))
        self.client.force_login(self.ito1)
        filas = self.client.get(f'/tekon/registros/construccion/{v2.pk}/paso/obra_avance/').context['bloques'][0]['filas']
        self.assertEqual([(f['nombre'], f['anterior'], f['actual']) for f in filas], [('Civil', 50.0, 0.0), ('Montaje', 20.0, 0.0)])

    def test_editar_una_visita_antigua_se_propaga_a_las_siguientes(self):
        v2 = self.crear_visita(date(2026, 4, 1))
        self.carga(self.v1, 20, 0)
        self.carga(v2, 30, 0)
        self.assertEqual(self.pct(v2), Decimal('20.00'))                       # 50% de 40
        self.carga(self.v1, 60, 0)
        self.assertEqual(self.pct(v2), Decimal('36.00'))                       # 90% de 40
        self.carga(self.v1, 90, 0)
        self.assertEqual(self.pct(v2), Decimal('40.00'))                       # tope 100% de 40

    def test_una_visita_intermedia_reordena_el_acumulado(self):
        v3 = self.crear_visita(date(2026, 5, 1))
        self.carga(self.v1, 10, 0)
        self.carga(v3, 10, 0)
        self.assertEqual(self.pct(v3), Decimal('8.00'))
        v2 = self.crear_visita(date(2026, 4, 1))                                          # se crea después pero va en medio
        self.carga(v2, 10, 0)
        self.assertEqual(self.pct(v3), Decimal('12.00'))

    def test_borrar_o_eliminar_una_visita_recalcula_las_demas(self):
        v2 = self.crear_visita(date(2026, 4, 1))
        self.carga(self.v1, 50, 0)
        self.carga(v2, 25, 0)
        self.assertEqual(self.pct(v2), Decimal('30.00'))
        self.v1.soft_delete()
        self.assertEqual(self.pct(v2), Decimal('10.00'))                         # sin la primera: 25% de 40
        RegConstruccion.objects.get(pk=self.v1.pk).delete()
        self.assertEqual(DatoPaso.objects.filter(object_id=self.v1.pk, paso_nombre='obra_avance').count(), 0)

    def test_otros_proyectos_no_se_afectan(self):
        otro = self.crear_visita(date(2026, 3, 1), proyecto=self.t2)
        self.carga(self.v1, 100, 100)
        self.assertEqual(self.pct(otro), Decimal('0'))
        self.assertEqual(self.pct(self.v1), Decimal('100.00'))

    def test_recalcular_avance_es_idempotente(self):
        self.carga(self.v1, 50, 0)
        recalcular_avance(RegConstruccion, self.t1.pk, self.a.pk, 'obra_avance')
        recalcular_avance(RegConstruccion, self.t1.pk, self.a.pk, 'obra_avance')
        self.assertEqual(self.pct(self.v1), Decimal('20.00'))
        recalcular_avance(RegConstruccion, None, self.a.pk, 'obra_avance')       # sin proyecto: no hace nada

    def test_la_lista_y_el_detalle_muestran_el_avance(self):
        self.carga(self.v1, 50, 0)
        self.client.force_login(self.pmo)
        self.assertContains(self.client.get('/tekon/registros/construccion/'), '20%')
        self.assertContains(self.client.get(f'/tekon/registros/construccion/{self.v1.pk}/'), 'Avance 20.0%')

    def test_completo_requiere_todos_los_elementos_obligatorios(self):
        flag = lambda: RegConstruccion.objects.get(pk=self.v1.pk).completo
        self.assertFalse(flag())
        self.carga(self.v1, 10, 0)
        self.post(self.ito1, self.v1, {f'{SLUG}__id': self.ids, f'{SLUG}__actual': ['10', '0'], 'comentario_widget__comentario': 'ok'})
        self.assertFalse(flag())                                                    # faltan las 2 fotos
        self.client.force_login(self.ito1)
        self.client.post(f'/tekon/registros/construccion/{self.v1.pk}/fotos/obra_avance/subir/', {'fotos': [subida()]})
        self.assertFalse(flag())
        self.client.post(f'/tekon/registros/construccion/{self.v1.pk}/fotos/obra_avance/subir/', {'fotos': [subida('b.jpg', imagen((1, 2, 3)))]})
        self.assertTrue(flag())                                                     # el libro de obras es opcional
        self.client.post(f'/tekon/registros/construccion/{self.v1.pk}/paso/obra_avance/guardar/', {'comentario_widget__comentario': ''})
        self.assertFalse(flag())                                                    # vaciar el comentario lo apaga
        self.client.force_login(self.pmo)
        self.assertContains(self.client.get('/tekon/registros/construccion/'), 'Avance')

    def test_la_fila_completa_se_resalta_en_la_lista(self):
        RegConstruccion.objects.filter(pk=self.v1.pk).update(completo=True)
        self.client.force_login(self.pmo)
        self.assertContains(self.client.get('/tekon/registros/construccion/'), 'row-concluido')
