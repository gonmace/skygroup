from datetime import date
from decimal import Decimal as D
from unittest import mock

import requests
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings

from apu_motor import calcular
from apu_motor.plantillas import BOLIVIA_ESTANDAR
from core import n8n
from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base

from . import editor
from .models import Insumo, ItemModelo, LineaComposicion, PerfilCalculo, PrecioInsumo, Tipo

AJUSTES = dict(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


@override_settings(APU_SOLO_ADMIN=False)
class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Tekon', slug='tekon', modulos=['apu'])
        cls.b = crear_empresa(nombre='Embol', slug='embol', modulos=['apu'])
        cls.coord = User.objects.create_user('coord@example.com', 'x')
        agregar_miembro(cls.coord, cls.a, rol_por_base(cls.a, RolBase.COORDINADOR))
        cls.obs = User.objects.create_user('obs@example.com', 'x')
        agregar_miembro(cls.obs, cls.a, rol_por_base(cls.a, RolBase.OBSERVADOR))
        cls.ajeno = User.objects.create_user('ajeno@example.com', 'x')
        agregar_miembro(cls.ajeno, cls.b, rol_por_base(cls.b, RolBase.COORDINADOR))

    def setUp(self):
        cache.clear()


class ModelosTests(Base):
    def insumo(self, codigo='CEM', empresa=None, tipo=Tipo.MATERIAL):
        return Insumo.objects.create(empresa=empresa or self.a, codigo=codigo, descripcion=codigo, unidad='kg', tipo=tipo)

    def item(self, codigo, empresa=None):
        return ItemModelo.objects.create(empresa=empresa or self.a, codigo=codigo, descripcion=codigo, unidad='m3')

    def test_codigo_unico_por_empresa_pero_repetible_entre_empresas(self):
        self.insumo('CEM')
        self.insumo('CEM', empresa=self.b)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.insumo('CEM')

    def test_precio_vigente_ultimo_en_region_con_respaldo_nacional(self):
        i = self.insumo()
        for region, fecha, precio in [('', date(2026, 1, 1), 10), ('La Paz', date(2026, 2, 1), 12),
                                      ('La Paz', date(2026, 6, 1), 15), ('', date(2026, 5, 1), 11)]:
            PrecioInsumo.objects.create(insumo=i, region=region, fecha=fecha, precio=precio, moneda='BOB')
        self.assertEqual(i.precio_vigente('La Paz', date(2026, 3, 1)).precio, 12)    # el último ≤ fecha
        self.assertEqual(i.precio_vigente('La Paz', date(2026, 7, 1)).precio, 15)
        self.assertEqual(i.precio_vigente('Cochabamba', date(2026, 7, 1)).precio, 11)  # respaldo nacional
        self.assertIsNone(i.precio_vigente('La Paz', date(2025, 1, 1)))               # nada anterior a la fecha

    def test_linea_exige_insumo_o_subitem(self):
        item = self.item('A')
        with self.assertRaises(IntegrityError), transaction.atomic():
            LineaComposicion.objects.create(item=item, cantidad=1)
        with self.assertRaises(ValidationError):
            LineaComposicion(item=item, insumo=self.insumo(), subitem=self.item('B'), cantidad=1).clean()

    def test_linea_no_mezcla_empresas(self):
        with self.assertRaisesMessage(ValidationError, 'otra empresa'):
            LineaComposicion(item=self.item('A'), insumo=self.insumo('X', empresa=self.b), cantidad=1).clean()

    def test_sub_analisis_sin_ciclos(self):
        a, b, c = self.item('A'), self.item('B'), self.item('C')
        LineaComposicion.objects.create(item=a, subitem=b, cantidad=1)
        LineaComposicion.objects.create(item=b, subitem=c, cantidad=1)
        for item, sub in [(a, a), (b, a), (c, a)]:                   # c→a cerraría el ciclo a→b→c→a
            with self.assertRaisesMessage(ValidationError, 'ciclo'):
                LineaComposicion(item=item, subitem=sub, cantidad=1).clean()
        LineaComposicion(item=a, subitem=c, cantidad=1).clean()      # a→c es válido (un rombo, no un ciclo)

    def test_plantillas_sembradas_y_calculables(self):
        nombres = set(PerfilCalculo.objects.filter(empresa=None).values_list('nombre', flat=True))
        self.assertEqual(nombres, {'Bolivia - estándar', 'Chile - estándar (por validar)'})
        for p in PerfilCalculo.objects.filter(empresa=None):
            p.full_clean()
            calcular(p.validado(), {'MAT': 100, 'MO': 50, 'EQ': 20})
        bolivia = PerfilCalculo.objects.get(nombre='Bolivia - estándar').validado()
        self.assertEqual(calcular(bolivia, {'MAT': 100, 'MO': 50, 'EQ': 20}).total, D('266.36'))

    def test_perfil_invalido_se_rechaza_con_mensaje(self):
        p = PerfilCalculo(empresa=self.a, nombre='Roto', moneda='BOB', datos={'lineas': []})
        with self.assertRaisesMessage(ValidationError, 'al menos una línea'):
            p.full_clean()

    def test_copiar_plantilla_no_choca_con_nombres(self):
        plantilla = PerfilCalculo.objects.get(nombre='Bolivia - estándar')
        c1, c2 = plantilla.copiar_a(self.a), plantilla.copiar_a(self.a)
        self.assertEqual((c1.nombre, c2.nombre), ('Bolivia - estándar', 'Bolivia - estándar (2)'))
        self.assertEqual(c1.empresa, self.a)


@override_settings(**AJUSTES)
class VistasTests(Base):
    def test_inicio_lista_plantillas_y_solo_perfiles_propios(self):
        plantilla = PerfilCalculo.objects.get(empresa=None, nombre='Bolivia - estándar')
        propio, ajeno = plantilla.copiar_a(self.a), plantilla.copiar_a(self.b)
        ajeno.nombre = 'Secreto de Embol'
        ajeno.save()
        self.client.force_login(self.coord)
        r = self.client.get('/tekon/apu/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(propio, r.context['perfiles'])
        self.assertNotIn(ajeno, r.context['perfiles'])
        self.assertEqual(len(r.context['perfiles']), 3)     # 2 plantillas + 1 propio
        self.assertNotContains(r, 'Secreto de Embol')

    def test_el_modulo_deja_de_ser_proximamente(self):
        from panel.menu import app_activa_codigo  # noqa: F401  (el menú se arma con registrar_item en ready())
        self.client.force_login(self.coord)
        estados = {m['codigo']: m['estado'] for m in self.client.get('/tekon/').context['lanzador_modulos']}
        self.assertEqual(estados['apu'], 'disponible')

    def test_requiere_sesion_modulo_activo_y_membresia(self):
        self.assertEqual(self.client.get('/tekon/apu/').status_code, 302)       # sin sesión → login
        self.client.force_login(self.ajeno)
        self.assertEqual(self.client.get('/tekon/apu/').status_code, 403)       # miembro de otra empresa
        self.a.modulos = ['tar']
        self.a.save()
        cache.clear()
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get('/tekon/apu/').status_code, 404)       # módulo no habilitado

    def test_copiar_requiere_capacidad_y_no_acepta_get(self):
        plantilla = PerfilCalculo.objects.get(nombre='Bolivia - estándar')
        url = f'/tekon/apu/perfiles/{plantilla.pk}/copiar/'
        self.client.force_login(self.obs)
        self.assertEqual(self.client.post(url).status_code, 403)                # el Observador solo ve
        self.assertEqual(PerfilCalculo.objects.filter(empresa=self.a).count(), 0)
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get(url).status_code, 405)
        copia = PerfilCalculo.objects.filter(empresa=self.a)
        r = self.client.post(url)
        self.assertEqual(copia.count(), 1)
        self.assertRedirects(r, f'/tekon/apu/perfiles/{copia.get().pk}/editar/')    # abre el editor sobre la copia

    def test_no_se_copia_el_perfil_de_otra_empresa(self):
        ajeno = PerfilCalculo.objects.get(nombre='Bolivia - estándar').copiar_a(self.b)
        self.client.force_login(self.coord)
        self.assertEqual(self.client.post(f'/tekon/apu/perfiles/{ajeno.pk}/copiar/').status_code, 404)


class N8nTests(SimpleTestCase):
    def respuesta(self, estado=200, texto='{"ok": true}'):
        r = mock.Mock(ok=estado < 400, status_code=estado, text=texto)
        r.json.side_effect = lambda: __import__('json').loads(texto)
        return r

    @override_settings(N8N_BASE_URL='http://n8n:5678/')
    def test_url_del_webhook(self):
        self.assertEqual(n8n.webhook_url('apu-coherencia'), 'http://n8n:5678/webhook/apu-coherencia')

    @override_settings(N8N_WEBHOOK_TOKEN='secreto', N8N_WEBHOOK_TOKEN_HEADER='X-T')
    def test_envia_el_token_en_la_cabecera(self):
        with mock.patch('core.n8n.requests.post', return_value=self.respuesta()) as post:
            self.assertEqual(n8n.llamar_webhook_seguro('http://x', {'a': 1}), {'ok': True})
        self.assertEqual(post.call_args.kwargs['headers']['X-T'], 'secreto')

    @override_settings(N8N_WEBHOOK_TOKEN='')
    def test_sin_token_no_hay_cabecera_y_respuesta_vacia_es_dict(self):
        with mock.patch('core.n8n.requests.post', return_value=self.respuesta(texto='  ')) as post:
            self.assertEqual(n8n.llamar_webhook_seguro('http://x', {}), {})
        self.assertEqual(list(post.call_args.kwargs['headers']), ['Content-Type'])

    def test_los_fallos_se_traducen_a_n8nerror_en_español(self):
        casos = [
            (dict(side_effect=requests.exceptions.Timeout()), 'tardó demasiado'),
            (dict(side_effect=requests.exceptions.ConnectionError()), 'No se pudo conectar'),
            (dict(return_value=self.respuesta(500, 'boom')), 'HTTP 500'),
            (dict(return_value=self.respuesta(200, 'no es json')), 'respuesta inválida'),
        ]
        for config, mensaje in casos:
            with self.subTest(mensaje), mock.patch('core.n8n.requests.post', **config):
                with self.assertRaisesMessage(n8n.N8NError, mensaje):
                    n8n.llamar_webhook_seguro('http://x', {})

    def test_desempaquetar(self):
        for crudo in ({'a': 1}, {'output': {'a': 1}}, [{'a': 1}], [{'output': {'a': 1}}]):
            self.assertEqual(n8n.desempaquetar(crudo), {'a': 1})
        for crudo in ([], 'texto', None, [None]):
            self.assertEqual(n8n.desempaquetar(crudo), {})


@override_settings(**AJUSTES)
class DetallePerfilTests(Base):
    def test_filas_legibles(self):
        filas = {f['cod']: f for f in PerfilCalculo.objects.get(nombre='Bolivia - estándar').filas()}
        self.assertEqual(filas['MAT']['calculo'], 'Σ materiales')
        self.assertEqual(filas['BS']['calculo'], '55 % × MO')
        self.assertEqual(filas['IVA_MO']['calculo'], '14.94 % × (MO + BS)')
        self.assertEqual(filas['DIRECTO']['calculo'], 'MAT + TOT_MO + TOT_EQ')
        self.assertTrue(filas['PU']['total'])
        chile = {f['cod']: f for f in PerfilCalculo.objects.get(nombre__startswith='Chile').filas()}
        self.assertEqual((chile['IVA']['nivel'], chile['IVA']['calculo']), ('presupuesto', '19 % × NETO'))

    def test_detalle_visible_para_quien_ve_el_modulo_y_aislado_por_empresa(self):
        plantilla = PerfilCalculo.objects.get(nombre='Bolivia - estándar')
        ajeno = plantilla.copiar_a(self.b)
        self.client.force_login(self.obs)                      # el Observador puede ver (no copiar)
        r = self.client.get(f'/tekon/apu/perfiles/{plantilla.pk}/')
        self.assertContains(r, 'Gastos generales')
        self.assertNotContains(r, 'Copiar y editar')
        self.assertEqual(self.client.get(f'/tekon/apu/perfiles/{ajeno.pk}/').status_code, 404)
        self.client.force_login(self.coord)
        self.assertContains(self.client.get(f'/tekon/apu/perfiles/{plantilla.pk}/'), 'Copiar y editar')


def post_de(datos, accion='probar', **cambios):
    """Lo que enviaría el navegador al abrir el editor con `datos` y pulsar `accion`."""
    estado = editor.estado_inicial(datos)
    red = datos.get('redondeo', {})
    d = {'accion': accion, 'n': len(estado['filas']), 'total_apu': estado['total_apu'],
         'total_presupuesto': estado['total_presupuesto'], 'nombre': 'Perfil de prueba', 'pais': 'BO', 'moneda': 'BOB',
         'dec_total': red.get('total', 2), 'dec_linea': red.get('linea') if red.get('linea') is not None else '',
         'modo': red.get('modo', 'HALF_UP'), 'prueba_MAT': '100', 'prueba_MO': '50', 'prueba_EQ': '20'}
    for i, f in enumerate(estado['filas']):
        d.update({f'cod_{i}': f['cod'], f'nombre_{i}': f['nombre'], f'tipo_{i}': f['tipo'], f'grupo_{i}': f['grupo'],
                  f'nivel_{i}': f['nivel'], f'valor_{i}': f['valor'], f'sobre_{i}': f['bases']})
        if f['modo'] == 'sobre_precio':
            d[f'modo_{i}'] = 'on'
    d.update(cambios)
    return d


class EditorLogicaTests(SimpleTestCase):
    """`editor.py` no toca la base de datos."""

    def estado(self, datos=None):
        return editor.estado_inicial(datos or editor.MINIMO)

    def cods(self, estado):
        return [f['cod'] for f in estado['filas']]

    def test_agregar_recargo_toma_como_base_la_ultima_linea(self):
        e = self.estado()
        editor.aplicar_accion(e, 'agregar_recargo')
        self.assertEqual(self.cods(e), ['MAT', 'MO', 'EQ', 'DIRECTO', 'L1'])
        self.assertEqual((e['filas'][-1]['bases'], e['filas'][-1]['tipo']), (['DIRECTO'], 'porcentaje'))
        self.assertEqual(e['total_apu'], 'DIRECTO')

    def test_agregar_subtotal_pasa_a_ser_el_resultado(self):
        e = self.estado()
        editor.aplicar_accion(e, 'agregar_recargo')
        editor.aplicar_accion(e, 'agregar_subtotal')
        self.assertEqual((e['filas'][-1]['cod'], e['total_apu']), ('L2', 'L2'))
        self.assertEqual(e['filas'][-1]['bases'], ['DIRECTO', 'L1'])     # Costo directo + el recargo agregado
        datos, errores = editor.datos_desde_estado(e, editor.MINIMO['redondeo'])
        editor.validar_perfil(datos)                                       # el perfil armado solo con botones es válido

    def test_los_codigos_nuevos_no_se_repiten(self):
        e = self.estado()
        for _ in range(3):
            editor.aplicar_accion(e, 'agregar_recargo')
        editor.aplicar_accion(e, 'quitar:4')            # quita L1
        editor.aplicar_accion(e, 'agregar_recargo')
        self.assertEqual(len(set(self.cods(e))), len(e['filas']))

    def test_quitar_limpia_las_referencias_y_no_quita_sumas(self):
        e = self.estado()
        editor.aplicar_accion(e, 'agregar_recargo')
        e['filas'][-1]['bases'] = ['DIRECTO']
        editor.aplicar_accion(e, 'quitar:3')             # quita DIRECTO
        self.assertEqual(self.cods(e), ['MAT', 'MO', 'EQ', 'L1'])
        self.assertEqual(e['filas'][-1]['bases'], [])
        self.assertEqual(e['total_apu'], '')             # el resultado quitado deja de ser el resultado
        editor.aplicar_accion(e, 'quitar:0')             # MAT es una suma: se queda
        self.assertIn('MAT', self.cods(e))

    def test_subir_y_bajar_no_mezclan_sumas_ni_niveles(self):
        e = self.estado()
        editor.aplicar_accion(e, 'subir:3')              # DIRECTO no puede pasar sobre una suma
        self.assertEqual(self.cods(e)[:4], ['MAT', 'MO', 'EQ', 'DIRECTO'])
        editor.aplicar_accion(e, 'agregar_recargo')
        editor.aplicar_accion(e, 'subir:4')
        self.assertEqual(self.cods(e)[3:], ['L1', 'DIRECTO'])
        self.assertEqual(e['filas'][3]['bases'], [])     # L1 quedó antes de DIRECTO: su base ya no es anterior
        e['filas'][4]['nivel'] = 'presupuesto'
        editor._ordenar(e)
        editor.aplicar_accion(e, 'subir:4')
        self.assertEqual(self.cods(e)[3:], ['L1', 'DIRECTO'])

    def test_las_lineas_de_presupuesto_van_al_final(self):
        e = self.estado()
        editor.aplicar_accion(e, 'agregar_recargo')
        e['filas'][3]['nivel'] = 'presupuesto'           # DIRECTO pasa al final
        editor._ordenar(e)
        self.assertEqual(self.cods(e), ['MAT', 'MO', 'EQ', 'L1', 'DIRECTO'])

    def test_numeros_con_coma_y_errores_de_captura(self):
        e = self.estado()
        editor.aplicar_accion(e, 'agregar_recargo')
        e['filas'][-1]['valor'] = '14,94'
        datos, errores = editor.datos_desde_estado(e, editor.MINIMO['redondeo'])
        self.assertEqual((errores, datos['lineas'][-1]['pct']), ([], 0.1494))
        e['filas'][-1]['valor'] = 'abc'
        self.assertEqual(len(editor.datos_desde_estado(e, editor.MINIMO['redondeo'])[1]), 1)

    def test_estado_desde_post_tolera_basura(self):
        from django.http import QueryDict
        self.assertEqual(editor.estado_desde_post(QueryDict('n=zzz'))['filas'], [])
        self.assertEqual(len(editor.estado_desde_post(QueryDict('n=9999'))['filas']), editor.MAX_FILAS)

    def test_vista_previa_coincide_con_el_motor(self):
        self.assertEqual(editor.previsualizar(BOLIVIA_ESTANDAR, {'MAT': '100', 'MO': '50', 'EQ': '20'})['total_apu'],
                         D('266.36'))
        self.assertIsNone(editor.previsualizar({'lineas': []}, {}))


@override_settings(**AJUSTES)
class EditorVistasTests(Base):
    def setUp(self):
        super().setUp()
        self.plantilla = PerfilCalculo.objects.get(empresa=None, nombre='Bolivia - estándar')
        self.perfil = self.plantilla.copiar_a(self.a)
        self.url = f'/tekon/apu/perfiles/{self.perfil.pk}/editar/'
        self.client.force_login(self.coord)

    def idx(self, cod, datos=None):
        return [l['cod'] for l in (datos or self.perfil.datos)['lineas']].index(cod)

    def test_editar_muestra_los_valores_y_la_prueba(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'value="55"')
        self.assertContains(r, 'value="14.94"')
        self.assertEqual(r.context['vista_previa']['total_apu'], D('266.36'))

    def test_probar_recalcula_sin_guardar(self):
        d = post_de(self.perfil.datos, **{f'valor_{self.idx("GG")}': '20'})
        r = self.client.post(self.url, d)
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.context['vista_previa']['total_apu'], D('266.36'))
        self.perfil.refresh_from_db()
        self.assertEqual({l['cod']: l for l in self.perfil.datos['lineas']}['GG']['pct'], 0.1)

    def test_guardar_cambios(self):
        d = post_de(self.perfil.datos, 'guardar', nombre='Bolivia - licitación X',
                    **{f'valor_{self.idx("GG")}': '12,5', f'valor_{self.idx("BS")}': '60'})
        self.assertRedirects(self.client.post(self.url, d), f'/tekon/apu/perfiles/{self.perfil.pk}/', fetch_redirect_response=False)
        self.perfil.refresh_from_db()
        lineas = {l['cod']: l for l in self.perfil.datos['lineas']}
        self.assertEqual((self.perfil.nombre, lineas['GG']['pct'], lineas['BS']['pct']), ('Bolivia - licitación X', 0.125, 0.6))
        self.assertEqual({l['cod']: l for l in self.plantilla.datos['lineas']}['GG']['pct'], 0.1)   # la plantilla no cambia
        self.assertNotEqual(calcular(self.perfil.validado(), {'MAT': 100, 'MO': 50, 'EQ': 20}).total, D('266.36'))

    def test_guardar_invalido_no_guarda_y_explica(self):
        for cambio in ({f'valor_{self.idx("GG")}': '-5'}, {f'valor_{self.idx("GG")}': 'abc'}, {'dec_total': '12'},
                       {'moneda': ''}, {'total_apu': ''}):
            with self.subTest(cambio):
                r = self.client.post(self.url, post_de(self.perfil.datos, 'guardar', **cambio))
                self.assertEqual(r.status_code, 200)
                self.assertTrue(r.context['errores'] or r.context['form'].errors)
        self.perfil.refresh_from_db()
        self.assertEqual({l['cod']: l for l in self.perfil.datos['lineas']}['GG']['pct'], 0.1)

    def test_nombre_repetido_en_la_empresa(self):
        otra = self.plantilla.copiar_a(self.a)
        r = self.client.post(self.url, post_de(self.perfil.datos, 'guardar', nombre=otra.nombre))
        self.assertIn('Ya tienes un perfil con ese nombre.', r.context['form'].errors['nombre'])

    def test_agregar_y_quitar_lineas_desde_la_vista(self):
        n = len(self.perfil.datos['lineas'])
        r = self.client.post(self.url, post_de(self.perfil.datos, 'agregar_recargo'))
        self.assertEqual(len(r.context['filas']), n + 1)
        self.assertEqual(len(self.perfil.datos['lineas']), n)                     # nada se guardó todavía
        r = self.client.post(self.url, post_de(self.perfil.datos, f'quitar:{self.idx("IT")}'))
        self.assertEqual(len(r.context['filas']), n - 1)

    def test_crear_desde_cero_con_un_recargo(self):
        r = self.client.get('/tekon/apu/perfiles/nuevo/')
        self.assertEqual([f['cod'] for f in r.context['filas']], ['MAT', 'MO', 'EQ', 'DIRECTO'])
        e = editor.estado_inicial(editor.MINIMO)
        editor.aplicar_accion(e, 'agregar_recargo')
        datos, _ = editor.datos_desde_estado(e, editor.MINIMO['redondeo'])
        d = post_de(datos, 'guardar', nombre='Mi perfil', moneda='usd', pais='cl', **{'valor_4': '10', 'sobre_4': ['DIRECTO']})
        self.assertEqual(PerfilCalculo.objects.filter(empresa=self.a, nombre='Mi perfil').count(), 0)
        r = self.client.post('/tekon/apu/perfiles/nuevo/', d)
        nuevo = PerfilCalculo.objects.get(empresa=self.a, nombre='Mi perfil')
        self.assertRedirects(r, f'/tekon/apu/perfiles/{nuevo.pk}/', fetch_redirect_response=False)
        self.assertEqual((nuevo.moneda, nuevo.pais), ('USD', 'CL'))
        self.assertEqual(len(nuevo.datos['lineas']), 5)
        self.assertEqual(calcular(nuevo.validado(), {'MAT': 100}).lineas['L1'], D('10'))

    def test_perfil_de_presupuesto_se_previsualiza(self):
        chile = PerfilCalculo.objects.get(nombre__startswith='Chile').copiar_a(self.a)
        r = self.client.get(f'/tekon/apu/perfiles/{chile.pk}/editar/')
        self.assertEqual(r.context['vista_previa']['total_apu'], D('170'))
        self.assertEqual(r.context['vista_previa']['total_presupuesto'], D('247'))    # 170 × (1 + 0,12 + 0,10) × 1,19 = 246,806 → 247

    def test_las_plantillas_y_lo_ajeno_no_se_editan_ni_borran(self):
        ajeno = self.plantilla.copiar_a(self.b)
        for pk in (self.plantilla.pk, ajeno.pk):
            self.assertEqual(self.client.get(f'/tekon/apu/perfiles/{pk}/editar/').status_code, 404)
            self.assertEqual(self.client.post(f'/tekon/apu/perfiles/{pk}/eliminar/').status_code, 404)
        self.assertEqual(PerfilCalculo.objects.filter(pk__in=[self.plantilla.pk, ajeno.pk]).count(), 2)

    def test_crear_y_editar_exigen_capacidad(self):
        self.client.force_login(self.obs)
        self.assertEqual(self.client.get('/tekon/apu/perfiles/nuevo/').status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_eliminar_exige_post_y_capacidad(self):
        url = f'/tekon/apu/perfiles/{self.perfil.pk}/eliminar/'
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(self.obs)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(PerfilCalculo.objects.filter(pk=self.perfil.pk).exists())
        self.client.force_login(self.coord)
        self.assertRedirects(self.client.post(url), '/tekon/apu/', fetch_redirect_response=False)
        self.assertFalse(PerfilCalculo.objects.filter(pk=self.perfil.pk).exists())
        self.assertTrue(PerfilCalculo.objects.filter(pk=self.plantilla.pk).exists())

    def test_botones_segun_sea_plantilla_o_propio(self):
        r = self.client.get('/tekon/apu/')
        self.assertContains(r, '/apu/perfiles/nuevo/')
        self.assertContains(r, f'/apu/perfiles/{self.perfil.pk}/editar/')
        self.assertContains(r, f'/apu/perfiles/{self.perfil.pk}/eliminar/')
        self.assertNotContains(r, f'/apu/perfiles/{self.plantilla.pk}/editar/')
        self.assertNotContains(r, f'/apu/perfiles/{self.plantilla.pk}/eliminar/')


@override_settings(**AJUSTES)
class SinPasoProyectoClaroTests(Base):
    """El proyecto y su descripción se dan por correctos: no hay paso de IA que los cuestione."""

    def test_no_existe_el_paso_ni_sus_prompts_y_la_coherencia_lo_deja_claro(self):
        from .models import PlantillaAPU, PromptAPU
        self.assertNotIn('proyecto_claro', dict(PromptAPU.Paso.choices))
        self.assertFalse(PromptAPU.objects.filter(paso='proyecto_claro').exists())
        plantillas = list(PlantillaAPU.objects.all())
        self.assertTrue(plantillas)
        for pl in plantillas:
            self.assertIn('no la cuestiones', pl.prompt('coherencia').texto, pl.nombre)


@override_settings(**AJUSTES)
class EliminarInsumosEnBloqueTests(Base):
    """Seleccionar y eliminar insumos en bloque: solo el superusuario; lo que usa un APU se protege."""
    URL = '/tekon/apu/insumos/eliminar-varios/'

    def setUp(self):
        super().setUp()
        self.su = User.objects.create_superuser('su@example.com', 'x')
        self.m = [Insumo.objects.create(empresa=self.a, codigo=f'M-{i:02d}', descripcion=f'Material {i}', unidad='kg', tipo=Tipo.MATERIAL) for i in range(5)]
        self.mo = Insumo.objects.create(empresa=self.a, codigo='MO-01', descripcion='Peón', unidad='h', tipo=Tipo.MANO_OBRA)
        self.ajeno = Insumo.objects.create(empresa=self.b, codigo='M-01', descripcion='De otra empresa', unidad='kg', tipo=Tipo.MATERIAL)

    def test_solo_el_superusuario_ve_las_casillas_y_puede_eliminar(self):
        for u in (self.coord, self.obs):
            self.client.force_login(u)
            self.assertNotContains(self.client.get('/tekon/apu/insumos/'), 'data-bulk')
            self.assertEqual(self.client.post(self.URL, {'ids': [self.m[0].pk]}).status_code, 403)
        self.assertEqual(Insumo.objects.filter(empresa=self.a).count(), 6)
        self.client.force_login(self.su)
        self.assertContains(self.client.get('/tekon/apu/insumos/'), 'data-bulk')

    def test_elimina_solo_los_marcados_y_de_su_empresa(self):
        self.client.force_login(self.su)
        r = self.client.post(self.URL, {'ids': [self.m[0].pk, self.m[1].pk, self.ajeno.pk]})
        self.assertRedirects(r, '/tekon/apu/insumos/')
        self.assertEqual(Insumo.objects.filter(empresa=self.a).count(), 4)
        self.assertTrue(Insumo.objects.filter(pk=self.ajeno.pk).exists())            # el de otra empresa no se toca

    def test_todos_respeta_el_filtro_y_no_toca_otras_empresas(self):
        self.client.force_login(self.su)
        r = self.client.post(self.URL, {'todos': '1', 'tipo': Tipo.MATERIAL})
        self.assertRedirects(r, '/tekon/apu/insumos/?tipo=%s' % Tipo.MATERIAL)
        self.assertEqual(list(Insumo.objects.filter(empresa=self.a)), [self.mo])      # quedó solo la mano de obra
        self.assertTrue(Insumo.objects.filter(pk=self.ajeno.pk).exists())
        self.client.post(self.URL, {'todos': '1'})
        self.assertFalse(Insumo.objects.filter(empresa=self.a).exists())

    def test_sin_seleccion_no_borra_nada(self):
        self.client.force_login(self.su)
        self.client.post(self.URL, {})
        self.assertEqual(Insumo.objects.filter(empresa=self.a).count(), 6)

    def test_un_insumo_usado_por_un_apu_se_protege(self):
        item = ItemModelo.objects.create(empresa=self.a, codigo='APU-1', descripcion='Muro', unidad='m2')
        LineaComposicion.objects.create(item=item, insumo=self.m[0], cantidad=D('1'))
        self.client.force_login(self.su)
        self.client.post(self.URL, {'todos': '1'})
        self.assertEqual(list(Insumo.objects.filter(empresa=self.a)), [self.m[0]])    # el usado queda; el resto se eliminó

    def test_solo_post(self):
        self.client.force_login(self.su)
        self.assertEqual(self.client.get(self.URL).status_code, 405)


@override_settings(**AJUSTES)
class SoloAdministradoresTests(Base):
    """APU está cerrado a quien no administra: ve «Próximamente» (página y respuestas AJAX)."""

    @override_settings(APU_SOLO_ADMIN=True)
    def test_un_miembro_comun_ve_proximamente_y_el_superusuario_entra(self):
        self.client.force_login(self.coord)
        r = self.client.get('/tekon/apu/insumos/')
        self.assertContains(r, 'Próximamente', status_code=403)
        r = self.client.get('/tekon/apu/insumos/', HTTP_ACCEPT='application/json')
        self.assertEqual(r.status_code, 403)
        su = User.objects.create_superuser('su@example.com', 'x')
        self.client.force_login(su)
        self.assertEqual(self.client.get('/tekon/apu/insumos/').status_code, 200)


@override_settings(**AJUSTES)
class CategoriasTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.coord)

    def nombres(self, empresa=None):
        from .models import CategoriaAPU
        return list(CategoriaAPU.objects.filter(empresa=empresa or self.a).values_list('nombre', flat=True))

    def test_crear_sin_duplicar_por_mayusculas_ni_tildes(self):
        self.client.post('/tekon/apu/categorias/nueva/', {'nombre': 'Obra gruesa'})
        r = self.client.post('/tekon/apu/categorias/nueva/', {'nombre': ' obra  GRUESA '}, follow=True)
        self.assertEqual(self.nombres(), ['Obra gruesa'])
        self.assertContains(r, 'Ya existe')
        self.client.post('/tekon/apu/categorias/nueva/', {'nombre': 'Instalación'})
        self.client.post('/tekon/apu/categorias/nueva/', {'nombre': 'instalacion'})
        self.assertEqual(self.nombres(), ['Obra gruesa', 'Instalación'])

    def test_reordenar_a_mano(self):
        from . import categorias as cats
        a, b, c = (cats.crear(self.a, n) for n in ('A', 'B', 'C'))
        self.client.post(f'/tekon/apu/categorias/{c.pk}/mover/', {'sentido': 'subir'})
        self.assertEqual(self.nombres(), ['A', 'C', 'B'])
        self.client.post(f'/tekon/apu/categorias/{a.pk}/mover/', {'sentido': 'bajar'})
        self.assertEqual(self.nombres(), ['C', 'A', 'B'])
        self.client.post(f'/tekon/apu/categorias/{c.pk}/mover/', {'sentido': 'subir'})   # ya es la primera
        self.assertEqual(self.nombres(), ['C', 'A', 'B'])

    def test_renombrar_fusionar_y_eliminar(self):
        from . import categorias as cats
        a, b = cats.crear(self.a, 'Acabados'), cats.crear(self.a, 'Acabado')
        item = ItemModelo.objects.create(empresa=self.a, codigo='X', descripcion='x', unidad='m2', categoria=b)
        self.client.post(f'/tekon/apu/categorias/{b.pk}/renombrar/', {'nombre': 'Acabados Finos'})
        self.assertEqual(self.nombres(), ['Acabados', 'Acabados Finos'])
        r = self.client.post(f'/tekon/apu/categorias/{b.pk}/renombrar/', {'nombre': 'acabados'}, follow=True)
        self.assertContains(r, 'Ya existe')
        self.client.post(f'/tekon/apu/categorias/{b.pk}/fusionar/', {'destino': a.pk})
        item.refresh_from_db()
        self.assertEqual((self.nombres(), item.categoria), (['Acabados'], a))
        self.client.post(f'/tekon/apu/categorias/{a.pk}/eliminar/')
        item.refresh_from_db()
        self.assertEqual((self.nombres(), item.categoria), ([], None))

    def test_permisos_y_aislamiento_por_empresa(self):
        from . import categorias as cats
        ajena = cats.crear(self.b, 'Ajena')
        self.assertEqual(self.client.post(f'/tekon/apu/categorias/{ajena.pk}/eliminar/').status_code, 404)
        self.assertEqual(self.client.get('/tekon/apu/categorias/nueva/').status_code, 405)
        self.client.force_login(self.obs)
        self.assertEqual(self.client.post('/tekon/apu/categorias/nueva/', {'nombre': 'X'}).status_code, 403)
        self.assertEqual(self.client.get('/tekon/apu/categorias/').status_code, 200)
        self.assertEqual(self.nombres(), [])

    def test_la_ia_reutiliza_o_crea_al_final(self):
        from . import categorias as cats
        a = cats.crear(self.a, 'Obra gruesa')
        self.assertEqual(cats.obtener_o_crear(self.a, 'obra GRUESA'), a)
        n = cats.obtener_o_crear(self.a, 'Estructuras')
        self.assertEqual((n.orden, cats.para_ia(self.a)), (2, ['Obra gruesa', 'Estructuras']))
        self.assertIsNone(cats.obtener_o_crear(self.a, '  '))


class UnidadesTests(SimpleTestCase):
    def test_abrevia_nombres_sinonimos_y_errores_de_tipeo(self):
        from .unidades import normalizar
        for escrito, esperado in [('hectárea', 'ha'), ('hactarea', 'ha'), ('Hectareas', 'ha'), ('metro', 'm'),
                                  ('Metros Cuadrados', 'm²'), ('m2', 'm²'), ('M3', 'm³'), ('kilos', 'kg'),
                                  ('Pza.', 'pza'), ('tonelada', 't'), ('m²', 'm²'), ('  ml ', 'ml')]:
            self.assertEqual(normalizar(escrito), esperado, escrito)

    def test_lo_desconocido_se_respeta(self):
        from .unidades import normalizar
        self.assertEqual(normalizar('  Quintal   grande '), 'Quintal grande')
        self.assertEqual(normalizar(''), '')
