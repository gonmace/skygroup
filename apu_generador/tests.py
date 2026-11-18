import json
from datetime import date, timedelta
from decimal import Decimal as D
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apu_catalogo import calculo
from apu_catalogo.models import Insumo, ItemModelo, LineaComposicion, PerfilCalculo, PrecioInsumo, ProyectoAPU, Tipo
from core.n8n import N8NError
from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from proyectos.models import Proyecto

from . import asistente, creditos, ia
from .models import (APUBorrador, ConsumoAPU, LimiteAPU, LimiteEmpresaAPU, LlamadaIA, TarifaModeloIA)

AJUSTES = dict(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
DESCRIPCION = ('Construcción de una escuela de dos plantas en la ciudad de Tarija, con muros de ladrillo, losa '
               'alivianada y terminaciones sencillas para uso educativo.')
LLAMAR = 'apu_generador.ia.n8n.llamar_webhook_seguro'
MAX_SUGERENCIAS_PRUEBA = 3          # = apu_generador.views.MAX_SUGERENCIAS
COHERENTE = {'coherente': True, 'sistema_constructivo': 'Mampostería', 'tipo_elemento': 'Muro',
             'material_principal': 'Ladrillo', 'proceso_principal': 'Asentado', 'categoria': 'Obra gruesa'}


def propuesta_materiales():
    return {'filas': [
        {'descripcion': 'Ladrillo 6H', 'unidad': 'pza', 'cantidad': '38', 'desperdicio_pct': '5', 'check': True},
        {'descripcion': 'Mortero 1:4', 'unidad': 'm3', 'cantidad': '0,03', 'desperdicio_pct': '10', 'check': True}]}


@override_settings(**AJUSTES)
@override_settings(APU_SOLO_ADMIN=False)
class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Tekon', slug='tekon', modulos=['apu'])
        cls.b = crear_empresa(nombre='Embol', slug='embol', modulos=['apu'])
        cls.c = crear_empresa(nombre='Conjor', slug='conjor', modulos=['apu', 'jor'])

        def usuario(correo, empresa, rol, **kw):
            u = User.objects.create_user(correo, 'x', **kw)
            m = agregar_miembro(u, empresa, rol_por_base(empresa, rol)) if empresa else None
            return u, m
        cls.coord, cls.m_coord = usuario('coord@example.com', cls.a, RolBase.COORDINADOR)
        cls.ejec, cls.m_ejec = usuario('ejec@example.com', cls.a, RolBase.MIEMBRO)
        cls.obs, _ = usuario('obs@example.com', cls.a, RolBase.OBSERVADOR)
        cls.adm, cls.m_adm = usuario('adm@example.com', cls.a, RolBase.MIEMBRO)
        cls.adm.empresas_administradas.add(cls.a)
        cls.su, _ = usuario('su@example.com', None, None, is_superuser=True, is_staff=True)
        cls.ajeno, _ = usuario('ajeno@example.com', cls.b, RolBase.COORDINADOR)
        cls.ejec_c, cls.m_ejec_c = usuario('ejecc@example.com', cls.c, RolBase.MIEMBRO)
        cls.proyecto = Proyecto.objects.create(empresa=cls.a, nombre='Escuela Tarija', descripcion=DESCRIPCION)
        cls.proyecto_b = Proyecto.objects.create(empresa=cls.b, nombre='Otro', descripcion=DESCRIPCION)
        cls.perfil = PerfilCalculo.objects.get(empresa=None, nombre='Bolivia - estándar')
        cls.pa = ProyectoAPU.objects.create(proyecto=cls.proyecto, perfil=cls.perfil)

    def setUp(self):
        cache.clear()

    def json(self, url, datos=None, usuario=None):
        if usuario:
            self.client.force_login(usuario)
        return self.client.post(url, json.dumps(datos or {}), content_type='application/json')

    def borrador(self, paso=1, **kw):
        base = dict(empresa=self.a, proyecto=self.proyecto, creado_por=self.coord, actividad='Muro de ladrillo',
                    unidad='m2', descripcion='e=12 cm', paso=paso)
        base.update(kw)
        return APUBorrador.objects.create(**base)

    def insumo(self, codigo, descripcion, tipo=Tipo.MATERIAL, unidad='pza', empresa=None, precio=None):
        i = Insumo.objects.create(empresa=empresa or self.a, codigo=codigo, descripcion=descripcion, unidad=unidad, tipo=tipo)
        if precio is not None:
            PrecioInsumo.objects.create(insumo=i, fecha=date(2026, 1, 1), precio=D(precio), moneda='BOB')
        return i

    def borrador_en_paso5(self, **kw):
        """Borrador con los tres pasos confirmados, listo para guardar (sin pasar por la IA)."""
        ladrillo = self.insumo('MAT-001', 'Ladrillo 6H', precio='1.50')
        albanil = self.insumo('MO-001', 'Albañil', Tipo.MANO_OBRA, 'h', precio='20')
        mezcl = self.insumo('EQ-001', 'Mezcladora', Tipo.EQUIPO, 'h', precio='10')
        return self.borrador(
            paso=5, clasificacion={'categoria': 'Obra gruesa'},
            materiales={'filas': [{'descripcion': 'Ladrillo 6H', 'unidad': 'pza', 'cantidad': '38', 'desperdicio_pct': '5',
                                   'insumo_id': ladrillo.pk, 'check': True}]},
            mano_obra={'filas': [{'descripcion': 'Albañil', 'unidad': 'h', 'personas': '2', 'cantidad': '0.5',
                                  'insumo_id': albanil.pk, 'check': True}], 'rendimiento': '8', 'horas_jornada': '2'},
            equipos={'filas': [{'descripcion': 'Mezcladora', 'unidad': 'h', 'cantidad': '0.1', 'insumo_id': mezcl.pk,
                                'check': True}]}, **kw)


class Paso1Tests(Base):
    URL = '/tekon/apu/generar/'

    def datos(self, **kw):
        d = {'proyecto': self.proyecto.pk, 'actividad': 'Muro de ladrillo 6H', 'unidad': 'm2', 'descripcion': 'e=12 cm', 'region': ''}
        d.update(kw)
        return d

    def test_coherente_crea_el_borrador_antes_y_avanza_al_paso_2(self):
        with mock.patch(LLAMAR, return_value=COHERENTE) as ll:
            r = self.json(self.URL, self.datos(), self.coord)
        self.assertEqual(r.json()['estado'], 'ok')
        b = APUBorrador.objects.get()
        self.assertEqual((b.paso, b.proyecto, b.clasificacion['categoria']), (2, self.proyecto, 'Obra gruesa'))
        self.assertEqual(LlamadaIA.objects.get().webhook, 'apu-coherencia')
        enviado = ll.call_args[0][1]
        self.assertEqual(enviado['proyecto']['descripcion'], DESCRIPCION)
        self.assertNotIn('pais', json.dumps(enviado).lower())          # ningún payload lleva país

    def test_no_coherente_no_avanza_y_muestra_la_razon(self):
        with mock.patch(LLAMAR, return_value={'coherente': False, 'razon': 'Un muro no se mide en kg'}):
            r = self.json(self.URL, self.datos(), self.coord).json()
        self.assertEqual((r['estado'], r['razon']), ('no_coherente', 'Un muro no se mide en kg'))
        self.assertEqual(APUBorrador.objects.get().paso, 1)

    def test_proyecto_poco_claro_pide_completar_la_descripcion(self):
        with mock.patch(LLAMAR, return_value={'proyecto_claro': False, 'falta': 'No dice qué se construye'}):
            r = self.json(self.URL, self.datos(), self.coord).json()
        self.assertEqual((r['estado'], r['falta']), ('proyecto_poco_claro', 'No dice qué se construye'))
        self.assertEqual(APUBorrador.objects.get().paso, 1)

    def test_si_n8n_falla_el_borrador_queda_pendiente_en_el_paso_1(self):
        with mock.patch(LLAMAR, side_effect=N8NError('El servicio de IA tardó demasiado en responder.')):
            r = self.json(self.URL, self.datos(), self.coord)
        self.assertEqual(r.status_code, 502)
        self.assertIn('tardó demasiado', r.json()['message'])
        b = APUBorrador.objects.get()
        self.assertEqual(b.paso, 1)
        self.assertTrue(b.pendiente)
        self.assertEqual(LlamadaIA.objects.get().ok, False)
        self.client.force_login(self.coord)
        self.assertContains(self.client.get('/tekon/apu/pendientes/'), 'Muro de ladrillo 6H')

    def test_respuesta_invalida_de_n8n(self):
        with mock.patch(LLAMAR, return_value={'algo': 1}):
            self.assertEqual(self.json(self.URL, self.datos(), self.coord).status_code, 502)

    def test_proyecto_sin_descripcion_la_exige_y_la_guarda_en_el_proyecto(self):
        p = Proyecto.objects.create(empresa=self.a, nombre='Sin texto')
        ProyectoAPU.objects.create(proyecto=p, perfil=self.perfil)
        r = self.json(self.URL, self.datos(proyecto=p.pk), self.coord)
        self.assertEqual(r.status_code, 400)
        self.assertIn('15 palabras', r.json()['message'])
        self.assertFalse(APUBorrador.objects.exists())
        with mock.patch(LLAMAR, return_value=COHERENTE):
            self.assertEqual(self.json(self.URL, self.datos(proyecto=p.pk, proyecto_descripcion=DESCRIPCION)).status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.descripcion, DESCRIPCION)

    def test_un_proyecto_sin_habilitar_no_se_puede_usar(self):
        p = Proyecto.objects.create(empresa=self.a, nombre='Sin habilitar', descripcion=DESCRIPCION)
        r = self.json(self.URL, self.datos(proyecto=p.pk), self.coord)
        self.assertEqual(r.status_code, 400)
        self.assertIn('habilitado', r.json()['message'])
        self.assertFalse(APUBorrador.objects.exists())
        self.assertNotContains(self.client.get(self.URL), 'Sin habilitar')            # tampoco se ofrece en el selector

    def test_el_paso_1_no_pide_perfil_porque_sale_de_la_habilitacion(self):
        self.client.force_login(self.coord)
        self.assertNotContains(self.client.get(self.URL), 'name="perfil"')

    def test_el_perfil_es_unico_por_empresa_y_las_plantillas_tampoco_se_repiten(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            PerfilCalculo.objects.create(empresa=self.a, nombre=self.perfil.nombre, moneda='BOB', datos=self.perfil.datos) \
                and PerfilCalculo.objects.create(empresa=self.a, nombre=self.perfil.nombre, moneda='BOB', datos=self.perfil.datos)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PerfilCalculo.objects.create(empresa=None, nombre=self.perfil.nombre, moneda='BOB', datos=self.perfil.datos)

    def test_exige_proyecto_de_la_propia_empresa(self):
        r = self.json(self.URL, self.datos(proyecto=self.proyecto_b.pk), self.coord)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(APUBorrador.objects.exists())

    def test_la_region_de_precios_sale_del_proyecto_no_del_formulario(self):
        self.pa.region = 'Tarija'
        self.pa.save()
        with mock.patch(LLAMAR, return_value=COHERENTE) as ll:
            self.json(self.URL, self.datos(region='Otra ciudad'), self.coord)
        self.assertEqual(APUBorrador.objects.get().region, 'Tarija')
        self.assertEqual(ll.call_args[0][1]['region'], 'Tarija')
        self.assertNotContains(self.client.get(self.URL), 'name="region"')

    def test_el_superusuario_sin_membresia_puede_generar_en_la_empresa_activa(self):
        with mock.patch(LLAMAR, return_value=COHERENTE):
            r = self.json(self.URL, self.datos(), self.su)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['estado'], 'ok')
        b = APUBorrador.objects.get()
        self.assertEqual((b.empresa, b.creado_por), (self.a, self.su))
        self.assertEqual(self.client.get(self.URL).status_code, 200)                   # la página también abre

    def test_el_observador_no_puede_generar(self):
        self.assertEqual(self.json(self.URL, self.datos(), self.obs).status_code, 403)

    def test_corregir_y_volver_a_comprobar_no_cobra_ni_duplica(self):
        with mock.patch(LLAMAR, return_value={'coherente': False, 'razon': 'x'}):
            self.json(self.URL, self.datos(), self.coord)
        b = APUBorrador.objects.get()
        with mock.patch(LLAMAR, return_value=COHERENTE):
            r = self.json(f'/tekon/apu/borrador/{b.pk}/actividad/', self.datos(actividad='Muro corregido'))
        self.assertEqual(r.json()['estado'], 'ok')
        b.refresh_from_db()
        self.assertEqual((b.actividad, b.paso, APUBorrador.objects.count()), ('Muro corregido', 2, 1))
        self.assertFalse(ConsumoAPU.objects.exists())


class PasosTests(Base):
    def url(self, b, accion='', slug='materiales'):
        return f'/tekon/apu/borrador/{b.pk}/{slug}/{accion}'

    def test_proponer_no_guarda_y_envia_catalogo_decisiones_y_proyecto(self):
        self.insumo('MAT-001', 'Cemento')
        self.insumo('MAT-002', 'Cemento ajeno', empresa=self.b)
        b = self.borrador(paso=2, clasificacion={'categoria': 'x'})
        with mock.patch(LLAMAR, return_value=propuesta_materiales()) as ll:
            r = self.json(self.url(b, 'proponer/'), {}, self.coord).json()
        self.assertEqual(len(r['propuesta']['filas']), 2)
        self.assertEqual(r['propuesta']['filas'][1]['cantidad'], '0.03')          # coma decimal normalizada
        b.refresh_from_db()
        self.assertEqual(b.materiales, {})                                          # nada confirmado todavía
        self.assertEqual(b.paso, 2)
        enviado = ll.call_args[0][1]
        self.assertEqual([c['codigo'] for c in enviado['catalogo']], ['MAT-001'])  # solo del tipo y de la empresa
        self.assertEqual(enviado['proyecto']['nombre'], 'Escuela Tarija')
        self.assertFalse(ConsumoAPU.objects.exists())                               # proponer no cobra

    def test_guardar_solo_lo_marcado_crea_insumos_y_avanza(self):
        b = self.borrador(paso=2)
        filas = [{'descripcion': 'Ladrillo 6H', 'unidad': 'pza', 'cantidad': '38', 'desperdicio_pct': '5', 'check': True},
                 {'descripcion': 'Arena', 'unidad': 'm3', 'cantidad': '0.1', 'check': False}]
        r = self.json(self.url(b, 'guardar/'), {'filas': filas}, self.coord)
        self.assertEqual(r.status_code, 200)
        b.refresh_from_db()
        self.assertEqual((b.paso, len(b.materiales['filas'])), (3, 1))
        insumo = Insumo.objects.get(empresa=self.a)
        self.assertEqual((insumo.codigo, insumo.tipo, insumo.descripcion), ('MAT-001', Tipo.MATERIAL, 'Ladrillo 6H'))
        self.assertFalse(Insumo.objects.filter(descripcion='Arena').exists())      # lo no marcado no entra al catálogo

    def test_un_paso_guardado_queda_cerrado(self):
        b = self.borrador(paso=3, materiales={'filas': [{'descripcion': 'x'}]})
        self.client.force_login(self.coord)
        self.assertRedirects(self.client.get(self.url(b)), f'/tekon/apu/borrador/{b.pk}/mano-obra/', fetch_redirect_response=False)
        r = self.json(self.url(b, 'guardar/'), {'filas': []})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.json(self.url(b, 'proponer/')).status_code, 409)

    def test_vocabulario_no_distingue_mayusculas_tildes_ni_espacios_ni_empresas(self):
        existente = self.insumo('MO-001', 'Albañil', Tipo.MANO_OBRA, 'h')
        ajeno = self.insumo('MO-009', 'Ayudante', Tipo.MANO_OBRA, 'h', empresa=self.b)
        for nombre in ('albañil ', 'ALBANIL', 'Albanil'):
            self.assertEqual(asistente.resolver_insumo(self.a, 'mano_obra', {'descripcion': nombre, 'unidad': 'h'}), existente)
        nuevo = asistente.resolver_insumo(self.a, 'mano_obra', {'descripcion': 'Ayudante', 'unidad': 'h'})
        self.assertNotEqual(nuevo, ajeno)                                          # no se mezclan empresas
        self.assertEqual(nuevo.codigo, 'MO-002')
        self.assertEqual(Insumo.objects.filter(empresa=self.a).count(), 2)

    def test_mano_de_obra_calcula_horas_por_unidad(self):
        b = self.borrador(paso=3, materiales={'filas': [{'descripcion': 'x'}]})
        datos = {'filas': [{'descripcion': 'Albañil', 'unidad': 'h', 'personas': '3', 'check': True}],
                 'rendimiento': '12', 'horas_jornada': '8'}
        self.assertEqual(self.json(self.url(b, 'guardar/', 'mano-obra'), datos, self.coord).status_code, 200)
        b.refresh_from_db()
        self.assertEqual(D(b.mano_obra['filas'][0]['cantidad']), D('2'))           # 3 × 8 ÷ 12
        self.assertEqual(self.json(self.url(b, 'guardar/', 'mano-obra'), datos).status_code, 409)

    def test_mano_de_obra_exige_rendimiento(self):
        b = self.borrador(paso=3)
        r = self.json(self.url(b, 'guardar/', 'mano-obra'),
                      {'filas': [{'descripcion': 'Albañil', 'unidad': 'h', 'personas': '2', 'check': True}], 'rendimiento': '0', 'horas_jornada': '8'}, self.coord)
        self.assertEqual(r.status_code, 400)

    def test_no_se_guarda_con_consultas_sin_responder(self):
        b = self.borrador(paso=2, consultas={'materiales': {'propuesta': {'consultas': [
            {'id': 'c1', 'tipo': 'opciones', 'pregunta': '¿Premezclado?', 'opciones': [], 'recomendada': ''}]}}})
        fila = {'descripcion': 'Hormigón H21', 'unidad': 'm3', 'cantidad': '0.1', 'check': True}
        r = self.json(self.url(b, 'guardar/'), {'filas': [fila], 'decisiones': {}}, self.coord)
        self.assertEqual(r.status_code, 400)
        self.assertIn('consultas pendientes', r.json()['message'])
        ok = self.json(self.url(b, 'guardar/'), {'filas': [fila], 'decisiones': {'c1': 'consolidado'}})
        self.assertEqual(ok.status_code, 200)
        b.refresh_from_db()
        self.assertEqual(b.consultas['materiales']['decisiones']['c1']['clave'], 'consolidado')

    def test_opcion_de_sub_analisis_crea_una_linea_con_sub_item(self):
        sub = ItemModelo.objects.create(empresa=self.a, codigo='HOR-21', descripcion='Hormigón H21 en obra', unidad='m3')
        b = self.borrador(paso=2)
        fila = {'descripcion': 'Hormigón H21 en obra', 'unidad': 'm3', 'codigo_subitem': 'HOR-21', 'cantidad': '0.1', 'check': True}
        self.assertEqual(self.json(self.url(b, 'guardar/'), {'filas': [fila]}, self.coord).status_code, 200)
        b.refresh_from_db()
        self.assertEqual(b.materiales['filas'][0]['subitem_id'], sub.pk)
        self.assertFalse(Insumo.objects.exists())

    def test_normalizar_consultas(self):
        crudas = [{'id': 'c1', 'pregunta': '¿Premezclado?', 'recomendada': 'zzz',
                   'opciones': [{'clave': 'a', 'etiqueta': 'A', 'filas': [{'descripcion': 'Hormigón', 'unidad': 'm3', 'cantidad': '1'}]},
                                {'clave': 'b', 'etiqueta': 'B'}]},
                  {'tipo': 'dato', 'pregunta': '¿Portante?', 'opciones': ['Sí', 'No']},
                  {'pregunta': 'sola', 'opciones': [{'clave': 'a', 'etiqueta': 'A'}]},    # una sola opción: no es consulta
                  {'sin': 'pregunta'}]
        res = ia.normalizar_propuesta({'filas': [], 'consultas': crudas}, 'materiales')['consultas']
        self.assertEqual([c['tipo'] for c in res], ['opciones', 'dato'])
        self.assertEqual(res[0]['recomendada'], 'a')                                  # recomendada inválida → la primera
        self.assertEqual(res[0]['opciones'][0]['filas'][0]['consulta'], 'c1')
        self.assertEqual(res[1]['opciones'][0]['etiqueta'], 'Sí')

    def test_una_fila_que_ya_esta_en_una_opcion_no_se_repite_en_el_nivel_superior(self):
        crudo = {'filas': [{'descripcion': 'Acero', 'unidad': 'kg', 'cantidad': 100},
                           {'descripcion': 'Tablas de encofrado', 'unidad': 'm2', 'cantidad': 2},
                           {'descripcion': 'Membrana de curado', 'unidad': 'l', 'cantidad': 0}],
                 'consultas': [{'id': 'c1', 'tipo': 'opciones', 'pregunta': '¿Incluir el encofrado?', 'recomendada': 'si',
                                'opciones': [{'clave': 'si', 'etiqueta': 'Incluir', 'filas': [
                                    {'descripcion': 'tablas de encofrado ', 'unidad': 'm2', 'cantidad': 2}]},
                                             {'clave': 'no', 'etiqueta': 'Aparte'}]}]}
        p = ia.normalizar_propuesta(crudo, 'materiales')
        self.assertEqual([f['descripcion'] for f in p['filas']], ['Acero', 'Membrana de curado'])   # el encofrado queda solo en la opción
        self.assertEqual(p['consultas'][0]['opciones'][0]['filas'][0]['consulta'], 'c1')
        self.assertEqual([f['check'] for f in p['filas']], [True, False])                          # cantidad cero: desmarcada

    def test_rendimiento_cero_o_ausente_queda_vacio_y_las_horas_por_defecto_son_8(self):
        for crudo in ({'filas': [{'descripcion': 'Albañil', 'personas': 1}], 'rendimiento': 0},
                      {'filas': [{'descripcion': 'Albañil', 'personas': 1}]}):
            p = ia.normalizar_propuesta(crudo, 'mano_obra')
            self.assertNotIn('rendimiento', p)
            self.assertEqual(p['horas_jornada'], '8')
        p = ia.normalizar_propuesta({'filas': [{'descripcion': 'Albañil', 'personas': 1}], 'rendimiento': 12, 'horas_jornada': 9}, 'mano_obra')
        self.assertEqual((p['rendimiento'], p['horas_jornada']), ('12', '9'))

    def test_las_dudas_se_reenvian_con_historial_y_hay_un_maximo_de_rondas(self):
        b = self.borrador(paso=2)
        dato = {'filas': [], 'consultas': [{'id': 'c1', 'tipo': 'dato', 'pregunta': '¿Es portante?'}]}
        with mock.patch(LLAMAR, return_value=dato):
            self.json(self.url(b, 'proponer/'), {}, self.coord)
        with mock.patch(LLAMAR, return_value=propuesta_materiales()) as ll:
            self.json(self.url(b, 'proponer/'), {'respuestas': {'c1': 'Sí, portante'}})
        enviado = ll.call_args[0][1]
        self.assertEqual(enviado['historial'], [{'pregunta': '¿Es portante?', 'respuesta': 'Sí, portante'}])
        self.assertFalse(enviado['ultima_ronda'])
        with mock.patch(LLAMAR, return_value=propuesta_materiales()):
            for _ in range(2):
                self.assertEqual(self.json(self.url(b, 'proponer/')).status_code, 200)
        with mock.patch(LLAMAR, return_value=propuesta_materiales()) as ll:
            self.assertEqual(self.json(self.url(b, 'proponer/')).status_code, 429)  # ya usó la 1.ª propuesta + 3 repeticiones
        self.assertFalse(ConsumoAPU.objects.exists())                                # ninguna ronda cobra

    def test_lo_respondido_en_un_paso_se_envia_como_aclaraciones_a_los_otros(self):
        b = self.borrador(paso=3, consultas={
            'materiales': {'historial': [{'pregunta': '¿Qué armadura?', 'respuesta': 'Barras corrugadas'}],
                           'decisiones': {'c1': {'pregunta': '¿Encofrado?', 'elegida': 'Incluir', 'clave': 'si'}}},
            'mano_obra': {'historial': [{'pregunta': 'solo de este paso', 'respuesta': 'x'}]}})
        self.assertEqual(asistente.aclaraciones(b, 'mano_obra'), [
            {'pregunta': '¿Qué armadura?', 'respuesta': 'Barras corrugadas'}, {'pregunta': '¿Encofrado?', 'respuesta': 'Incluir'}])
        with mock.patch(LLAMAR, return_value=propuesta_materiales()) as ll:
            self.json(self.url(b, 'proponer/', 'mano-obra'), {}, self.coord)
        self.assertEqual(len(ll.call_args[0][1]['aclaraciones']), 2)                 # no incluye las del propio paso

    def test_una_respuesta_solo_con_preguntas_es_valida_pero_vacia_no(self):
        b = self.borrador(paso=2)
        with mock.patch(LLAMAR, return_value={'filas': [], 'consultas': [{'id': 'c1', 'tipo': 'dato', 'pregunta': '¿Altura?'}]}):
            self.assertEqual(self.json(self.url(b, 'proponer/'), {}, self.coord).status_code, 200)
        with mock.patch(LLAMAR, return_value={'filas': [], 'consultas': []}):
            self.assertEqual(self.json(self.url(b, 'proponer/'), {}).status_code, 502)

    def test_otro_usuario_de_otra_empresa_no_ve_el_borrador(self):
        b = self.borrador(paso=2)
        self.client.force_login(self.ajeno)
        self.assertEqual(self.client.get(self.url(b)).status_code, 403)


class ResultadoTests(Base):
    def test_precio_unitario_coincide_con_el_motor(self):
        b = self.borrador_en_paso5()
        prev = asistente.previsualizar(b)
        grupos = {'MAT': D('38') * D('1.05') * D('1.5'), 'MO': D('0.5') * D('20'), 'EQ': D('0.1') * D('10')}
        from apu_motor import calcular
        esperado = calcular(self.pa.perfil_efectivo(), grupos)
        self.assertEqual(prev['resultado'].total, esperado.total)
        self.assertEqual(prev['sin_precio'], [])

    def test_guardar_cobra_una_vez_crea_el_apu_y_no_se_duplica(self):
        b = self.borrador_en_paso5()
        r = self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.coord)
        self.assertEqual(r.status_code, 200)
        item = ItemModelo.objects.get()
        self.assertEqual((item.proyecto, item.codigo, item.categoria.nombre), (self.proyecto, 'APU-001', 'Obra gruesa'))
        self.assertEqual(item.lineas.count(), 3)
        self.assertEqual(item.lineas.get(insumo__tipo='MO').ayuda['personas'], '2')
        self.assertEqual(ConsumoAPU.objects.filter(tipo='generar').count(), 1)
        self.assertEqual(self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/').status_code, 200)   # idempotente
        self.assertEqual((ItemModelo.objects.count(), ConsumoAPU.objects.count()), (1, 1))
        self.assertEqual(self.client.get(f'/tekon/apu/borrador/{b.pk}/resultado/').status_code, 302)

    def test_el_precio_unitario_de_la_ficha_usa_las_incidencias_del_proyecto(self):
        b = self.borrador_en_paso5()
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.coord)
        item = ItemModelo.objects.get()
        antes = calculo.analizar(item).total
        self.pa.ajustes = {'GG': '0.20'}
        self.pa.save()
        self.assertGreater(calculo.analizar(item).total, antes)
        otro = Proyecto.objects.create(empresa=self.a, nombre='Otro proyecto', descripcion=DESCRIPCION)
        ProyectoAPU.objects.create(proyecto=otro, perfil=self.perfil)
        copia = ItemModelo.objects.create(empresa=self.a, proyecto=otro, codigo='APU-001', descripcion='x', unidad='m2')
        for l in item.lineas.all():
            LineaComposicion.objects.create(item=copia, insumo=l.insumo, cantidad=l.cantidad, desperdicio_pct=l.desperdicio_pct)
        self.assertEqual(calculo.analizar(copia).total, antes)                      # el otro proyecto no cambia

    def test_si_falla_el_guardado_se_devuelve_el_credito(self):
        b = self.borrador_en_paso5()
        with mock.patch('apu_generador.asistente._crear_o_actualizar_apu', side_effect=RuntimeError('boom')):
            self.client.force_login(self.coord)
            with self.assertRaises(RuntimeError):
                self.client.post(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', '{}', content_type='application/json')
        b.refresh_from_db()
        self.assertEqual((ConsumoAPU.objects.count(), b.credito_consumido), (0, False))

    def test_cargar_precio_de_un_insumo_sin_precio(self):
        b = self.borrador_en_paso5()
        nuevo = self.insumo('MAT-050', 'Arena', unidad='m3')
        r = self.json(f'/tekon/apu/borrador/{b.pk}/precio/', {'insumo': nuevo.pk, 'precio': '85,5', 'moneda': 'bob'}, self.coord)
        self.assertEqual(r.status_code, 200)
        p = PrecioInsumo.objects.get(insumo=nuevo)
        self.assertEqual((p.precio, p.moneda), (D('85.5'), 'BOB'))
        ajeno = self.insumo('MAT-051', 'X', empresa=self.b)
        self.assertEqual(self.json(f'/tekon/apu/borrador/{b.pk}/precio/', {'insumo': ajeno.pk, 'precio': '1', 'moneda': 'BOB'}).status_code, 400)

    def test_la_pagina_tiene_las_zonas_que_el_js_refresca_sin_recargar(self):
        b = self.borrador_en_paso5()
        self.client.force_login(self.coord)
        html = self.client.get(f'/tekon/apu/borrador/{b.pk}/resultado/').content.decode()
        self.assertEqual(html.count('data-zona="composicion"'), 1)
        self.assertEqual(html.count('data-zona="precio"'), 1)
        self.assertEqual(html.count('<div'), html.count('</div>'))                      # el HTML quedó bien anidado
        self.assertEqual(html.count('<section'), html.count('</section>'))
        self.assertLess(html.index('data-progreso'), html.index('data-zona="composicion"'))   # el progreso queda fuera de la zona

    def test_pagina_de_resultado_muestra_composicion_y_precio(self):
        b = self.borrador_en_paso5()
        self.client.force_login(self.coord)
        r = self.client.get(f'/tekon/apu/borrador/{b.pk}/resultado/')
        self.assertContains(r, 'Ladrillo 6H')
        self.assertContains(r, 'Precio unitario')


class HabilitarTests(Base):
    URL = '/tekon/apu/proyectos/habilitar/'

    def setUp(self):
        super().setUp()
        self.nuevo = Proyecto.objects.create(empresa=self.a, nombre='Colegio Norte', descripcion='')

    def datos(self, **kw):
        d = {'proyecto': self.nuevo.pk, 'perfil': self.perfil.pk, 'descripcion': DESCRIPCION}
        d.update(kw)
        return d

    def test_habilitar_crea_el_perfil_propio_y_guarda_la_descripcion(self):
        self.client.force_login(self.coord)
        r = self.client.post(self.URL, self.datos())
        self.assertRedirects(r, '/tekon/apu/generar/', fetch_redirect_response=False)
        pa = ProyectoAPU.objects.get(proyecto=self.nuevo)
        self.assertEqual((pa.perfil.empresa, pa.perfil.nombre), (self.a, self.perfil.nombre))    # copia de la plantilla, de la empresa
        self.nuevo.refresh_from_db()
        self.assertEqual(self.nuevo.descripcion, DESCRIPCION)

    def test_habilitar_guarda_la_region_de_precios_del_proyecto(self):
        self.client.force_login(self.coord)
        self.client.post(self.URL, self.datos(region='  Tarija '))
        self.assertEqual(ProyectoAPU.objects.get(proyecto=self.nuevo).region, 'Tarija')
        self.assertContains(self.client.get('/tekon/apu/proyectos/'), 'Tarija')

    def test_otro_proyecto_con_la_misma_plantilla_reutiliza_la_copia(self):
        otro = Proyecto.objects.create(empresa=self.a, nombre='Colegio Sur')
        self.client.force_login(self.coord)
        self.client.post(self.URL, self.datos())
        self.client.post(self.URL, self.datos(proyecto=otro.pk))
        self.assertEqual(PerfilCalculo.objects.filter(empresa=self.a, nombre=self.perfil.nombre).count(), 1)

    def test_exige_una_descripcion_suficiente_y_no_habilita_sin_ella(self):
        self.client.force_login(self.coord)
        r = self.client.post(self.URL, self.datos(descripcion='Una escuela'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'al menos 15 palabras')
        self.assertFalse(ProyectoAPU.objects.filter(proyecto=self.nuevo).exists())

    def test_no_ofrece_ni_acepta_perfiles_o_proyectos_de_otra_empresa(self):
        ajeno = self.perfil.copiar_a(self.b)
        self.client.force_login(self.coord)
        r = self.client.post(self.URL, self.datos(perfil=ajeno.pk))
        self.assertContains(r, 'no existe')
        self.assertFalse(ProyectoAPU.objects.filter(proyecto=self.nuevo).exists())
        r = self.client.post(self.URL, self.datos(proyecto=self.proyecto_b.pk))
        self.assertContains(r, 'Elige un proyecto')
        self.assertFalse(ProyectoAPU.objects.filter(proyecto=self.proyecto_b).exists())

    def test_solo_quien_gestiona_perfiles_habilita(self):
        self.client.force_login(self.ejec)
        self.assertEqual(self.client.get(self.URL).status_code, 403)
        self.assertEqual(self.client.post(self.URL, self.datos()).status_code, 403)

    def test_los_proyectos_ya_habilitados_no_se_ofrecen(self):
        self.client.force_login(self.coord)
        r = self.client.get(self.URL)
        self.assertContains(r, 'Colegio Norte')
        self.assertNotContains(r, 'Escuela Tarija')

    def test_sin_proyectos_habilitados_nuevo_apu_lleva_primero_a_habilitar(self):
        ProyectoAPU.objects.all().delete()
        self.client.force_login(self.coord)
        self.assertRedirects(self.client.get('/tekon/apu/generar/'), self.URL, fetch_redirect_response=False)
        self.assertContains(self.client.get('/tekon/apu/'), 'habilita un proyecto')
        self.client.force_login(self.ejec)                                              # sin permiso: se le explica
        self.assertRedirects(self.client.get('/tekon/apu/generar/'), '/tekon/apu/', fetch_redirect_response=False)
        self.assertContains(self.client.get('/tekon/apu/'), 'Todavía no hay proyectos habilitados')

    def test_sin_ningun_proyecto_en_la_empresa_se_explica_como_crear_uno(self):
        ProyectoAPU.objects.all().delete()
        Proyecto.objects.filter(empresa=self.a).delete()
        self.client.force_login(self.coord)
        self.assertContains(self.client.get(self.URL), 'Todavía no hay proyectos')

    def test_reutilizar_solo_en_proyectos_habilitados(self):
        b = self.borrador_en_paso5()
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.coord)
        item = ItemModelo.objects.get()
        r = self.json(f'/tekon/apu/lista/{item.pk}/reutilizar/', {'proyecto': self.nuevo.pk})
        self.assertEqual(r.status_code, 400)
        self.assertIn('habilitado', r.json()['message'])


class PreciosEstimadosTests(Base):
    """La IA estima precios como RECOMENDACIÓN: no se guardan solos, no cobran y se marcan como «estimado»."""

    def setUp(self):
        super().setUp()
        self.b = self.borrador_en_paso5()
        self.sin = self.insumo('MAT-050', 'Arena', unidad='m3')
        self.b.materiales = {'filas': self.b.materiales['filas'] + [
            {'descripcion': 'Arena', 'unidad': 'm3', 'cantidad': '0.1', 'insumo_id': self.sin.pk, 'check': True}]}
        self.b.save()
        self.url = f'/tekon/apu/borrador/{self.b.pk}/sugerir-precios/'
        self.respuesta = {'precios': [
            {'id': self.sin.pk, 'precio': 85.5, 'moneda': 'bob', 'confianza': 'media', 'fuente': 'Ferretería X', 'nota': 'sin IVA'},
            {'id': 99999, 'precio': 10, 'moneda': 'BOB', 'confianza': 'alta'},                  # insumo que no se pidió
            {'id': self.sin.pk + 1000, 'precio': -3, 'moneda': 'BOB', 'confianza': 'alta'}]}

    def test_sugiere_solo_para_los_insumos_sin_precio_sin_guardar_ni_cobrar(self):
        with mock.patch(LLAMAR, return_value=self.respuesta) as ll:
            r = self.json(self.url, {}, self.coord).json()
        enviado = ll.call_args[0][1]
        self.assertEqual([i['id'] for i in enviado['insumos']], [self.sin.pk])              # los que ya tienen precio no se piden
        self.assertEqual((enviado['moneda'], enviado['region'], 'pais' in json.dumps(enviado).lower()), ('BOB', '', False))
        self.assertEqual(list(r['sugerencias']), [str(self.sin.pk)])                           # el id ajeno y el precio negativo se descartan
        sug = r['sugerencias'][str(self.sin.pk)]
        self.assertEqual((sug['precio'], sug['moneda'], sug['confianza'], sug['fuente']), ('85.5', 'BOB', 'media', 'Ferretería X'))
        self.assertFalse(PrecioInsumo.objects.filter(insumo=self.sin).exists())               # recomendación: nada se guarda solo
        self.assertFalse(ConsumoAPU.objects.exists())                                           # y no cobra créditos
        self.assertEqual(LlamadaIA.objects.get().webhook, 'apu-precios')

    def test_usar_una_sugerencia_deja_el_precio_marcado_como_estimado(self):
        self.json(f'/tekon/apu/borrador/{self.b.pk}/precio/',
                  {'insumo': self.sin.pk, 'precio': '85.5', 'moneda': 'BOB', 'estimado': True, 'fuente': 'Ferretería X'}, self.coord)
        p = PrecioInsumo.objects.get(insumo=self.sin)
        self.assertEqual((p.estimado, p.fuente), (True, 'Ferretería X'))
        pag = self.client.get(f'/tekon/apu/borrador/{self.b.pk}/resultado/')
        self.assertContains(pag, 'Estimado')
        self.assertContains(pag, 'estimado')                                                    # aviso: confírmalos con precios reales
        # corregir el valor a mano lo vuelve un precio normal
        self.json(f'/tekon/apu/borrador/{self.b.pk}/precio/', {'insumo': self.sin.pk, 'precio': '90', 'moneda': 'BOB'})
        self.assertFalse(PrecioInsumo.objects.get(insumo=self.sin).estimado)

    def test_con_insumos_sin_precio_la_pagina_tambien_queda_bien_anidada(self):
        self.client.force_login(self.coord)
        html = self.client.get(f'/tekon/apu/borrador/{self.b.pk}/resultado/').content.decode()
        self.assertIn('data-accion="sugerir-precios"', html)
        self.assertIn('data-precio-fila', html)
        self.assertEqual(html.count('<div'), html.count('</div>'))
        self.assertLess(html.index('data-progreso'), html.index('data-zona="composicion"'))
        self.assertLess(html.index('data-zona="composicion"'), html.index('data-accion="sugerir-precios"'))   # el botón se refresca con la zona
        self.assertLess(html.index('data-precio-fila'), html.index('data-zona="precio"'))

    def test_la_ficha_y_los_insumos_muestran_el_precio_estimado(self):
        PrecioInsumo.objects.create(insumo=self.sin, fecha=date(2026, 1, 1), precio=D('85'), moneda='BOB', estimado=True)
        self.json(f'/tekon/apu/borrador/{self.b.pk}/guardar-apu/', {}, self.coord)
        item = ItemModelo.objects.get()
        self.assertContains(self.client.get(f'/tekon/apu/lista/{item.pk}/'), 'Estimado')
        self.assertContains(self.client.get('/tekon/apu/insumos/'), 'Estimado')

    def test_si_todo_tiene_precio_no_hay_nada_que_sugerir(self):
        PrecioInsumo.objects.create(insumo=self.sin, fecha=date(2026, 1, 1), precio=D('85'), moneda='BOB')
        with mock.patch(LLAMAR, return_value=self.respuesta) as ll:
            r = self.json(self.url, {}, self.coord)
        self.assertEqual(r.status_code, 400)
        ll.assert_not_called()

    def test_maximo_de_pedidos_por_borrador_y_fallos_de_n8n(self):
        with mock.patch(LLAMAR, side_effect=N8NError('El servicio de IA tardó demasiado en responder.')):
            self.assertEqual(self.json(self.url, {}, self.coord).status_code, 502)
        with mock.patch(LLAMAR, return_value=self.respuesta):
            for _ in range(3):
                self.assertEqual(self.json(self.url, {}).status_code, 200)
            self.assertEqual(self.json(self.url, {}).status_code, 429)

    def test_el_superusuario_no_tiene_tope_de_sugerencias(self):
        with mock.patch(LLAMAR, return_value=self.respuesta):
            for _ in range(MAX_SUGERENCIAS_PRUEBA + 2):
                self.assertEqual(self.json(self.url, {}, self.su).status_code, 200)

    def test_respuesta_sin_precios_utiles_y_permisos(self):
        with mock.patch(LLAMAR, return_value={'precios': [{'id': 99999, 'precio': 5, 'moneda': 'BOB', 'confianza': 'alta'}]}):
            self.assertEqual(self.json(self.url, {}, self.coord).status_code, 502)
        self.assertEqual(self.json(self.url, {}, self.obs).status_code, 403)

    def test_los_numeros_nunca_salen_en_notacion_cientifica(self):
        r = ia.normalizar_precios({'precios': [{'id': 1, 'precio': 830, 'moneda': 'BOB', 'confianza': 'alta'},
                                               {'id': 2, 'precio': 1200000, 'moneda': 'BOB', 'confianza': 'alta'},
                                               {'id': 3, 'precio': 85.50, 'moneda': 'BOB', 'confianza': 'alta'},
                                               {'id': 4, 'precio': 0.0000012, 'moneda': 'BOB', 'confianza': 'alta'}]}, {1, 2, 3, 4}, 'BOB')
        self.assertEqual([r[i]['precio'] for i in (1, 2, 3, 4)], ['830', '1200000', '85.5', '0.0000012'])
        fila = ia.normalizar_fila({'descripcion': 'Ladrillo', 'unidad': 'pza', 'cantidad': 100, 'desperdicio_pct': 10}, 'materiales')
        self.assertEqual((fila['cantidad'], fila['desperdicio_pct']), ('100', '10'))

    def test_normalizar_precios(self):
        r = ia.normalizar_precios({'precios': [{'id': '7', 'precio': '1,5', 'moneda': 'clp', 'confianza': 'rara'}, 'basura', {'id': None}]}, {7}, 'BOB')
        self.assertEqual(r, {7: {'precio': '1.5', 'moneda': 'CLP', 'confianza': 'baja', 'fuente': '', 'nota': ''}})


class CreditosTests(Base):
    def consumir(self, user, n=1, empresa=None):
        for i in range(n):
            creditos.consumir(user, empresa or self.a, 'generar', f'x{i}')

    def test_limite_personal_3_por_dia_y_10_por_mes(self):
        self.consumir(self.ejec, 3)
        ok, motivo = creditos.puede_consumir(self.ejec, self.a)
        self.assertFalse(ok)
        self.assertIn('3 de 3 APU hoy', motivo)
        with self.assertRaises(creditos.SinCreditos):
            self.consumir(self.ejec)
        # 10 en el mes aunque en días distintos
        ConsumoAPU.objects.filter(usuario=self.ejec).delete()
        inicio_mes = creditos._inicios()[1] + timedelta(minutes=1)                 # dentro del mes (hora local)
        for i in range(10):
            c = ConsumoAPU.objects.create(empresa=self.a, usuario=self.ejec, tipo='generar')
            ConsumoAPU.objects.filter(pk=c.pk).update(fecha=inicio_mes)
        ok, motivo = creditos.puede_consumir(self.ejec, self.a)
        self.assertFalse(ok)
        self.assertIn('10 de 10 APU este mes', motivo)

    def test_limite_configurado_por_persona(self):
        LimiteAPU.objects.create(membresia=self.m_ejec, max_dia=1, max_mes=5)
        self.consumir(self.ejec)
        self.assertFalse(creditos.puede_consumir(self.ejec, self.a)[0])
        self.assertTrue(creditos.puede_consumir(self.coord, self.a)[0])

    def test_si_la_empresa_agota_su_limite_nadie_genera_aunque_tenga_creditos(self):
        LimiteEmpresaAPU.objects.create(empresa=self.a, max_dia=2, max_mes=50)
        self.consumir(self.coord, 2)
        ok, motivo = creditos.puede_consumir(self.ejec, self.a)                      # el ejecutor no usó ninguno
        self.assertFalse(ok)
        self.assertIn('La empresa agotó sus 2 APU de hoy', motivo)
        with self.assertRaises(creditos.SinCreditos):
            self.consumir(self.ejec)
        r = self.json('/tekon/apu/generar/', {'proyecto': self.proyecto.pk, 'actividad': 'x', 'unidad': 'm2'}, self.ejec)
        self.assertEqual(r.status_code, 402)
        self.assertFalse(APUBorrador.objects.exists())

    def test_limite_de_empresa_mensual_y_desactivable(self):
        LimiteEmpresaAPU.objects.create(empresa=self.a, max_dia=99, max_mes=1)
        self.consumir(self.coord)
        self.assertIn('este mes', creditos.puede_consumir(self.ejec, self.a)[1])
        LimiteEmpresaAPU.objects.filter(empresa=self.a).update(activo=False)
        self.assertTrue(creditos.puede_consumir(self.ejec, self.a)[0])

    def test_el_administrador_no_tiene_limite_personal_pero_consume_el_de_la_empresa(self):
        self.consumir(self.adm, 5)                                                   # más que el límite personal (3/día)
        self.assertEqual(ConsumoAPU.objects.filter(usuario=self.adm).count(), 5)
        LimiteEmpresaAPU.objects.update_or_create(empresa=self.a, defaults={'max_dia': 5, 'max_mes': 50})
        self.assertFalse(creditos.puede_consumir(self.adm, self.a)[0])

    def test_el_superusuario_no_consume_ni_tiene_limite(self):
        LimiteEmpresaAPU.objects.create(empresa=self.a, max_dia=0, max_mes=0)
        self.assertTrue(creditos.puede_consumir(self.su, self.a)[0])
        self.assertIsNone(creditos.consumir(self.su, self.a, 'generar', 'x'))
        self.assertFalse(ConsumoAPU.objects.exists())

    def test_revertir_devuelve_el_credito(self):
        self.consumir(self.ejec)
        creditos.revertir(self.ejec, self.a, 'generar', 'x0')
        self.assertFalse(ConsumoAPU.objects.exists())

    def test_las_empresas_no_comparten_consumo(self):
        self.consumir(self.coord, 2)
        self.assertEqual(creditos.usado_empresa(self.b), (0, 0))

    def test_resumen(self):
        self.consumir(self.ejec)
        r = creditos.resumen(self.ejec, self.a)
        self.assertEqual(r['persona'], (1, 3, 1, 10))
        self.assertEqual(r['empresa'], (1, 20, 1, 100))
        self.assertEqual(creditos.resumen(self.su, self.a), {'persona': None, 'empresa': None})


class JornadaTests(Base):
    def test_sin_jornada_en_curso_se_bloquea_todo_el_modulo(self):
        self.client.force_login(self.ejec_c)
        r = self.client.get('/conjor/apu/')
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, 'Inicia tu jornada', status_code=403)
        self.assertEqual(self.client.get('/conjor/apu/perfiles/1/').status_code, 403)
        ajax = self.client.post('/conjor/apu/generar/', '{}', content_type='application/json')
        self.assertEqual(ajax.status_code, 403)
        self.assertIn('jornada', ajax.json()['message'])

    def test_con_jornada_en_curso_entra(self):
        from jor_diario.models import Jornada
        from jor_empleados.models import Perfil
        Jornada.objects.create(empresa=self.c, perfil=Perfil.de(self.m_ejec_c), inicio=timezone.now())
        self.client.force_login(self.ejec_c)
        self.assertEqual(self.client.get('/conjor/apu/').status_code, 200)

    def test_jornada_completada_no_sirve(self):
        from jor_diario.models import Jornada
        from jor_empleados.models import Perfil
        Jornada.objects.create(empresa=self.c, perfil=Perfil.de(self.m_ejec_c), inicio=timezone.now(), estado='completada')
        self.client.force_login(self.ejec_c)
        self.assertEqual(self.client.get('/conjor/apu/').status_code, 403)

    def test_superusuario_y_administrador_estan_exentos(self):
        adm = User.objects.create_user('admc@example.com', 'x')
        agregar_miembro(adm, self.c, rol_por_base(self.c, RolBase.MIEMBRO))
        adm.empresas_administradas.add(self.c)
        for u in (self.su, adm):
            self.client.force_login(u)
            self.assertEqual(self.client.get('/conjor/apu/').status_code, 200, u)

    def test_empresa_sin_asistencia_no_tiene_la_restriccion(self):
        self.client.force_login(self.ejec)
        self.assertEqual(self.client.get('/tekon/apu/').status_code, 200)


class MenuYPermisosTests(Base):
    def menu(self, user, url='/tekon/apu/'):
        self.client.force_login(user)
        return {i['nombre']: i for i in self.client.get(url).context['menu_lateral']}

    def test_usuarios_solo_para_superusuario_y_administradores_con_contorno_rosa(self):
        self.assertNotIn('Usuarios', self.menu(self.coord))
        self.assertNotIn('Usuarios', self.menu(self.ejec))
        self.assertEqual(self.menu(self.adm)['Usuarios']['nivel'], 'administrador')
        self.assertIn('Usuarios', self.menu(self.su))
        self.assertEqual(self.client.get('/tekon/apu/').status_code, 200)

    def test_consumo_ia_solo_superusuario(self):
        self.assertNotIn('Consumo IA', self.menu(self.adm))
        self.assertEqual(self.menu(self.su)['Consumo IA']['nivel'], 'superusuario')

    def test_el_coordinador_recibe_403_en_usuarios(self):
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get('/tekon/apu/usuarios/').status_code, 403)
        self.assertEqual(self.json('/tekon/apu/usuarios/%d/limite/' % self.m_ejec.pk, {'max_dia': 9, 'max_mes': 9}).status_code, 403)

    def test_el_administrador_edita_limites_de_personas_pero_no_el_de_la_empresa(self):
        self.client.force_login(self.adm)
        self.assertEqual(self.client.get('/tekon/apu/usuarios/').status_code, 200)
        r = self.json('/tekon/apu/usuarios/%d/limite/' % self.m_ejec.pk, {'max_dia': 7, 'max_mes': 20})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(LimiteAPU.objects.get(membresia=self.m_ejec).max_dia, 7)
        self.assertEqual(self.json('/tekon/apu/usuarios/empresa/', {'max_dia': 1, 'max_mes': 1}).status_code, 403)
        self.assertEqual(self.json('/tekon/apu/usuarios/%d/limite/' % self.m_ejec.pk, {'max_dia': 'x', 'max_mes': 1}).status_code, 400)

    def test_el_superusuario_edita_el_limite_de_la_empresa(self):
        r = self.json('/tekon/apu/usuarios/empresa/', {'max_dia': 4, 'max_mes': 30, 'activo': True}, self.su)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(LimiteEmpresaAPU.objects.get(empresa=self.a).max_mes, 30)

    def test_no_se_edita_la_membresia_de_otra_empresa(self):
        self.client.force_login(self.adm)
        self.assertEqual(self.json('/tekon/apu/usuarios/%d/limite/' % self.ajeno.membresias.first().pk, {'max_dia': 1, 'max_mes': 1}).status_code, 404)

    def test_el_lanzador_muestra_beta_y_no_proximamente(self):
        self.client.force_login(self.coord)
        tarjeta = next(m for m in self.client.get('/tekon/').context['lanzador_modulos'] if m['codigo'] == 'apu')
        self.assertTrue(tarjeta['beta'])
        self.assertEqual(tarjeta['estado'], 'disponible')
        r = self.client.get('/tekon/')
        self.assertContains(r, 'Beta')
        self.assertNotContains(r, 'Próximamente')


class IncidenciasTests(Base):
    URL = None

    def setUp(self):
        super().setUp()
        self.URL = f'/tekon/apu/proyectos/{self.proyecto.pk}/incidencias/'
        b = self.borrador_en_paso5()
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.coord)
        self.item = ItemModelo.objects.get()

    def post(self, **valores):
        datos = {'perfil': self.perfil.pk, 'accion': 'guardar'}
        datos.update(valores)
        self.client.force_login(self.coord)
        return self.client.post(self.URL, datos)

    def test_ajustar_gastos_generales_solo_en_este_proyecto(self):
        antes = calculo.analizar(self.item).total
        r = self.post(aj_GG='12')
        self.assertRedirects(r, '/tekon/apu/proyectos/', fetch_redirect_response=False)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.ajustes, {'GG': '0.12'})
        self.assertGreater(calculo.analizar(self.item).total, antes)
        self.assertEqual(self.perfil.datos['lineas'][[l['cod'] for l in self.perfil.datos['lineas']].index('GG')]['pct'], 0.10)  # el perfil base no cambia

    def test_la_region_de_precios_se_edita_en_incidencias(self):
        self.post(aj_GG='10', region='Santa Cruz')
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.region, 'Santa Cruz')
        self.assertContains(self.client.get(self.URL), 'Santa Cruz')

    def test_valores_iguales_al_perfil_base_no_son_ajustes(self):
        self.post(aj_GG='10')
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.ajustes, {})

    def test_restablecer_vuelve_al_valor_base(self):
        self.pa.ajustes = {'GG': '0.12'}
        self.pa.save()
        self.post(aj_GG='10')
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.ajustes, {})

    def test_valor_fuera_de_rango_no_guarda_y_muestra_el_error(self):
        self.pa.ajustes = {}
        r = self.post(aj_IT='1500')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'fuera de rango')
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.ajustes, {})
        r = self.post(aj_GG='abc')
        self.assertContains(r, 'Indica un número')

    def test_probar_muestra_la_vista_previa_sin_guardar(self):
        r = self.post(aj_GG='20', accion='probar')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['vista_previa'])
        v = r.context['vista_previa'][0]
        self.assertGreater(v['despues'], v['antes'])
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.ajustes, {})

    def test_codigo_huerfano_se_ignora(self):
        self.pa.ajustes = {'NO_EXISTE': '0.5', 'GG': '0.12'}
        self.pa.save()
        self.assertEqual(self.pa.ajustes_huerfanos(), ['NO_EXISTE'])
        self.assertTrue(self.pa.perfil_efectivo())                                  # no rompe el cálculo

    def test_solo_quien_gestiona_perfiles_edita(self):
        self.client.force_login(self.ejec)
        self.assertEqual(self.client.get(self.URL).status_code, 403)
        self.client.force_login(self.ajeno)
        self.assertEqual(self.client.get(self.URL).status_code, 403)


class ReutilizarTests(Base):
    def setUp(self):
        super().setUp()
        b = self.borrador_en_paso5()
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.coord)
        self.item = ItemModelo.objects.get()
        self.destino = Proyecto.objects.create(empresa=self.a, nombre='Colegio', descripcion=DESCRIPCION)
        ProyectoAPU.objects.create(proyecto=self.destino, perfil=self.perfil, ajustes={'GG': '0.15'})
        ConsumoAPU.objects.all().delete()

    def test_reutilizar_copia_al_proyecto_de_destino_y_cobra_un_credito(self):
        r = self.json(f'/tekon/apu/lista/{self.item.pk}/reutilizar/', {'proyecto': self.destino.pk}, self.coord)
        self.assertEqual(r.status_code, 200)
        b = APUBorrador.objects.get(modo='reutilizar')
        self.assertEqual((b.paso, b.origen, b.proyecto, b.credito_consumido), (5, self.item, self.destino, True))
        self.assertEqual(ConsumoAPU.objects.get().tipo, 'reutilizar')
        self.assertEqual(len(b.materiales['filas']) + len(b.mano_obra['filas']) + len(b.equipos['filas']), 3)
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {})
        copia = ItemModelo.objects.get(proyecto=self.destino)
        self.assertEqual((copia.origen, copia.lineas.count()), (self.item, 3))
        self.assertEqual(ConsumoAPU.objects.count(), 1)                              # guardar no vuelve a cobrar
        self.assertNotEqual(calculo.analizar(copia).total, calculo.analizar(self.item).total)   # usa las incidencias del destino

    def test_reutilizar_con_prompt_cobra_dos_y_deja_cambios_para_revisar(self):
        propuesta = {'resumen_cambios': 'Más desperdicio', 'materiales': {'filas': [
            {'descripcion': 'Ladrillo 6H', 'unidad': 'pza', 'cantidad': '38', 'desperdicio_pct': '8'}]},
            'mano_obra': {'filas': [{'descripcion': 'Albañil', 'personas': '2'}]}, 'equipos': {'filas': [{'descripcion': 'Mezcladora', 'cantidad': '0.1'}]}}
        with mock.patch(LLAMAR, return_value=propuesta):
            r = self.json(f'/tekon/apu/lista/{self.item.pk}/reutilizar/', {'proyecto': self.destino.pk, 'instruccion': 'sube el desperdicio'}, self.coord)
        self.assertEqual(r.status_code, 200)
        self.assertIn('/revision/', r.json()['continuar_url'])
        self.assertEqual(sorted(ConsumoAPU.objects.values_list('tipo', flat=True)), ['modificar', 'reutilizar'])
        b = APUBorrador.objects.get(modo='reutilizar')
        cambios = asistente.diferencias(b, b.instrucciones[0]['propuesta'])
        self.assertEqual([c['clase'] for c in cambios], ['cambiado'])               # solo cambió el desperdicio del ladrillo
        self.client.force_login(self.coord)
        self.assertContains(self.client.get(r.json()['continuar_url']), 'Más desperdicio')
        self.client.post(r.json()['continuar_url'], {'cambio': [cambios[0]['id']]})
        b.refresh_from_db()
        self.assertEqual(b.materiales['filas'][0]['desperdicio_pct'], '8')

    def test_si_la_ia_falla_al_modificar_se_devuelve_ese_credito(self):
        with mock.patch(LLAMAR, side_effect=N8NError('El servicio de IA tardó demasiado en responder.')):
            r = self.json(f'/tekon/apu/lista/{self.item.pk}/reutilizar/', {'proyecto': self.destino.pk, 'instruccion': 'cambia algo'}, self.coord)
        self.assertEqual(r.status_code, 502)
        self.assertEqual(list(ConsumoAPU.objects.values_list('tipo', flat=True)), ['reutilizar'])   # la copia sí se cobró

    def test_sin_cambios_no_cobra_la_modificacion(self):
        b = asistente.crear_borrador_reutilizado(self.item, self.proyecto, self.coord, self.a, edita_el_mismo=True)
        igual = {t: {'filas': getattr(b, t)['filas']} for t in ('materiales', 'mano_obra', 'equipos')}
        igual['mano_obra'].update(rendimiento=b.mano_obra['rendimiento'], horas_jornada=b.mano_obra['horas_jornada'])
        with mock.patch(LLAMAR, return_value=igual):
            r = self.json(f'/tekon/apu/borrador/{b.pk}/modificar/', {'instruccion': 'no cambies nada'}, self.coord)
        self.assertTrue(r.json().get('sin_cambios'))
        self.assertFalse(ConsumoAPU.objects.filter(tipo='modificar').exists())

    def test_modificar_desde_la_ficha_edita_el_mismo_apu(self):
        propuesta = {'materiales': {'filas': [{'descripcion': 'Ladrillo 6H', 'unidad': 'pza', 'cantidad': '40', 'desperdicio_pct': '5'}]},
                     'mano_obra': {'filas': [{'descripcion': 'Albañil', 'personas': '2'}]}, 'equipos': {'filas': [{'descripcion': 'Mezcladora', 'cantidad': '0.1'}]}}
        with mock.patch(LLAMAR, return_value=propuesta):
            r = self.json(f'/tekon/apu/lista/{self.item.pk}/modificar/', {'instruccion': 'usa 40 ladrillos'}, self.coord)
        self.assertEqual(r.status_code, 200)
        b = APUBorrador.objects.get(apu_guardado=self.item, modo='reutilizar')
        self.assertEqual(ConsumoAPU.objects.get().tipo, 'modificar')
        self.client.force_login(self.coord)
        self.client.post(f'/tekon/apu/borrador/{b.pk}/revision/', {'cambio': [c['id'] for c in asistente.diferencias(b, b.instrucciones[0]['propuesta'])]})
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {})
        self.assertEqual(ItemModelo.objects.count(), 1)                              # se actualizó, no se copió
        self.assertEqual(self.item.lineas.get(insumo__descripcion='Ladrillo 6H').cantidad, D('40'))
        self.assertEqual(ConsumoAPU.objects.count(), 1)

    def test_no_se_reutiliza_en_proyecto_ajeno_ni_apu_ajeno(self):
        self.assertEqual(self.json(f'/tekon/apu/lista/{self.item.pk}/reutilizar/', {'proyecto': self.proyecto_b.pk}, self.coord).status_code, 400)
        self.assertEqual(self.json(f'/tekon/apu/lista/{self.item.pk}/reutilizar/', {'proyecto': self.destino.pk}, self.ajeno).status_code, 403)

    def test_reutilizar_sin_credito_no_copia(self):
        LimiteAPU.objects.create(membresia=self.m_ejec, max_dia=0, max_mes=0)
        r = self.json(f'/tekon/apu/lista/{self.item.pk}/reutilizar/', {'proyecto': self.destino.pk}, self.ejec)
        self.assertEqual(r.status_code, 402)
        self.assertFalse(APUBorrador.objects.filter(modo='reutilizar').exists())


class TituloAlReutilizarTests(Base):
    """Al reutilizar o modificar un APU se verifica su título: la IA lo ajusta al prompt y la persona lo revisa."""

    def setUp(self):
        super().setUp()
        b = self.borrador_en_paso5(actividad='Hormigón H21 en columnas')
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.su)
        self.item = ItemModelo.objects.get()
        self.destino = Proyecto.objects.create(empresa=self.a, nombre='Colegio', descripcion=DESCRIPCION)
        ProyectoAPU.objects.create(proyecto=self.destino, perfil=self.perfil)

    def propuesta(self, titulo, cantidad='38'):
        return {'actividad': titulo, 'resumen_cambios': 'x',
                'materiales': {'filas': [{'descripcion': 'Ladrillo 6H', 'unidad': 'pza', 'cantidad': cantidad, 'desperdicio_pct': '5'}]},
                'mano_obra': {'filas': [{'descripcion': 'Albañil', 'personas': '2'}]},
                'equipos': {'filas': [{'descripcion': 'Mezcladora', 'cantidad': '0.1'}]}}

    def reutilizar(self, titulo, instruccion='cambia a vigas H25'):
        with mock.patch(LLAMAR, return_value=self.propuesta(titulo)):
            r = self.json(f'/tekon/apu/lista/{self.item.pk}/reutilizar/', {'proyecto': self.destino.pk, 'instruccion': instruccion}, self.su)
        return r, APUBorrador.objects.get(modo='reutilizar')

    def test_el_titulo_propuesto_aparece_como_un_cambio_mas_para_revisar(self):
        r, b = self.reutilizar('Hormigón H25 en vigas')
        self.assertEqual(r.status_code, 200)
        cambios = asistente.diferencias(b, b.instrucciones[0]['propuesta'])
        self.assertEqual(cambios[0]['id'], 'actividad')
        self.assertEqual((cambios[0]['anterior'], cambios[0]['nuevo']), ('Hormigón H21 en columnas', 'Hormigón H25 en vigas'))
        self.client.force_login(self.su)
        self.assertContains(self.client.get(r.json()['continuar_url']), 'value="Hormigón H25 en vigas"')        # editable

    def test_aplicar_el_cambio_de_titulo_lo_lleva_al_apu_guardado(self):
        r, b = self.reutilizar('Hormigón H25 en vigas')
        self.client.force_login(self.su)
        self.client.post(r.json()['continuar_url'], {'cambio': ['actividad']})
        b.refresh_from_db()
        self.assertEqual(b.actividad, 'Hormigón H25 en vigas')
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {'actividad': b.actividad})
        copia = ItemModelo.objects.get(proyecto=self.destino)
        self.assertEqual(copia.descripcion, 'Hormigón H25 en vigas')
        self.item.refresh_from_db()
        self.assertEqual(self.item.descripcion, 'Hormigón H21 en columnas')                       # el original no cambia

    def test_si_no_se_marca_el_cambio_el_titulo_se_conserva(self):
        r, b = self.reutilizar('Hormigón H25 en vigas')
        self.client.force_login(self.su)
        self.client.post(r.json()['continuar_url'], {'cambio': []})
        b.refresh_from_db()
        self.assertEqual(b.actividad, 'Hormigón H21 en columnas')

    def test_un_titulo_que_solo_cambia_la_unidad_o_el_formato_no_es_un_cambio(self):
        for titulo in ('Hormigón H21 en columnas (unidad: m3)', '  hormigón  h21 en  COLUMNAS ', 'Hormigón H21 en columnas (un. m3)', ''):
            self.assertEqual(asistente.diferencias(self.borrador(actividad='Hormigón H21 en columnas'), {'actividad': titulo}), [], titulo)
        self.assertEqual(asistente.limpiar_titulo('Muro de ladrillo (unidad: m2)'), 'Muro de ladrillo')
        self.assertEqual(asistente.limpiar_titulo('Muro (ladrillo visto) e=12'), 'Muro (ladrillo visto) e=12')   # otros paréntesis se respetan
        self.assertEqual(len(asistente.limpiar_titulo('x' * 500)), 200)

    def test_cambiar_solo_el_titulo_ya_cuenta_como_una_modificacion(self):
        with mock.patch(LLAMAR, return_value=self.propuesta('Hormigón H25 en vigas')):         # la composición propuesta es igual a la actual
            r = self.json(f'/tekon/apu/lista/{self.item.pk}/reutilizar/', {'proyecto': self.destino.pk, 'instruccion': 'cambia a vigas H25'}, self.coord)
        b = APUBorrador.objects.get(modo='reutilizar')
        self.assertEqual([c['id'] for c in asistente.diferencias(b, b.instrucciones[0]['propuesta'])][:1], ['actividad'])
        self.assertIn('/revision/', r.json()['continuar_url'])
        self.assertEqual(sorted(ConsumoAPU.objects.values_list('tipo', flat=True)), ['modificar', 'reutilizar'])   # se cobró: hubo un cambio real

    def test_sin_cambios_ni_de_titulo_no_cobra(self):
        b = asistente.crear_borrador_reutilizado(self.item, self.proyecto, self.su, self.a, edita_el_mismo=True)
        igual = {t: {'filas': getattr(b, t)['filas']} for t in ('materiales', 'mano_obra', 'equipos')}
        igual['mano_obra'].update(rendimiento=b.mano_obra['rendimiento'], horas_jornada=b.mano_obra['horas_jornada'])
        igual['actividad'] = 'Hormigón H21 en columnas'
        with mock.patch(LLAMAR, return_value=igual):
            r = self.json(f'/tekon/apu/borrador/{b.pk}/modificar/', {'instruccion': 'no cambies nada'}, self.su)
        self.assertTrue(r.json().get('sin_cambios'))

    def test_el_paso_5_deja_verificar_y_editar_el_titulo(self):
        r = self.json(f'/tekon/apu/lista/{self.item.pk}/reutilizar/', {'proyecto': self.destino.pk}, self.su)
        b = APUBorrador.objects.get(modo='reutilizar')
        pag = self.client.get(f'/tekon/apu/borrador/{b.pk}/resultado/')
        self.assertContains(pag, 'data-actividad')
        self.assertContains(pag, 'Título del APU')
        self.assertContains(pag, f'Reutilizado de')
        self.assertContains(pag, 'Hormigón H21 en columnas')
        self.assertEqual(self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {'actividad': 'x' * 201}).status_code, 400)
        self.assertEqual(self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {'actividad': '  Hormigón   H25 en   vigas '}).status_code, 200)
        self.assertEqual(ItemModelo.objects.get(proyecto=self.destino).descripcion, 'Hormigón H25 en vigas')

    # ── la columna «Detalle» de la revisión se puede editar ──
    def revision_con_cambios(self):
        propuesta = {'actividad': 'Hormigón H25 en vigas', 'resumen_cambios': 'x',
                     'materiales': {'filas': [{'descripcion': 'Ladrillo 6H', 'unidad': 'pza', 'cantidad': '40', 'desperdicio_pct': '5'},
                                              {'descripcion': 'Cemento portland', 'unidad': 'kg', 'cantidad': '5', 'desperdicio_pct': '2'}]},
                     'mano_obra': {'filas': [{'descripcion': 'Albañil', 'personas': '2'}], 'rendimiento': '12'},
                     'equipos': {'filas': []}}
        with mock.patch(LLAMAR, return_value=propuesta):
            r = self.json(f'/tekon/apu/lista/{self.item.pk}/reutilizar/', {'proyecto': self.destino.pk, 'instruccion': 'cambia varias cosas'}, self.su)
        b = APUBorrador.objects.get(modo='reutilizar')
        return b, r.json()['continuar_url']

    def test_la_revision_muestra_campos_editables_en_el_detalle(self):
        b, url = self.revision_con_cambios()
        ids = [c['id'] for c in asistente.diferencias(b, b.instrucciones[0]['propuesta'])]
        self.assertEqual(ids, ['actividad', 'materiales:~:ladrillo 6h', 'materiales:+:cemento portland', 'equipos:-:mezcladora', 'mano_obra:r:rendimiento'])
        self.client.force_login(self.su)
        html = self.client.get(url).content.decode()
        for campo in ('ed:actividad:valor', 'ed:materiales:~:ladrillo 6h:cantidad', 'ed:materiales:~:ladrillo 6h:desperdicio_pct',
                      'ed:materiales:+:cemento portland:descripcion', 'ed:materiales:+:cemento portland:cantidad', 'ed:mano_obra:r:rendimiento:valor'):
            self.assertIn(f'name="{campo}"', html)
        self.assertNotIn('ed:equipos:-:mezcladora', html)                                   # quitar no tiene nada que editar
        self.assertIn('value="Hormigón H25 en vigas"', html)
        self.assertIn('value="40"', html)

    def test_aplicar_con_valores_editados(self):
        b, url = self.revision_con_cambios()
        self.client.force_login(self.su)
        r = self.client.post(url, {
            'cambio': ['actividad', 'materiales:~:ladrillo 6h', 'materiales:+:cemento portland', 'mano_obra:r:rendimiento'],
            'ed:actividad:valor': ' Hormigón  H25 en vigas de entrepiso (unidad: m3)',
            'ed:materiales:~:ladrillo 6h:cantidad': '41,5', 'ed:materiales:~:ladrillo 6h:desperdicio_pct': '7',
            'ed:materiales:+:cemento portland:descripcion': 'Cemento Portland IP-40', 'ed:materiales:+:cemento portland:cantidad': '6,5',
            'ed:materiales:+:cemento portland:desperdicio_pct': '3', 'ed:mano_obra:r:rendimiento:valor': '10'})
        self.assertRedirects(r, f'/tekon/apu/borrador/{b.pk}/resultado/', fetch_redirect_response=False)
        b.refresh_from_db()
        self.assertEqual(b.actividad, 'Hormigón H25 en vigas de entrepiso')                  # editado y sin la unidad
        lad = next(f for f in b.materiales['filas'] if f['descripcion'] == 'Ladrillo 6H')
        self.assertEqual((lad['cantidad'], lad['desperdicio_pct']), ('41.5', '7'))
        cem = next(f for f in b.materiales['filas'] if f['descripcion'] == 'Cemento Portland IP-40')
        self.assertEqual((cem['cantidad'], cem['desperdicio_pct']), ('6.5', '3'))
        self.assertTrue(Insumo.objects.filter(empresa=self.a, descripcion='Cemento Portland IP-40').exists())   # entra al catálogo con lo editado
        self.assertFalse(Insumo.objects.filter(descripcion='Cemento portland').exists())
        self.assertEqual(b.mano_obra['rendimiento'], '10')
        self.assertTrue(b.filas('equipos'))                                                    # «quitar» no se marcó: la mezcladora sigue

    def test_sin_editar_se_aplica_lo_que_propuso_la_ia(self):
        b, url = self.revision_con_cambios()
        self.client.force_login(self.su)
        self.client.post(url, {'cambio': ['actividad', 'materiales:~:ladrillo 6h']})
        b.refresh_from_db()
        self.assertEqual(b.actividad, 'Hormigón H25 en vigas')
        self.assertEqual(next(f for f in b.materiales['filas'] if f['descripcion'] == 'Ladrillo 6H')['cantidad'], '40')

    def test_valores_invalidos_vuelven_a_mostrar_la_pagina_con_lo_escrito_y_no_aplican_nada(self):
        b, url = self.revision_con_cambios()
        self.client.force_login(self.su)
        r = self.client.post(url, {
            'cambio': ['actividad', 'materiales:~:ladrillo 6h', 'mano_obra:r:rendimiento'],
            'ed:actividad:valor': '  ', 'ed:materiales:~:ladrillo 6h:cantidad': 'abc', 'ed:materiales:~:ladrillo 6h:desperdicio_pct': '150',
            'ed:mano_obra:r:rendimiento:valor': '0'})
        self.assertEqual(r.status_code, 200)
        for texto in ('El título no puede quedar vacío', 'Indica una cantidad mayor que cero', 'Indica un número mayor que cero'):
            self.assertContains(r, texto)
        self.assertContains(r, 'value="abc"')                                                  # se conserva lo escrito
        html = r.content.decode()
        self.assertNotIn('checked aria-label="Aplicar: Agregar', html)
        b.refresh_from_db()
        self.assertEqual(b.actividad, 'Hormigón H21 en columnas')                              # nada se aplicó
        self.assertEqual(D(next(f for f in b.materiales['filas'] if f['descripcion'] == 'Ladrillo 6H')['cantidad']), D('38'))
        self.assertFalse(b.instrucciones[0]['aplicada'])

    def test_un_valor_invalido_en_un_cambio_sin_marcar_no_bloquea(self):
        b, url = self.revision_con_cambios()
        self.client.force_login(self.su)
        r = self.client.post(url, {'cambio': ['actividad'], 'ed:materiales:~:ladrillo 6h:cantidad': 'abc'})
        self.assertEqual(r.status_code, 302)
        b.refresh_from_db()
        self.assertEqual(b.actividad, 'Hormigón H25 en vigas')

    def test_un_titulo_vacio_conserva_el_actual(self):
        self.json(f'/tekon/apu/lista/{self.item.pk}/reutilizar/', {'proyecto': self.destino.pk}, self.su)
        b = APUBorrador.objects.get(modo='reutilizar')
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {'actividad': '   '})
        self.assertEqual(ItemModelo.objects.get(proyecto=self.destino).descripcion, 'Hormigón H21 en columnas')


class EliminarApuTests(Base):
    """Solo quien creó el APU y el superusuario pueden eliminarlo."""

    def setUp(self):
        super().setUp()
        b = self.borrador_en_paso5(creado_por=self.coord)
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.coord)
        self.item = ItemModelo.objects.get()
        self.url = f'/tekon/apu/lista/{self.item.pk}/eliminar/'
        self.otro_coord = User.objects.create_user('coord2@example.com', 'x')
        agregar_miembro(self.otro_coord, self.a, rol_por_base(self.a, RolBase.COORDINADOR))

    def post(self, usuario, url=None):
        self.client.force_login(usuario)
        return self.client.post(url or self.url)

    def test_el_creador_lo_elimina_con_su_composicion_pero_no_los_insumos_ni_precios(self):
        self.assertEqual(self.item.creado_por, self.coord)
        insumos, precios = Insumo.objects.count(), PrecioInsumo.objects.count()
        r = self.post(self.coord)
        self.assertRedirects(r, '/tekon/apu/lista/', fetch_redirect_response=False)
        self.assertFalse(ItemModelo.objects.exists())
        self.assertFalse(LineaComposicion.objects.exists())
        self.assertEqual((Insumo.objects.count(), PrecioInsumo.objects.count()), (insumos, precios))
        self.assertContains(self.client.get('/tekon/apu/lista/'), 'Se eliminó el APU')

    def test_el_superusuario_puede_eliminar_cualquier_apu(self):
        self.assertEqual(self.post(self.su).status_code, 302)
        self.assertFalse(ItemModelo.objects.exists())

    def test_nadie_mas_puede_ni_siquiera_otro_coordinador_o_administrador(self):
        for usuario in (self.otro_coord, self.adm, self.ejec, self.obs):
            self.assertEqual(self.post(usuario).status_code, 403, usuario)
        self.assertEqual(self.post(self.ajeno).status_code, 403)
        self.assertTrue(ItemModelo.objects.exists())

    def test_un_apu_sin_creador_solo_lo_elimina_el_superusuario(self):
        ItemModelo.objects.filter(pk=self.item.pk).update(creado_por=None)
        self.assertEqual(self.post(self.coord).status_code, 403)
        self.assertEqual(self.post(self.su).status_code, 302)

    def test_solo_por_post_y_solo_de_la_empresa_activa(self):
        self.client.force_login(self.coord)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.force_login(self.su)
        self.assertEqual(self.client.post(f'/embol/apu/lista/{self.item.pk}/eliminar/').status_code, 404)   # el APU es de Tekon
        self.assertTrue(ItemModelo.objects.exists())

    def test_si_otro_apu_lo_usa_como_sub_analisis_no_se_elimina(self):
        grande = ItemModelo.objects.create(empresa=self.a, proyecto=self.proyecto, codigo='APU-050', descripcion='Grande', unidad='m2')
        LineaComposicion.objects.create(item=grande, subitem=self.item, cantidad=D('1'))
        r = self.post(self.coord)
        self.assertRedirects(r, f'/tekon/apu/lista/{self.item.pk}/', fetch_redirect_response=False)
        self.assertTrue(ItemModelo.objects.filter(pk=self.item.pk).exists())
        self.assertContains(self.client.get(f'/tekon/apu/lista/{self.item.pk}/'), 'lo usan como sub-análisis APU-050')
        self.assertEqual(self.post(self.coord, f'/tekon/apu/lista/{grande.pk}/eliminar/').status_code, 403)   # no lo creó él (sin creador)
        self.post(self.su, f'/tekon/apu/lista/{grande.pk}/eliminar/')                                          # primero el que lo usa
        self.assertEqual(self.post(self.coord).status_code, 302)
        self.assertFalse(ItemModelo.objects.exists())

    def test_los_borradores_y_llamadas_a_la_ia_sobreviven(self):
        b = APUBorrador.objects.get()
        LlamadaIA.objects.create(empresa=self.a, webhook='apu-insumos', borrador=b, apu=self.item)
        self.post(self.coord)
        b.refresh_from_db()
        self.assertIsNone(b.apu_guardado)
        self.assertIsNone(LlamadaIA.objects.get().apu)

    def test_los_botones_solo_aparecen_para_quien_puede(self):
        for usuario, ve in ((self.coord, True), (self.su, True), (self.otro_coord, False), (self.ejec, False), (self.obs, False)):
            self.client.force_login(usuario)
            for url in ('/tekon/apu/lista/', f'/tekon/apu/lista/{self.item.pk}/'):
                html = self.client.get(url).content.decode()
                self.assertEqual(f'/tekon/apu/lista/{self.item.pk}/eliminar/' in html, ve, (usuario, url))


class PendientesPaginaTests(Base):
    URL = '/tekon/apu/pendientes/'

    def test_tarjeta_con_avance_por_pasos_creador_y_acciones(self):
        b = self.borrador(paso=3, actividad='Muro de ladrillo 6H', unidad='m2')
        self.client.force_login(self.coord)
        r = self.client.get(self.URL)
        self.assertContains(r, 'Muro de ladrillo 6H')
        self.assertContains(r, 'Escuela Tarija')
        self.assertContains(r, 'Paso 3 de 5')
        self.assertContains(r, 'Mano de obra')                                                  # el paso en que quedó
        self.assertContains(r, 'role="img" aria-label="Paso 3 de 5: Mano de obra"')
        self.assertContains(r, 'Tú')                                                            # lo creó quien mira
        self.assertContains(r, f'/tekon/apu/borrador/{b.pk}/continuar/')
        self.assertContains(r, f'/tekon/apu/borrador/{b.pk}/eliminar/')
        html = r.content.decode()
        barra = html.split('role="img"', 1)[1].split('</div>', 1)[0]
        self.assertEqual((barra.count('bg-primary"'), barra.count('bg-primary/40'), barra.count('bg-base-300')), (2, 1, 2))   # 2 hechos, 1 actual, 2 por hacer

    def test_reutilizado_y_pendiente_antiguo_se_indican(self):
        viejo = self.borrador(paso=2, modo='reutilizar', actividad='Antiguo')
        APUBorrador.objects.filter(pk=viejo.pk).update(actualizado=timezone.now() - timedelta(days=12))
        self.borrador(paso=2, actividad='Reciente')
        self.client.force_login(self.coord)
        r = self.client.get(self.URL)
        self.assertContains(r, 'Reutilizado')
        self.assertContains(r, 'Sin actividad hace 12 días')
        self.assertEqual(r.content.decode().count('Sin actividad hace'), 2)                      # una vez en el texto y otra en el atributo title
        self.assertEqual([b.antiguo for b in r.context['borradores']], [False, True])            # el más reciente primero

    def test_filtro_mios_solo_aparece_si_hay_de_otros_y_filtra(self):
        self.borrador(paso=2, actividad='Mío', creado_por=self.adm)
        self.client.force_login(self.adm)                                                        # un administrador ve los de todos
        self.assertNotContains(self.client.get(self.URL), 'Filtrar pendientes')                  # solo hay míos: sin filtro
        self.borrador(paso=2, actividad='De otro', creado_por=self.otro)
        r = self.client.get(self.URL)
        self.assertContains(r, 'Filtrar pendientes')
        self.assertEqual((r.context['n_todos'], r.context['n_mios']), (2, 1))
        r = self.client.get(self.URL + '?mios=1')
        self.assertEqual([b.actividad for b in r.context['borradores']], ['Mío'])
        self.assertNotContains(r, 'De otro')

    def test_estado_vacio_con_accion(self):
        self.client.force_login(self.coord)
        r = self.client.get(self.URL)
        self.assertContains(r, 'No tienes APU pendientes')
        self.assertContains(r, '/tekon/apu/generar/')
        self.client.get(self.URL + '?mios=1')                                                   # filtro sin resultados no rompe

    def test_los_de_otros_solo_los_ve_el_equipo_del_proyecto_o_un_administrador(self):
        self.borrador(paso=2, actividad='De otro', creado_por=self.otro)
        self.client.force_login(self.ejec)
        self.assertNotContains(self.client.get(self.URL), 'De otro')
        self.proyecto.equipo.add(self.m_ejec)
        self.assertContains(self.client.get(self.URL), 'De otro')
        self.client.force_login(self.adm)
        self.assertContains(self.client.get(self.URL), 'De otro')

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.otro = User.objects.create_user('otro2@example.com', 'x', first_name='Marta')
        agregar_miembro(cls.otro, cls.a, rol_por_base(cls.a, RolBase.MIEMBRO))


class UnidadYMotivoAlReutilizarTests(Base):
    """La IA también propone la unidad (si cambia lo que se mide) y explica por qué cambió el título; todo se revisa."""

    def setUp(self):
        super().setUp()
        b = self.borrador_en_paso5(actividad='Provisión e instalación de aire acondicionado', unidad='pza')
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.su)
        self.item = ItemModelo.objects.get()
        self.destino = Proyecto.objects.create(empresa=self.a, nombre='Colegio', descripcion=DESCRIPCION)
        ProyectoAPU.objects.create(proyecto=self.destino, perfil=self.perfil)

    def reutilizar(self, **extra):
        propuesta = {'actividad': 'Instalación de aire acondicionado', 'unidad': 'm2', 'motivo_titulo': 'Se eliminó la provisión del equipo.',
                     'resumen_cambios': 'x',
                     'materiales': {'filas': [{'descripcion': 'Ladrillo 6H', 'unidad': 'pza', 'cantidad': '38', 'desperdicio_pct': '5'}]},
                     'mano_obra': {'filas': [{'descripcion': 'Albañil', 'personas': '2'}]}, 'equipos': {'filas': [{'descripcion': 'Mezcladora', 'cantidad': '0.1'}]}}
        propuesta.update(extra)
        with mock.patch(LLAMAR, return_value=propuesta):
            r = self.json(f'/tekon/apu/lista/{self.item.pk}/reutilizar/', {'proyecto': self.destino.pk, 'instruccion': 'solo la instalación'}, self.su)
        return r, APUBorrador.objects.get(modo='reutilizar')

    def test_la_propuesta_guarda_unidad_y_motivo_y_ambos_son_cambios_para_revisar(self):
        r, b = self.reutilizar()
        prop = b.instrucciones[0]['propuesta']
        self.assertEqual((prop['unidad'], prop['motivo_titulo']), ('m²', 'Se eliminó la provisión del equipo.'))
        cambios = asistente.diferencias(b, prop)
        self.assertEqual([c['id'] for c in cambios][:2], ['actividad', 'unidad'])
        self.assertEqual((cambios[1]['anterior'], cambios[1]['nuevo']), ('pza', 'm²'))
        self.client.force_login(self.su)
        html = self.client.get(r.json()['continuar_url']).content.decode()
        self.assertIn('Se eliminó la provisión del equipo.', html)                              # el porqué del título, a la vista
        self.assertIn('name="ed:unidad:valor"', html)
        self.assertIn('value="Instalación de aire acondicionado"', html)

    def test_aplicar_la_unidad_editada_la_lleva_al_apu_guardado(self):
        r, b = self.reutilizar()
        self.client.force_login(self.su)
        self.client.post(r.json()['continuar_url'], {'cambio': ['actividad', 'unidad'], 'ed:unidad:valor': '  ml ', 'ed:actividad:valor': 'Instalación de aire acondicionado split'})
        b.refresh_from_db()
        self.assertEqual((b.actividad, b.unidad), ('Instalación de aire acondicionado split', 'ml'))
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {'actividad': b.actividad})
        copia = ItemModelo.objects.get(proyecto=self.destino)
        self.assertEqual((copia.descripcion, copia.unidad), ('Instalación de aire acondicionado split', 'ml'))
        self.item.refresh_from_db()
        self.assertEqual((self.item.descripcion, self.item.unidad), ('Provisión e instalación de aire acondicionado', 'pza'))   # el original no cambia

    def test_si_no_se_marca_la_unidad_se_conserva(self):
        r, b = self.reutilizar()
        self.client.force_login(self.su)
        self.client.post(r.json()['continuar_url'], {'cambio': ['actividad']})
        b.refresh_from_db()
        self.assertEqual(b.unidad, 'pza')

    def test_unidad_vacia_o_igual_no_es_valida_ni_es_un_cambio(self):
        r, b = self.reutilizar()
        self.client.force_login(self.su)
        malo = self.client.post(r.json()['continuar_url'], {'cambio': ['unidad'], 'ed:unidad:valor': '   '})
        self.assertEqual(malo.status_code, 200)
        self.assertContains(malo, 'La unidad no puede quedar vacía')
        b.refresh_from_db()
        self.assertEqual(b.unidad, 'pza')
        for unidad in (' PZA ', 'pza', ''):
            self.assertEqual([c['id'] for c in asistente.diferencias(b, {'unidad': unidad}) if c['id'] == 'unidad'], [], unidad)

    def test_un_workflow_viejo_sin_unidad_ni_motivo_no_rompe(self):
        r, b = self.reutilizar(unidad=None, motivo_titulo=None)
        self.assertEqual(r.status_code, 200)
        prop = b.instrucciones[0]['propuesta']
        self.assertEqual((prop['unidad'], prop['motivo_titulo']), ('', ''))
        self.assertEqual([c['id'] for c in asistente.diferencias(b, prop)], ['actividad'])
        self.client.force_login(self.su)
        self.assertEqual(self.client.get(r.json()['continuar_url']).status_code, 200)


class MotivoDeMedicionTests(Base):
    """Cuando no se pueden medir los tokens, se dice por qué (y no se insiste con cada llamada)."""

    def llamadas(self, n=3):
        return [LlamadaIA.objects.create(empresa=self.a, webhook='apu-insumos', ejecucion_id=str(100 + i)) for i in range(n)]

    def respuesta(self, codigo):
        return mock.Mock(status_code=codigo, **{'raise_for_status.return_value': None, 'json.return_value': {}})

    def test_sin_clave_la_medicion_esta_desactivada_y_lo_dice(self):
        ll = self.llamadas(1)
        self.assertEqual(ia.sincronizar_uso(ll), 0)
        self.assertIn('desactivada', ia.ESTADO_MEDICION['motivo'])

    @override_settings(N8N_API_URL='http://n8n:5678', N8N_API_KEY='mala')
    def test_clave_rechazada_se_avisa_y_se_deja_de_insistir(self):
        ll = self.llamadas(3)
        with mock.patch('apu_generador.ia.requests.get', return_value=self.respuesta(401)) as g:
            self.assertEqual(ia.sincronizar_uso(ll), 0)
        self.assertEqual(g.call_count, 1)                                                     # una sola prueba, no una por llamada
        self.assertIn('rechazó la clave de la API', ia.ESTADO_MEDICION['motivo'])
        self.assertIn('401', ia.ESTADO_MEDICION['motivo'])
        self.assertIn('http://n8n:5678', ia.ESTADO_MEDICION['motivo'])
        self.assertFalse(LlamadaIA.objects.exclude(uso__isnull=True).exists())                # siguen pendientes

    @override_settings(N8N_API_URL='http://n8n:5678', N8N_API_KEY='k')
    def test_sin_conexion(self):
        import requests
        ll = self.llamadas(3)
        with mock.patch('apu_generador.ia.requests.get', side_effect=requests.ConnectionError('x')) as g:
            self.assertEqual(ia.sincronizar_uso(ll), 0)
        self.assertEqual(g.call_count, 1)
        self.assertIn('No se pudo conectar con n8n en http://n8n:5678', ia.ESTADO_MEDICION['motivo'])

    @override_settings(N8N_API_URL='http://n8n:5678', N8N_API_KEY='k')
    def test_ejecuciones_que_n8n_ya_borro(self):
        ll = self.llamadas(2)
        with mock.patch('apu_generador.ia.requests.get', return_value=self.respuesta(404)):
            self.assertEqual(ia.sincronizar_uso(ll), 0)
        self.assertIn('ya no conserva 2 ejecución(es)', ia.ESTADO_MEDICION['motivo'])

    @override_settings(N8N_API_URL='http://n8n:5678', N8N_API_KEY='k')
    def test_al_medir_bien_el_motivo_se_limpia_y_el_resumen_lo_trae_solo_si_hay_pendientes(self):
        ll = self.llamadas(1)
        with mock.patch('apu_generador.ia.requests.get', return_value=self.respuesta(401)):
            ia.sincronizar_uso(ll)
        self.assertIn('rechazó', ia.resumen_uso(LlamadaIA.objects.all())['motivo'])
        ok = mock.Mock(status_code=200, **{'raise_for_status.return_value': None, 'json.return_value': TokensTests.EJECUCION})
        with mock.patch('apu_generador.ia.requests.get', return_value=ok):
            self.assertEqual(ia.sincronizar_uso(ll), 1)
        self.assertEqual(ia.ESTADO_MEDICION['motivo'], '')
        self.assertEqual(ia.resumen_uso(LlamadaIA.objects.all())['motivo'], '')

    @override_settings(N8N_API_URL='http://n8n:5678', N8N_API_KEY='mala')
    def test_la_ficha_del_apu_muestra_el_motivo_al_superusuario(self):
        b = self.borrador_en_paso5()
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.su)
        item = ItemModelo.objects.get()
        LlamadaIA.objects.create(empresa=self.a, webhook='apu-insumos', borrador=b, ejecucion_id='55')
        self.client.force_login(self.su)
        with mock.patch('apu_generador.ia.requests.get', return_value=self.respuesta(401)):
            r = self.client.get(f'/tekon/apu/lista/{item.pk}/')
        self.assertContains(r, '1 llamada pendiente de medir')
        self.assertContains(r, 'rechazó la clave de la API')


class CambiarProyectoEnElPaso1Tests(Base):
    """Mientras el paso 1 está pendiente, el proyecto del formulario manda: al comprobar de nuevo se usa el elegido."""

    def setUp(self):
        super().setUp()
        self.otro = Proyecto.objects.create(empresa=self.a, nombre='Colegio Norte', ciudad='Oruro',
                                            descripcion='Colegio de tres plantas en la ciudad de Oruro con aulas, laboratorios y canchas deportivas para estudiantes.')
        ProyectoAPU.objects.create(proyecto=self.otro, perfil=self.perfil, region='Oruro')
        with mock.patch(LLAMAR, return_value={'coherente': False, 'razon': 'x'}):
            self.json('/tekon/apu/generar/', {'proyecto': self.proyecto.pk, 'actividad': 'Muro', 'unidad': 'm2'}, self.coord)
        self.borrador = APUBorrador.objects.get()
        self.url = f'/tekon/apu/borrador/{self.borrador.pk}/actividad/'

    def comprobar(self, **datos):
        base = {'actividad': 'Muro', 'unidad': 'm2', 'descripcion': ''}
        base.update(datos)
        with mock.patch(LLAMAR, return_value=COHERENTE) as ll:
            r = self.json(self.url, base, self.coord)
        return r, ll

    def test_al_comprobar_de_nuevo_se_analiza_el_proyecto_elegido(self):
        r, ll = self.comprobar(proyecto=self.otro.pk)
        self.assertEqual(r.json()['estado'], 'ok')
        self.borrador.refresh_from_db()
        self.assertEqual((self.borrador.proyecto, self.borrador.region), (self.otro, 'Oruro'))
        enviado = ll.call_args[0][1]['proyecto']
        self.assertEqual((enviado['nombre'], enviado['ciudad']), ('Colegio Norte', 'Oruro'))       # a la IA le llega el nuevo, no el viejo
        self.assertEqual(ll.call_args[0][1]['region'], 'Oruro')
        self.assertEqual(APUBorrador.objects.count(), 1)                                            # el mismo borrador, no uno nuevo

    def test_sin_enviar_proyecto_se_conserva_el_del_borrador(self):
        self.comprobar()
        self.borrador.refresh_from_db()
        self.assertEqual(self.borrador.proyecto, self.proyecto)

    def test_proyectos_invalidos_se_rechazan_sin_cambiar_nada(self):
        sin_habilitar = Proyecto.objects.create(empresa=self.a, nombre='Sin habilitar', descripcion=DESCRIPCION)
        for pk in (sin_habilitar.pk, self.proyecto_b.pk, 999999):
            r, ll = self.comprobar(proyecto=pk)
            self.assertEqual(r.status_code, 400, pk)
            self.assertIn('habilitado', r.json()['message'])
            ll.assert_not_called()
        self.borrador.refresh_from_db()
        self.assertEqual(self.borrador.proyecto, self.proyecto)

    def test_el_proyecto_nuevo_tambien_debe_tener_descripcion_suficiente(self):
        corto = Proyecto.objects.create(empresa=self.a, nombre='Corto', descripcion='Una obra')
        ProyectoAPU.objects.create(proyecto=corto, perfil=self.perfil)
        r, ll = self.comprobar(proyecto=corto.pk)
        self.assertEqual(r.status_code, 400)
        self.assertIn('15 palabras', r.json()['message'])
        ll.assert_not_called()
        r, ll = self.comprobar(proyecto=corto.pk, proyecto_descripcion=DESCRIPCION)
        self.assertEqual(r.json()['estado'], 'ok')
        corto.refresh_from_db()
        self.assertEqual(corto.descripcion, DESCRIPCION)

    def test_la_pagina_del_borrador_deja_elegir_el_proyecto(self):
        self.client.force_login(self.coord)
        html = self.client.get(self.url).content.decode()
        select = html.split('<select name="proyecto"', 1)[1].split('</select>', 1)[0]
        self.assertNotIn('disabled', select.split('>', 1)[0])                                       # ya no está bloqueado
        self.assertIn('Colegio Norte', select)
        self.assertIn('Escuela Tarija', select)
        self.assertIn('selected', select)                                                           # viene elegido el actual
        self.assertNotIn('type="hidden" name="proyecto"', html)                                     # sin el campo oculto que lo pisaba


class PreguntasConRecomendacionTests(Base):
    """Toda pregunta de la IA llega con una respuesta recomendada (y su porqué), también las preguntas abiertas."""

    def norm(self, *consultas):
        return ia.normalizar_consultas(list(consultas))

    def test_una_pregunta_abierta_conserva_su_recomendacion_y_el_porque(self):
        c, = self.norm({'id': 'c1', 'tipo': 'dato', 'pregunta': '¿Qué resistencia?', 'recomendada': 'h25', 'por_que': '  Es la habitual en losas.  ',
                        'opciones': [{'clave': 'h21', 'etiqueta': 'H21'}, {'clave': 'h25', 'etiqueta': 'H25'}]})
        self.assertEqual((c['recomendada'], c['por_que']), ('h25', 'Es la habitual en losas.'))
        self.assertEqual([o['clave'] for o in c['opciones']], ['h21', 'h25'])

    def test_si_la_recomendada_viene_como_texto_se_enlaza_con_su_opcion(self):
        c, = self.norm({'id': 'c1', 'tipo': 'dato', 'pregunta': '¿Elemento?', 'recomendada': '  columnas ',
                        'opciones': [{'clave': 'v', 'etiqueta': 'Vigas'}, {'clave': 'c', 'etiqueta': 'Columnas'}]})
        self.assertEqual(c['recomendada'], 'c')

    def test_sin_recomendada_o_invalida_se_recomienda_la_primera_opcion(self):
        for crudo in ({}, {'recomendada': 'zzz'}, {'recomendada': ''}):
            c, = self.norm({'id': 'c1', 'tipo': 'dato', 'pregunta': '¿Uso?', 'opciones': ['Aulas', 'Oficinas'], **crudo})
            self.assertEqual(c['recomendada'], 'Aulas', crudo)                                   # la IA ordena de más a menos recomendable
        c, = self.norm({'id': 'c1', 'tipo': 'opciones', 'pregunta': '¿Cómo?', 'opciones': [{'clave': 'a', 'etiqueta': 'A'}, {'clave': 'b', 'etiqueta': 'B'}]})
        self.assertEqual(c['recomendada'], 'a')

    def test_una_pregunta_sin_opciones_pero_con_respuesta_recomendada_la_ofrece_como_opcion(self):
        c, = self.norm({'id': 'c1', 'tipo': 'dato', 'pregunta': '¿Altura?', 'recomendada': '2,70 m de piso a techo'})
        self.assertEqual(c['recomendada'], c['opciones'][0]['clave'])
        self.assertEqual(c['opciones'][0]['etiqueta'], '2,70 m de piso a techo')

    def test_sin_ninguna_recomendacion_posible_queda_vacia_sin_romper(self):
        c, = self.norm({'id': 'c1', 'tipo': 'dato', 'pregunta': '¿Altura?'})
        self.assertEqual((c['recomendada'], c['opciones'], c['por_que']), ('', [], ''))

    def test_el_endpoint_de_proponer_entrega_la_recomendacion_al_navegador(self):
        b = self.borrador(paso=2)
        crudo = {'filas': [], 'consultas': [{'id': 'c1', 'tipo': 'dato', 'pregunta': '¿Armadura?', 'recomendada': 'barras',
                                             'por_que': 'Es lo habitual en columnas.', 'opciones': [
                                                 {'clave': 'malla', 'etiqueta': 'Malla electrosoldada'}, {'clave': 'barras', 'etiqueta': 'Barras corrugadas'}]}]}
        with mock.patch(LLAMAR, return_value=crudo):
            r = self.json(f'/tekon/apu/borrador/{b.pk}/materiales/proponer/', {}, self.coord).json()
        c = r['propuesta']['consultas'][0]
        self.assertEqual((c['recomendada'], c['por_que']), ('barras', 'Es lo habitual en columnas.'))
        b.refresh_from_db()
        self.assertEqual(b.consultas['materiales']['propuesta']['consultas'][0]['recomendada'], 'barras')   # y queda guardada para retomar

    def test_el_workflow_exige_recomendar_en_cada_consulta(self):
        import json as _json
        from pathlib import Path
        wf = _json.loads((Path(__file__).resolve().parent.parent / 'n8n' / 'workflows' / 'APU_02-04insumos.json').read_text())
        esquema = _json.loads(next(n for n in wf['nodes'] if n['name'] == 'Esquema · Insumos')['parameters']['inputSchema'])
        items = esquema['properties']['consultas']['items']
        self.assertIn('recomendada', items['required'])
        self.assertIn('por_que', items['required'])
        for nombre in ('Prompt · Materiales', 'Prompt · Mano de obra', 'Prompt · Equipos'):
            texto = next(n for n in wf['nodes'] if n['name'] == nombre)['parameters']['assignments']['assignments'][0]['value']
            self.assertIn('RECOMENDAR SIEMPRE', texto, nombre)


class ProyectosResumenTests(Base):
    """APU → Proyectos: lista de proyectos y, del elegido, sus APU y el resumen (suma de precios unitarios, estado de los
    precios y desglose por categoría)."""
    URL = '/tekon/apu/proyectos/'

    def categoria(self, item, nombre):
        campo = ItemModelo._meta.get_field('categoria')
        if campo.is_relation:
            from apu_catalogo.models import CategoriaAPU
            item.categoria = CategoriaAPU.objects.get_or_create(empresa=item.empresa, nombre=nombre)[0]
        else:
            item.categoria = nombre
        item.save()

    def apu(self, proyecto, codigo, *insumos, categoria=''):
        item = ItemModelo.objects.create(empresa=self.a, proyecto=proyecto, codigo=codigo, descripcion=f'Descripción {codigo}', unidad='m2')
        for i in insumos:
            LineaComposicion.objects.create(item=item, insumo=i, cantidad=D('2'))
        if categoria:
            self.categoria(item, categoria)
        return item

    def setUp(self):
        super().setUp()
        self.con = self.insumo('MAT-1', 'Con precio', precio='10')
        self.con2 = self.insumo('MAT-2', 'Con precio 2', precio='7')
        self.sin = self.insumo('MAT-3', 'Sin precio')
        self.alfa = Proyecto.objects.create(empresa=self.a, nombre='Alfa', descripcion=DESCRIPCION)
        ProyectoAPU.objects.create(proyecto=self.alfa, perfil=self.perfil, region='Oruro')
        self.apu(self.alfa, 'ALF-1', self.con, categoria='Estructuras')
        # Escuela Tarija: un APU completo, uno parcial, uno sin precios y uno sin composición
        self.verde = self.apu(self.proyecto, 'ESC-1', self.con, self.con2, categoria='Obra gruesa')
        self.amarillo = self.apu(self.proyecto, 'ESC-2', self.con, self.sin, categoria='Obra gruesa')
        self.rojo = self.apu(self.proyecto, 'ESC-3', self.sin)
        self.vacio = self.apu(self.proyecto, 'ESC-4')

    def get(self, params='', usuario=None):
        self.client.force_login(usuario or self.su)
        return self.client.get(self.URL + params)

    def det(self, proyecto, usuario=None):
        """Detalle de un proyecto: su resumen y el listado de todos sus APU."""
        self.client.force_login(usuario or self.su)
        return self.client.get(f'{self.URL}{proyecto.pk}/')

    def test_las_cantidades_dan_el_presupuesto_y_se_guardan_por_proyecto(self):
        url = f'{self.URL}{self.proyecto.pk}/cantidades/'
        self.client.force_login(self.su)
        antes = self.det(self.proyecto).context['resumen']
        self.assertEqual((antes['presupuesto'], antes['n_con_metrado']), (None, 0))
        r = self.client.post(url, {f'metrado_{self.verde.pk}': '12,5', f'metrado_{self.amarillo.pk}': ''}, follow=True)
        self.assertContains(r, 'Cantidades guardadas')
        self.assertContains(r, 'aviso aviso-success')        # el mensaje de Django sale como toast estándar (ficha, título y detalle)
        self.assertContains(r, 'aviso__titulo')
        self.assertNotContains(r, 'alert-success')
        self.verde.refresh_from_db()
        self.assertEqual(self.verde.metrado, D('12.5'))
        resumen = self.det(self.proyecto).context['resumen']
        self.assertEqual(resumen['presupuesto'], D('12.5') * calculo.analizar(self.verde).total)
        self.assertEqual((resumen['n_con_metrado'], resumen['filas'][0]['subtotal']), (1, resumen['presupuesto']))
        self.assertAlmostEqual(float(resumen['filas'][0]['pct_presupuesto']), 100.0, places=6)

    def test_cantidad_invalida_no_guarda_nada_y_otro_proyecto_no_se_toca(self):
        url = f'{self.URL}{self.proyecto.pk}/cantidades/'
        self.client.force_login(self.su)
        r = self.client.post(url, {f'metrado_{self.verde.pk}': '5', f'metrado_{self.amarillo.pk}': 'abc'}, follow=True)
        self.assertContains(r, 'no es una cantidad válida')
        self.verde.refresh_from_db()
        self.assertIsNone(self.verde.metrado)                                               # ni siquiera la válida
        alfa_item = ItemModelo.objects.get(codigo='ALF-1')
        self.client.post(url, {f'metrado_{alfa_item.pk}': '9'})                             # APU de otro proyecto: se ignora
        alfa_item.refresh_from_db()
        self.assertIsNone(alfa_item.metrado)
        self.assertEqual(self.client.post(url, {f'metrado_{self.verde.pk}': '-3'}, follow=True).status_code, 200)
        self.verde.refresh_from_db()
        self.assertIsNone(self.verde.metrado)

    def test_solo_quien_gestiona_el_catalogo_puede_guardar_cantidades(self):
        self.client.force_login(self.obs)
        r = self.client.post(f'{self.URL}{self.proyecto.pk}/cantidades/', {f'metrado_{self.verde.pk}': '5'})
        self.assertEqual(r.status_code, 403)

    def test_la_lista_solo_muestra_el_resumen_de_cada_proyecto_sin_listar_los_apu(self):
        r = self.get()
        self.assertEqual([t['proyecto'].nombre for t in r.context['tarjetas']], ['Alfa', 'Escuela Tarija'])   # orden alfabético
        for t in r.context['tarjetas']:
            self.assertNotIn('filas', t['resumen'])
        self.assertNotContains(r, 'ESC-1')                                                  # ningún APU suelto en la lista
        self.assertNotContains(r, 'ALF-1')
        self.assertNotContains(r, 'Descripción ESC-1')
        tarjeta = {t['proyecto'].nombre: t['resumen'] for t in r.context['tarjetas']}['Escuela Tarija']
        self.assertEqual((tarjeta['n'], tarjeta['estados']), (4, {'completo': 1, 'parcial': 1, 'ninguno': 1, 'vacio': 1}))

    def test_elegir_un_proyecto_lista_sus_apu_y_el_resumen(self):
        r = self.det(self.proyecto)
        resumen = r.context['resumen']
        self.assertEqual(r.context['elegido'], self.proyecto)
        self.assertEqual([f['item'].codigo for f in resumen['filas']], ['ESC-1', 'ESC-2', 'ESC-3', 'ESC-4'])
        self.assertNotContains(r, 'ALF-1')                                                  # los de otro proyecto no se mezclan
        esperado = sum((calculo.analizar(i).total for i in (self.verde, self.amarillo, self.rojo, self.vacio)), D(0))
        self.assertEqual(resumen['suma'], esperado)
        self.assertEqual((resumen['n'], resumen['moneda']), (4, 'BOB'))
        self.assertEqual(resumen['estados'], {'completo': 1, 'parcial': 1, 'ninguno': 1, 'vacio': 1})
        self.assertEqual(resumen['n_incompletos'], 2)
        for texto in ('Suma de precios unitarios', 'Precios de los insumos', 'completos', 'con algunos sin precio', 'sin ningún precio',
                      'Descripción ESC-1', 'Ver en la base de APU', 'Presupuesto estimado', 'Carga las cantidades en la tabla'):
            self.assertContains(r, texto)
        self.assertContains(r, '2 APU tienen insumos sin precio')                           # aviso de que la suma no es real

    def test_la_suma_y_los_pesos_son_coherentes(self):
        resumen = self.det(self.proyecto).context['resumen']
        self.assertEqual(sum((f['total'] for f in resumen['filas'] if f['total'] is not None), D(0)), resumen['suma'])
        self.assertAlmostEqual(float(sum(f['pct'] for f in resumen['filas'])), 100.0, places=6)
        self.assertEqual(resumen['filas'][3]['pct'], D(0) if resumen['filas'][3]['total'] == 0 else resumen['filas'][3]['pct'])

    def test_desglose_por_categoria(self):
        resumen = self.det(self.proyecto).context['resumen']
        por = {c['nombre']: c for c in resumen['categorias']}
        self.assertEqual(set(por), {'Obra gruesa', ''})                                     # ESC-3 y ESC-4 no tienen categoría
        self.assertEqual(por['Obra gruesa']['n'], 2)
        self.assertEqual(por['Obra gruesa']['suma'], calculo.analizar(self.verde).total + calculo.analizar(self.amarillo).total)
        self.assertEqual(resumen['categorias'][-1]['nombre'], '')                           # «Sin categoría» al final
        self.assertContains(self.det(self.proyecto), 'Por categoría')

    def test_las_incidencias_del_proyecto_cambian_la_suma(self):
        antes = self.det(self.alfa).context['resumen']['suma']
        ProyectoAPU.objects.filter(proyecto=self.alfa).update(ajustes={'GG': '0.30'})
        despues = self.det(self.alfa).context['resumen']['suma']
        self.assertGreater(despues, antes)
        self.assertEqual(self.det(self.proyecto).context['resumen']['suma'],
                         self.det(self.proyecto).context['resumen']['suma'])   # y no afecta a los demás proyectos

    def test_un_proyecto_ajeno_o_inexistente_no_se_muestra(self):
        self.client.force_login(self.su)
        for pk in (self.proyecto_b.pk, 999999):
            self.assertEqual(self.client.get(f'{self.URL}{pk}/').status_code, 404, pk)
        sin = Proyecto.objects.create(empresa=self.a, nombre='Sin habilitar', descripcion=DESCRIPCION)
        r = self.get()
        self.assertNotIn('Sin habilitar', [t['proyecto'].nombre for t in r.context['tarjetas']])
        self.assertEqual(self.client.get(f'{self.URL}{sin.pk}/').status_code, 404)

    def test_enlaces_y_permisos_de_las_acciones(self):
        r = self.det(self.proyecto, self.coord)
        self.assertContains(r, f'/tekon/apu/generar/?proyecto={self.proyecto.pk}')
        self.assertContains(r, f'/tekon/apu/proyectos/{self.proyecto.pk}/incidencias/')
        self.assertContains(r, f'/tekon/apu/lista/{self.verde.pk}/')
        self.assertContains(r, f'/tekon/apu/lista/?proyecto={self.proyecto.pk}')
        r = self.det(self.proyecto, self.obs)                              # el observador solo mira
        self.assertNotContains(r, '/tekon/apu/generar/')
        self.assertNotContains(r, '/incidencias/')
        self.assertContains(r, 'Descripción ESC-1')

    def test_cada_tarjeta_lleva_al_detalle_y_muestra_cuantos_apu_tiene(self):
        r = self.get()
        html = r.content.decode()
        for p in (self.proyecto, self.alfa):
            self.assertEqual(html.count(f'href="{self.URL}{p.pk}/"'), 1)                    # el nombre enlaza al detalle
        self.assertEqual({t['proyecto'].nombre: t['proyecto'].n_apu for t in r.context['tarjetas']}, {'Alfa': 1, 'Escuela Tarija': 4})
        self.assertIn('Oruro', html)                                                        # la región de cada proyecto
        self.assertIn('Ver detalle y APU', html)

    def test_el_detalle_enlaza_de_vuelta_a_la_lista(self):
        self.assertContains(self.det(self.proyecto), f'href="{self.URL}"')

    def test_proyecto_sin_apu_invita_a_crear_el_primero(self):
        vacio = Proyecto.objects.create(empresa=self.a, nombre='Zeta', descripcion=DESCRIPCION)
        ProyectoAPU.objects.create(proyecto=vacio, perfil=self.perfil)
        r = self.det(vacio, self.coord)
        self.assertEqual((r.context['resumen']['n'], r.context['resumen']['suma']), (0, D(0)))
        self.assertContains(r, 'Este proyecto todavía no tiene APU')
        self.assertContains(r, f'/tekon/apu/generar/?proyecto={vacio.pk}')

    def test_sin_proyectos_habilitados_explica_como_empezar(self):
        ProyectoAPU.objects.all().delete()
        ItemModelo.objects.all().delete()
        r = self.get(usuario=self.coord)
        self.assertEqual(r.context['tarjetas'], [])
        self.assertContains(r, 'Todavía no hay proyectos habilitados para APU')
        self.assertContains(r, '/tekon/apu/proyectos/habilitar/')


class CalculoTests(Base):
    def test_sub_items_desperdicio_region_e_insumos_sin_precio(self):
        cemento = self.insumo('MAT-1', 'Cemento', unidad='kg', precio='2')
        sin = self.insumo('MAT-2', 'Arena', unidad='m3')
        PrecioInsumo.objects.create(insumo=cemento, region='Tarija', fecha=date(2026, 1, 1), precio=D('3'), moneda='BOB')
        mortero = ItemModelo.objects.create(empresa=self.a, codigo='MOR', descripcion='Mortero', unidad='m3')
        LineaComposicion.objects.create(item=mortero, insumo=cemento, cantidad=D('300'))
        LineaComposicion.objects.create(item=mortero, insumo=sin, cantidad=D('1'))
        muro = ItemModelo.objects.create(empresa=self.a, proyecto=self.proyecto, codigo='APU-001', descripcion='Muro', unidad='m2')
        LineaComposicion.objects.create(item=muro, subitem=mortero, cantidad=D('0.02'), desperdicio_pct=D('10'))
        nacional = calculo.analizar(muro)
        self.assertEqual(nacional.grupos['MAT'], D('0.02') * D('1.1') * D('300') * D('2'))
        self.assertEqual(nacional.sin_precio, [sin])
        tarija = calculo.analizar(muro, region='Tarija')
        self.assertEqual(tarija.grupos['MAT'], D('0.02') * D('1.1') * D('300') * D('3'))   # precio regional
        self.assertEqual(nacional.filas[0].costo, nacional.grupos['MAT'])

    def test_los_precios_usan_por_defecto_la_region_del_proyecto(self):
        cemento = self.insumo('MAT-1', 'Cemento', unidad='kg', precio='2')
        PrecioInsumo.objects.create(insumo=cemento, region='Tarija', fecha=date(2026, 1, 1), precio=D('3'), moneda='BOB')
        item = ItemModelo.objects.create(empresa=self.a, proyecto=self.proyecto, codigo='APU-001', descripcion='x', unidad='m2')
        LineaComposicion.objects.create(item=item, insumo=cemento, cantidad=D('10'))
        self.assertEqual(calculo.analizar(item).grupos['MAT'], D('20'))              # proyecto sin región: nacional
        self.pa.region = 'Tarija'
        self.pa.save()
        self.assertEqual(calculo.analizar(item).grupos['MAT'], D('30'))              # ahora usa la de Tarija
        self.assertEqual(calculo.analizar(item, region='').grupos['MAT'], D('20'))   # una región explícita la reemplaza

    def test_sin_perfil_no_hay_precio_unitario(self):
        p = Proyecto.objects.create(empresa=self.a, nombre='Sin perfil', descripcion=DESCRIPCION)
        item = ItemModelo.objects.create(empresa=self.a, proyecto=p, codigo='APU-001', descripcion='x', unidad='m2')
        self.assertIsNone(calculo.analizar(item).total)


class FichaTests(Base):
    """La ficha del APU: composición agrupada con subtotales y pesos, y el precio unitario junto a su desglose."""

    def setUp(self):
        super().setUp()
        b = self.borrador_en_paso5()
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.su)
        self.item = ItemModelo.objects.get()
        self.url = f'/tekon/apu/lista/{self.item.pk}/'

    def test_secciones_con_subtotales_y_pesos_que_suman_cien(self):
        a = calculo.analizar(self.item)
        secs = a.secciones
        self.assertEqual([s['clave'] for s in secs], ['MAT', 'MO', 'EQ'])
        self.assertEqual(sum((s['subtotal'] for s in secs), D(0)), a.directo)
        self.assertAlmostEqual(float(sum(s['pct'] for s in secs)), 100.0, places=6)
        self.assertAlmostEqual(float(sum(f.pct for s in secs for f in s['filas'])), 100.0, places=6)
        mat = secs[0]
        self.assertEqual(mat['subtotal'], D('38') * D('1.05') * D('1.5'))
        self.assertEqual(mat['moneda'], 'BOB')

    def test_un_sub_analisis_forma_su_propia_seccion(self):
        sub = ItemModelo.objects.create(empresa=self.a, codigo='HOR', descripcion='Hormigón', unidad='m3')
        LineaComposicion.objects.create(item=sub, insumo=self.item.lineas.first().insumo, cantidad=D('2'))
        LineaComposicion.objects.create(item=self.item, subitem=sub, cantidad=D('0.1'))
        claves = [s['clave'] for s in calculo.analizar(self.item).secciones]
        self.assertEqual(claves[-1], 'SUB')
        self.client.force_login(self.su)
        self.assertContains(self.client.get(self.url), f'/tekon/apu/lista/{sub.pk}/')           # enlaza al sub-análisis

    def test_la_pagina_muestra_precio_unitario_desglose_y_distribucion(self):
        self.client.force_login(self.su)
        r = self.client.get(self.url)
        for texto in ('Precio unitario', 'Dónde se va el costo', 'Desglose del precio', 'Materiales', 'Mano de obra', 'Equipos',
                      'Costo directo', 'Ladrillo 6H', 'MAT-001', 'Precios: nacionales'):
            self.assertContains(r, texto)
        html = r.content.decode()
        for trazo in ('M12 9v6M16 15v6', 'M7 9.5a5 5 0 0 1 10 0', 'M11 13 16 5.5l4 6.5'):                # ladrillos, obrero, excavadora
            self.assertIn(trazo, html)
        self.assertEqual(html.count('<div'), html.count('</div>'))
        self.assertEqual(html.count('<section'), html.count('</section>'))
        self.assertEqual(html.count('<table'), html.count('</table>'))
        self.assertNotIn('style="', html.split('<main', 1)[1])                                      # sin estilos en línea (CSP)
        self.assertIn(str(calculo.analizar(self.item).total).replace('.', ','), html)              # el número sale con coma (es)

    def test_sin_perfil_muestra_el_costo_directo_en_lugar_del_precio(self):
        p = Proyecto.objects.create(empresa=self.a, nombre='Sin habilitar', descripcion=DESCRIPCION)
        self.item.proyecto = p
        self.item.save()
        self.client.force_login(self.su)
        r = self.client.get(self.url)
        self.assertContains(r, 'Costo directo')
        self.assertContains(r, 'no tiene un proyecto habilitado')

    def test_los_porcentajes_no_fallan_con_costo_cero(self):
        vacio = ItemModelo.objects.create(empresa=self.a, proyecto=self.proyecto, codigo='APU-009', descripcion='Vacío', unidad='m2')
        self.client.force_login(self.su)
        self.assertContains(self.client.get(f'/tekon/apu/lista/{vacio.pk}/'), 'aún no tiene composición')
        sin_precio = self.insumo('MAT-077', 'Sin precio aún')
        LineaComposicion.objects.create(item=vacio, insumo=sin_precio, cantidad=D('1'))
        self.assertEqual(self.client.get(f'/tekon/apu/lista/{vacio.pk}/').status_code, 200)       # directo = 0 sin dividir por cero


class SemaforoListaTests(Base):
    """En la base de APU, la barra a la izquierda de cada fila indica qué tan completos están los precios."""

    def apu(self, codigo, *insumos, sub=None):
        item = ItemModelo.objects.create(empresa=self.a, proyecto=self.proyecto, codigo=codigo, descripcion=f'APU {codigo}', unidad='m2')
        for i in insumos:
            LineaComposicion.objects.create(item=item, insumo=i, cantidad=D('1'))
        if sub:
            LineaComposicion.objects.create(item=item, subitem=sub, cantidad=D('1'))
        return item

    def setUp(self):
        super().setUp()
        self.con = self.insumo('MAT-1', 'Con precio', precio='5')
        self.con2 = self.insumo('MAT-2', 'Con precio 2', precio='7')
        self.sin = self.insumo('MAT-3', 'Sin precio')
        self.sin2 = self.insumo('MAT-4', 'Sin precio 2')

    def test_estados(self):
        verde = calculo.analizar(self.apu('A-1', self.con, self.con2))
        amarillo = calculo.analizar(self.apu('A-2', self.con, self.sin))
        rojo = calculo.analizar(self.apu('A-3', self.sin, self.sin2))
        vacio = calculo.analizar(self.apu('A-4'))
        self.assertEqual([a.estado_precios for a in (verde, amarillo, rojo, vacio)], ['completo', 'parcial', 'ninguno', 'vacio'])
        self.assertEqual((amarillo.n_insumos, len(amarillo.sin_precio)), (2, 1))

    def test_los_insumos_de_los_sub_analisis_cuentan(self):
        sub = ItemModelo.objects.create(empresa=self.a, codigo='SUB', descripcion='Sub', unidad='m3')
        LineaComposicion.objects.create(item=sub, insumo=self.sin, cantidad=D('2'))
        a = calculo.analizar(self.apu('A-5', self.con, sub=sub))              # 1 con precio + 1 (del sub) sin precio
        self.assertEqual((a.estado_precios, a.n_insumos), ('parcial', 2))
        solo_sub = calculo.analizar(self.apu('A-6', sub=sub))
        self.assertEqual(solo_sub.estado_precios, 'ninguno')

    def test_un_insumo_repetido_se_cuenta_una_vez(self):
        a = calculo.analizar(self.apu('A-7', self.con, self.con, self.sin))
        self.assertEqual((a.n_insumos, len(a.sin_precio), a.estado_precios), (2, 1, 'parcial'))

    def test_la_lista_pinta_la_barra_del_color_que_corresponde(self):
        self.apu('A-1', self.con, self.con2)
        self.apu('A-2', self.con, self.sin)
        self.apu('A-3', self.sin, self.sin2)
        self.apu('A-4')
        self.client.force_login(self.su)
        r = self.client.get('/tekon/apu/lista/')
        estados = {it.codigo: it.estado_precios for it in r.context['pagina']}
        self.assertEqual(estados, {'A-1': 'completo', 'A-2': 'parcial', 'A-3': 'ninguno', 'A-4': 'vacio'})
        html = r.content.decode()
        for codigo, clase in (('A-1', 'border-l-success'), ('A-2', 'border-l-warning'), ('A-3', 'border-l-error'), ('A-4', 'border-l-base-300')):
            fila = html.split(f'>{codigo}</a>')[0].rsplit('<td', 1)[1]                        # la celda del código de esa fila
            self.assertIn(clase, fila, codigo)
        for texto in ('Faltan algunos', 'Ninguno tiene precio', 'Completos', 'Faltan precios: 1 de 2 insumos sin precio',
                      'Ningún insumo tiene precio (2 en total)', 'Sin composición'):
            self.assertContains(r, texto)
        self.assertContains(r, '1 sin precio')                                                   # en la celda del precio

    def test_el_estado_sigue_el_precio_de_la_region_del_proyecto(self):
        item = self.apu('A-8', self.con)
        PrecioInsumo.objects.create(insumo=self.sin, region='Tarija', fecha=date(2026, 1, 1), precio=D('3'), moneda='BOB')
        LineaComposicion.objects.create(item=item, insumo=self.sin, cantidad=D('1'))
        self.assertEqual(calculo.analizar(item).estado_precios, 'parcial')                    # nacional: falta uno
        self.pa.region = 'Tarija'
        self.pa.save()
        self.assertEqual(calculo.analizar(item).estado_precios, 'completo')                   # con la región del proyecto: completo


class LineasFichaTests(Base):
    """Desde la ficha del APU se edita cada línea de la composición (cantidad, desperdicio y precio) o se quita."""

    def setUp(self):
        super().setUp()
        b = self.borrador_en_paso5()
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.su)
        self.item = ItemModelo.objects.get()
        self.mat = self.item.lineas.get(insumo__tipo='MAT')
        self.mo = self.item.lineas.get(insumo__tipo='MO')
        self.url = f'/tekon/apu/lista/{self.item.pk}/lineas/{self.mat.pk}/'

    def test_la_ficha_ofrece_editar_cada_insumo(self):
        self.client.force_login(self.su)
        r = self.client.get(f'/tekon/apu/lista/{self.item.pk}/')
        html = r.content.decode()
        self.assertEqual(html.count('data-linea="'), 3)
        self.assertEqual(html.count('data-editar-linea'), 3)                                      # un lápiz por fila
        self.assertContains(r, f'data-url="{self.url}"')
        self.assertContains(r, 'id="apu-editar-linea"')
        self.assertContains(r, 'data-cantidad="38"')
        self.assertContains(r, 'data-precio="1.5"')                                               # sin ceros de más
        self.assertContains(r, 'data-cantidad="0.5"')
        self.assertNotContains(r, '1,5000')
        self.client.force_login(self.obs)                                                         # el observador solo ve
        self.assertNotContains(self.client.get(f'/tekon/apu/lista/{self.item.pk}/'), 'data-linea="')

    def test_editar_cantidad_y_desperdicio_cambia_el_precio_unitario(self):
        antes = calculo.analizar(self.item).total
        r = self.json(self.url, {'cantidad': '40,5', 'desperdicio_pct': '8'}, self.su)
        self.assertEqual(r.status_code, 200)
        self.mat.refresh_from_db()
        self.assertEqual((self.mat.cantidad, self.mat.desperdicio_pct), (D('40.5'), D('8')))
        self.assertGreater(calculo.analizar(self.item).total, antes)

    def test_editar_el_precio_crea_uno_nuevo_en_la_region_del_proyecto_para_todos_los_apu(self):
        self.pa.region = 'Tarija'
        self.pa.save()
        r = self.json(self.url, {'cantidad': '38', 'desperdicio_pct': '5', 'precio': '2,25', 'moneda': 'bob'}, self.su)
        self.assertEqual(r.status_code, 200)
        self.assertIn('todos los APU', r.json()['message'])
        p = PrecioInsumo.objects.get(insumo=self.mat.insumo, region='Tarija')
        self.assertEqual((p.precio, p.moneda, p.estimado), (D('2.25'), 'BOB', False))
        self.assertEqual(PrecioInsumo.objects.filter(insumo=self.mat.insumo).count(), 2)          # el nacional anterior sigue ahí
        self.assertEqual(calculo.analizar(self.item).grupos['MAT'], D('38') * D('1.05') * D('2.25'))

    def test_un_precio_ya_estimado_deja_de_serlo_al_corregirlo(self):
        PrecioInsumo.objects.filter(insumo=self.mat.insumo).update(estimado=True)
        self.json(self.url, {'cantidad': '38', 'precio': '1.6', 'moneda': 'BOB'}, self.su)
        self.assertFalse(PrecioInsumo.objects.filter(insumo=self.mat.insumo, region='').latest('fecha').estimado)

    def test_validaciones(self):
        for datos, texto in (({'cantidad': '0'}, 'mayor que cero'), ({'cantidad': 'abc'}, 'mayor que cero'),
                             ({'cantidad': '5', 'desperdicio_pct': '150'}, 'entre 0 y 100'),
                             ({'cantidad': '5', 'precio': '-3', 'moneda': 'BOB'}, 'precio válido'),
                             ({'cantidad': '5', 'precio': '3', 'moneda': 'B'}, 'moneda')):
            r = self.json(self.url, datos, self.su)
            self.assertEqual(r.status_code, 400, datos)
            self.assertIn(texto, r.json()['message'])
        self.mat.refresh_from_db()
        self.assertEqual(self.mat.cantidad, D('38'))                                              # nada cambió

    def test_horas_de_mano_de_obra_editadas_a_mano_dejan_de_depender_de_la_cuadrilla(self):
        self.assertTrue(self.mo.ayuda)
        self.json(f'/tekon/apu/lista/{self.item.pk}/lineas/{self.mo.pk}/', {'cantidad': '0.75'}, self.su)
        self.mo.refresh_from_db()
        self.assertEqual((self.mo.cantidad, self.mo.ayuda), (D('0.75'), {}))
        otra = self.item.lineas.get(insumo__tipo='EQ')                                           # equipos: la ayuda no aplica
        self.json(f'/tekon/apu/lista/{self.item.pk}/lineas/{otra.pk}/', {'cantidad': '0.2'}, self.su)

    def test_el_filtro_de_numeros_no_deja_ceros_de_mas(self):
        from apu_catalogo.templatetags.apu_tags import numlimpio
        self.assertEqual([numlimpio(v, 'u') for v in ('1.5000', '830', '0.500000', D('1200000'), '0', None, 'x')],
                         ['1.5', '830', '0.5', '1200000', '0', '', 'x'])
        self.assertEqual(numlimpio(D('1.2500')), '1,25')                                          # con el separador del idioma (es)

    def test_quitar_la_linea_no_borra_el_insumo(self):
        r = self.json(self.url + 'quitar/', {}, self.su)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.item.lineas.filter(pk=self.mat.pk).exists())
        self.assertTrue(Insumo.objects.filter(pk=self.mat.insumo_id).exists())
        self.assertTrue(PrecioInsumo.objects.filter(insumo=self.mat.insumo_id).exists())

    def test_permisos_y_aislamiento_por_empresa(self):
        self.assertEqual(self.json(self.url, {'cantidad': '5'}, self.obs).status_code, 403)
        self.assertEqual(self.json(self.url + 'quitar/', {}, self.obs).status_code, 403)
        self.assertEqual(self.json(self.url, {'cantidad': '5'}, self.ajeno).status_code, 403)
        otra = ItemModelo.objects.create(empresa=self.a, proyecto=self.proyecto, codigo='APU-099', descripcion='Otro', unidad='m2')
        self.assertEqual(self.json(f'/tekon/apu/lista/{otra.pk}/lineas/{self.mat.pk}/', {'cantidad': '5'}, self.su).status_code, 404)   # línea de otro APU
        self.mat.refresh_from_db()
        self.assertEqual(self.mat.cantidad, D('38'))

    def test_editar_un_sub_analisis_solo_cambia_cantidad_y_desperdicio(self):
        sub = ItemModelo.objects.create(empresa=self.a, codigo='HOR', descripcion='Hormigón', unidad='m3')
        linea = LineaComposicion.objects.create(item=self.item, subitem=sub, cantidad=D('0.1'))
        r = self.json(f'/tekon/apu/lista/{self.item.pk}/lineas/{linea.pk}/', {'cantidad': '0.2', 'desperdicio_pct': '3', 'precio': '9', 'moneda': 'BOB'}, self.su)
        self.assertEqual(r.status_code, 200)
        linea.refresh_from_db()
        self.assertEqual((linea.cantidad, linea.desperdicio_pct), (D('0.2'), D('3')))
        self.assertFalse(PrecioInsumo.objects.filter(precio=D('9')).exists())                    # un sub-análisis no tiene precio propio


class TokensTests(Base):
    EJECUCION = {
        'workflowData': {'nodes': [{'name': 'OpenAI Chat Model', 'parameters': {'model': {'value': 'gpt-5.1'}}},
                                   {'name': 'Modelo mini', 'parameters': {'model': 'gpt-4.1-mini'}}]},
        'data': {'resultData': {'runData': {
            'OpenAI Chat Model': [{'data': {'ai_languageModel': [[{'json': {'tokenUsage': {'promptTokens': 1000, 'completionTokens': 500}}}]]}},
                                  {'data': {'ai_languageModel': [[{'json': {'tokenUsage': {'promptTokens': 200, 'completionTokens': 100}}}]]}}],
            'Modelo mini': [{'data': {'ai_languageModel': [[{'json': {'tokenUsage': {'promptTokens': 400, 'completionTokens': 50}}}]]}}],
            'Webhook': [{'data': {'main': [[{'json': {}}]]}}]}}}}

    def test_sin_uso_reportado_se_usa_la_estimacion_de_n8n_y_el_modelo_que_respondio(self):
        item = {'json': {'response': {'generations': [[{'generationInfo': {'model_name': 'gpt-5.1-2025-11-13'}}]]},
                         'tokenUsageEstimate': {'promptTokens': 3149, 'completionTokens': 0}}}
        ejecucion = {'workflowData': {'nodes': [{'name': 'Modelo principal', 'parameters': {'model': {'value': 'otro'}}}]},
                     'data': {'resultData': {'runData': {'Modelo principal': [{'data': {'ai_languageModel': [[item]]}}]}}}}
        self.assertEqual(ia.uso_de_ejecucion(ejecucion), {'gpt-5.1': {'entrada': 3149, 'salida': 0, 'estimado': True}})

    def test_el_uso_se_suma_por_modelo_y_el_costo_sale_de_la_tarifa(self):
        uso = ia.uso_de_ejecucion(self.EJECUCION)
        self.assertEqual(uso, {'gpt-5.1': {'entrada': 1200, 'salida': 600}, 'gpt-4.1-mini': {'entrada': 400, 'salida': 50}})
        TarifaModeloIA.objects.create(modelo='gpt-5.1', entrada_usd_mtok=D('1.25'), salida_usd_mtok=D('10'))
        self.assertIsNone(ia.costo_de_uso(uso))                                     # falta la tarifa del mini
        TarifaModeloIA.objects.create(modelo='gpt-4.1-mini', entrada_usd_mtok=D('0.4'), salida_usd_mtok=D('1.6'))
        self.assertEqual(ia.costo_de_uso(uso), D('0.007740'))

    def test_el_catalogo_de_apu_se_recorta_a_los_mas_parecidos(self):
        for i in range(asistente.LIMITE_CATALOGO_ITEMS + 10):
            ItemModelo.objects.create(empresa=self.a, codigo=f'X{i:03d}', descripcion=f'Otro trabajo {i}', unidad='m2')
        ItemModelo.objects.create(empresa=self.a, codigo='Z999', descripcion='Mortero cementicio especial', unidad='m3')
        filas = asistente.catalogo_items_para_ia(self.a, texto='Muro con mortero cementicio')
        self.assertEqual(len(filas), asistente.LIMITE_CATALOGO_ITEMS)
        self.assertEqual(filas[0]['codigo'], 'Z999')                                  # el más parecido va primero

    def _llamada_en(self, fecha):
        ll = LlamadaIA.objects.create(empresa=self.a, webhook='apu-insumos', uso={'gpt-5.1': {'entrada': 10, 'salida': 5}})
        LlamadaIA.objects.filter(pk=ll.pk).update(fecha=fecha)
        return ll

    def test_el_consumo_se_filtra_por_dia(self):
        hoy = timezone.localtime().replace(hour=12)
        self._llamada_en(hoy)
        self._llamada_en(hoy - timedelta(days=1))
        self._llamada_en(hoy - timedelta(days=1))
        self.client.force_login(self.su)
        self.assertEqual(self.client.get('/tekon/apu/consumo-ia/').context['total']['llamadas'], 3)
        self.assertEqual(self.client.get('/tekon/apu/consumo-ia/?dia=%s' % hoy.date().isoformat()).context['total']['llamadas'], 1)
        self.assertEqual(self.client.get('/tekon/apu/consumo-ia/?dia=basura').context['total']['llamadas'], 3)

    def test_reiniciar_borra_solo_el_dia_elegido_o_todo_y_solo_el_superusuario(self):
        hoy = timezone.localtime().replace(hour=12)
        self._llamada_en(hoy)
        self._llamada_en(hoy - timedelta(days=1))
        url = '/tekon/apu/consumo-ia/reiniciar/'
        self.client.force_login(self.adm)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(LlamadaIA.objects.count(), 2)
        self.client.force_login(self.su)
        self.assertEqual(self.client.get(url).status_code, 405)                     # solo POST
        r = self.client.post(url, {'dia': hoy.date().isoformat()})
        self.assertRedirects(r, '/tekon/apu/consumo-ia/?dia=%s' % hoy.date().isoformat())
        self.assertEqual(LlamadaIA.objects.count(), 1)                                # queda la de ayer
        self.client.post(url, {'dia': ''})
        self.assertEqual(LlamadaIA.objects.count(), 0)

    @override_settings(N8N_API_URL='http://n8n:5678', N8N_API_KEY='k')
    def test_la_busqueda_web_suma_su_costo_al_sincronizar(self):
        TarifaModeloIA.objects.create(modelo='gpt-5.1', entrada_usd_mtok=D('1.25'), salida_usd_mtok=D('10'))
        TarifaModeloIA.objects.create(modelo='gpt-4.1-mini', entrada_usd_mtok=D('0.4'), salida_usd_mtok=D('1.6'))
        resp = mock.Mock(**{'json.return_value': self.EJECUCION, 'raise_for_status.return_value': None})
        sin = LlamadaIA.objects.create(empresa=self.a, webhook='apu-insumos', ejecucion_id='1')
        con = LlamadaIA.objects.create(empresa=self.a, webhook='apu-precios', ejecucion_id='2')
        with mock.patch('apu_generador.ia.requests.get', return_value=resp):
            ia.sincronizar_uso([sin, con])
        sin.refresh_from_db(); con.refresh_from_db()
        self.assertEqual(sin.costo_usd, D('0.007740'))
        self.assertEqual(con.costo_usd, D('0.017740'))      # + $0.01 de la búsqueda web

    def test_el_resumen_marca_lo_estimado(self):
        ll = LlamadaIA.objects.create(empresa=self.a, webhook='apu-insumos', uso={'gpt-5.1': {'entrada': 1000, 'salida': 0, 'estimado': True}},
                                      costo_usd=D('0.00125'))
        self.assertTrue(ia.resumen_uso([ll])['estimado'])

    @override_settings(N8N_API_URL='http://n8n:5678', N8N_API_KEY='k')
    def test_sincronizar_deja_pendiente_si_falla_la_api_de_n8n(self):
        ll = LlamadaIA.objects.create(empresa=self.a, webhook='apu-insumos', ejecucion_id='77')
        import requests
        with mock.patch('apu_generador.ia.requests.get', side_effect=requests.ConnectionError('x')):
            self.assertEqual(ia.sincronizar_uso([ll]), 0)
        ll.refresh_from_db()
        self.assertIsNone(ll.uso)
        resp = mock.Mock(**{'json.return_value': self.EJECUCION, 'raise_for_status.return_value': None})
        with mock.patch('apu_generador.ia.requests.get', return_value=resp) as g:
            self.assertEqual(ia.sincronizar_uso([ll]), 1)
        self.assertEqual(g.call_args[1]['headers'], {'X-N8N-API-KEY': 'k'})
        ll.refresh_from_db()
        self.assertEqual(ll.uso['gpt-5.1']['entrada'], 1200)

    def test_sin_configurar_la_medicion_no_hace_nada(self):
        ll = LlamadaIA.objects.create(empresa=self.a, webhook='apu-insumos', ejecucion_id='77')
        self.assertEqual(ia.sincronizar_uso([ll]), 0)

    def test_la_ficha_del_apu_muestra_el_consumo_solo_al_superusuario(self):
        b = self.borrador_en_paso5()
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.coord)
        item = ItemModelo.objects.get()
        LlamadaIA.objects.create(empresa=self.a, webhook='apu-insumos', borrador=b, ejecucion_id='',
                                 uso={'gpt-5.1': {'entrada': 10, 'salida': 5}})
        self.assertNotContains(self.client.get(f'/tekon/apu/lista/{item.pk}/'), 'Consumo de IA')
        self.client.force_login(self.su)
        self.assertContains(self.client.get(f'/tekon/apu/lista/{item.pk}/'), 'Consumo de IA')

    def test_panel_consumo_y_tarifas_solo_superusuario(self):
        for url in ('/tekon/apu/consumo-ia/',):
            self.client.force_login(self.adm)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.client.force_login(self.su)
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.json('/tekon/apu/consumo-ia/tarifas/verificar/', {}, self.adm).status_code, 403)

    def test_verificar_tarifas_muestra_diferencias_y_aplica_solo_al_confirmar(self):
        TarifaModeloIA.objects.create(modelo='gpt-5.1', entrada_usd_mtok=D('1.25'), salida_usd_mtok=D('10'))
        publicada = {'tarifas': [{'modelo': 'gpt-5.1', 'entrada_usd_mtok': '1.5', 'salida_usd_mtok': '10'},
                                 {'modelo': 'gpt-4.1-mini', 'entrada_usd_mtok': '0.4', 'salida_usd_mtok': '1.6'}], 'fuente': 'openai.com/pricing'}
        with mock.patch(LLAMAR, return_value=publicada):
            r = self.json('/tekon/apu/consumo-ia/tarifas/verificar/', {}, self.su).json()
        self.assertEqual(len(r['cambios']), 2)
        self.assertEqual(TarifaModeloIA.objects.get(modelo='gpt-5.1').entrada_usd_mtok, D('1.25'))   # aún no se aplicó
        self.json('/tekon/apu/consumo-ia/tarifas/aplicar/', {'cambios': r['cambios'], 'fuente': r['fuente']})
        self.assertEqual(TarifaModeloIA.objects.get(modelo='gpt-5.1').entrada_usd_mtok, D('1.5'))
        self.assertEqual(TarifaModeloIA.objects.count(), 2)
        with mock.patch(LLAMAR, return_value=publicada):
            r = self.json('/tekon/apu/consumo-ia/tarifas/verificar/', {}).json()
        self.assertEqual(r['cambios'], [])
        self.assertIn('no cambiaron', r['message'])


class PaginasTests(Base):
    """Todas las pantallas responden y respetan permisos (humo)."""

    def test_pantallas_del_modulo(self):
        b = self.borrador_en_paso5()
        self.json(f'/tekon/apu/borrador/{b.pk}/guardar-apu/', {}, self.coord)
        item = ItemModelo.objects.get()
        self.client.force_login(self.coord)
        for url in ('/tekon/apu/', '/tekon/apu/generar/', '/tekon/apu/pendientes/', '/tekon/apu/lista/', f'/tekon/apu/lista/{item.pk}/',
                    '/tekon/apu/proyectos/', f'/tekon/apu/proyectos/{self.proyecto.pk}/incidencias/', '/tekon/apu/insumos/',
                    '/tekon/apu/lista/?q=muro&proyecto=%d' % self.proyecto.pk, '/tekon/apu/insumos/?tipo=MAT'):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_pasos_2_a_4_se_muestran_en_su_paso(self):
        for paso, slug in ((2, 'materiales'), (3, 'mano-obra'), (4, 'equipos')):
            b = self.borrador(paso=paso)
            self.client.force_login(self.coord)
            r = self.client.get(f'/tekon/apu/borrador/{b.pk}/{slug}/')
            self.assertEqual(r.status_code, 200, slug)
            self.assertContains(r, 'Guardar y continuar')

    def test_eliminar_borrador(self):
        b = self.borrador(paso=2)
        self.client.force_login(self.coord)
        self.client.post(f'/tekon/apu/borrador/{b.pk}/eliminar/')
        b.refresh_from_db()
        self.assertTrue(b.eliminado)
        self.assertEqual(list(self.client.get('/tekon/apu/pendientes/').context['borradores']), [])

    def test_pendientes_los_ve_el_equipo_del_proyecto_y_no_otros(self):
        b = self.borrador(paso=2)
        self.proyecto.equipo.add(self.m_ejec)
        self.client.force_login(self.ejec)
        self.assertContains(self.client.get('/tekon/apu/pendientes/'), 'Muro de ladrillo')
        otro = User.objects.create_user('otro@example.com', 'x')
        agregar_miembro(otro, self.a, rol_por_base(self.a, RolBase.MIEMBRO))
        self.client.force_login(otro)
        self.assertNotContains(self.client.get('/tekon/apu/pendientes/'), 'Muro de ladrillo')
        self.assertEqual(self.client.get(f'/tekon/apu/borrador/{b.pk}/continuar/').status_code, 404)


class CredencialN8nTests(Base):
    @override_settings(N8N_API_URL='http://env:5678', N8N_API_KEY='env-key')
    def test_la_de_la_empresa_manda_y_el_env_es_respaldo(self):
        from cuentas.models import CredencialesEmpresa
        self.assertEqual(CredencialesEmpresa.n8n_api(self.a), ('http://env:5678', 'env-key'))
        CredencialesEmpresa.objects.create(empresa=self.a, n8n_api_url='http://db:5678/', n8n_api_key=' db-key ')
        self.assertEqual(CredencialesEmpresa.n8n_api(self.a), ('http://db:5678', 'db-key'))
        self.assertEqual(CredencialesEmpresa.n8n_api(self.b), ('http://env:5678', 'env-key'))   # la otra empresa no hereda la de Tekon

    def test_cada_llamada_se_mide_con_la_clave_de_su_empresa(self):
        from cuentas.models import CredencialesEmpresa
        CredencialesEmpresa.objects.create(empresa=self.a, n8n_api_url='http://a:5678', n8n_api_key='clave-A')
        CredencialesEmpresa.objects.create(empresa=self.b, n8n_api_url='http://b:5678', n8n_api_key='clave-B')
        la = LlamadaIA.objects.create(empresa=self.a, webhook='apu-insumos', ejecucion_id='1')
        lb = LlamadaIA.objects.create(empresa=self.b, webhook='apu-insumos', ejecucion_id='2')
        ok = mock.Mock(status_code=200, **{'raise_for_status.return_value': None, 'json.return_value': TokensTests.EJECUCION})
        with mock.patch('apu_generador.ia.requests.get', return_value=ok) as g:
            self.assertEqual(ia.sincronizar_uso([la, lb]), 2)
        usados = {c[0][0]: c[1]['headers']['X-N8N-API-KEY'] for c in g.call_args_list}
        self.assertEqual(usados, {'http://a:5678/api/v1/executions/1': 'clave-A', 'http://b:5678/api/v1/executions/2': 'clave-B'})

    def test_si_una_empresa_falla_las_demas_se_siguen_midiendo(self):
        from cuentas.models import CredencialesEmpresa
        CredencialesEmpresa.objects.create(empresa=self.a, n8n_api_url='http://a:5678', n8n_api_key='mala')
        CredencialesEmpresa.objects.create(empresa=self.b, n8n_api_url='http://b:5678', n8n_api_key='buena')
        llamadas = [LlamadaIA.objects.create(empresa=self.a, webhook='apu-insumos', ejecucion_id=str(i)) for i in (1, 2, 3)]
        llamadas.append(LlamadaIA.objects.create(empresa=self.b, webhook='apu-insumos', ejecucion_id='9'))
        ok = mock.Mock(status_code=200, **{'raise_for_status.return_value': None, 'json.return_value': TokensTests.EJECUCION})
        rechazada = mock.Mock(status_code=401)
        with mock.patch('apu_generador.ia.requests.get', side_effect=lambda url, **kw: rechazada if 'a:5678' in url else ok) as g:
            self.assertEqual(ia.sincronizar_uso(llamadas), 1)
        self.assertEqual(g.call_count, 2)                                                 # una prueba de A (rechazada) y la de B
        self.assertIn('Tekon: n8n rechazó la clave de la API', ia.ESTADO_MEDICION['motivo'])
        self.assertNotIn('Embol', ia.ESTADO_MEDICION['motivo'])
