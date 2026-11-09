import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from cuentas.models import User
from proyectos.models import Proyecto, ProyectoUbicacion
from reg_base import estado
from reg_base.tests import BaseRegistros
from reg_construccion.models import RegConstruccion
from reg_fotos.tests import STORAGES_TEST, imagen, subida
from reg_txtss.models import RegTxtss

from . import servicios, widgets
from .models import DatoPaso, Paso, PasoAsignado, PasoWidget, Plantilla
from .widgets.base import Contexto
from .widgets.form_dinamico import errores_dsl, parsear_campos


def ctx(registro, paso=None):
    return Contexto(registro=registro, paso=paso or Paso(nombre='p'), clave='txtss')


class WidgetsTests(BaseRegistros):
    def setUp(self):
        super().setUp()
        self.r = RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1)

    def leer(self, slug, config=None, **post):
        w = widgets.obtener(slug)
        return w, w.leer({w.nombre_campo(k): v for k, v in post.items()}, {}, config or {})

    def test_el_registro_tiene_los_tipos_esperados(self):
        self.assertEqual(sorted(w.slug for w in widgets.todos()), sorted([
            'comentario_widget', 'lista_widget', 'form_dinamico_widget', 'ubicacion_widget', 'distancia_widget',
            'camera_widget', 'camera_libro_widget', 'imgs_desc_widget', 'tabla_avance_widget', 'poste_form_widget',
            'mapa_1p', 'mapa_2_puntos', 'tabla_widget', 'firma_widget', 'hallazgos_widget', 'seguimiento_widget']))

    def test_comentario(self):
        w, (datos, errs) = self.leer('comentario_widget', comentario='  Todo bien  ')
        self.assertEqual((datos, errs), ({'comentario': 'Todo bien'}, []))
        self.assertEqual((w.nivel(datos, {}, ctx(self.r)), w.nivel({}, {}, ctx(self.r))), (3, 1))
        _w, (datos, errs) = self.leer('comentario_widget', {'max_length': 5}, comentario='demasiado largo')
        self.assertTrue(errs)
        self.assertEqual(datos['comentario'], 'demasiado largo')            # se devuelve para repintarlo
        self.assertTrue(w.validar_config({'max_length': 'x'}))

    def test_lista(self):
        w, (datos, errs) = self.leer('lista_widget', entradas='uno\n\n  dos \ntres')
        self.assertEqual(datos, {'entradas': ['uno', 'dos', 'tres']})
        _w, (_d, errs) = self.leer('lista_widget', {'max_items': 2}, entradas='a\nb\nc')
        self.assertTrue(errs)
        self.assertEqual(w.nivel({'entradas': []}, {}, ctx(self.r)), 1)

    def test_form_dinamico_dsl(self):
        dsl = ('tipo | text | Tipo de estructura | ej. metálica | *\n'
               'altura | number | Altura\n'
               'estado | select | Estado | Bueno,Malo | *\n'
               'acceso | toggle | Acceso camión; fecha | date | Fecha\n'
               '# comentario ignorado\n')
        self.assertEqual([c['nombre'] for c in parsear_campos(dsl)], ['tipo', 'altura', 'estado', 'acceso', 'fecha'])
        self.assertEqual(errores_dsl(dsl), [])
        self.assertEqual(len(errores_dsl('Mal-Nombre | text')), 1)
        self.assertEqual(len(errores_dsl('a | inventado')), 1)
        self.assertEqual(len(errores_dsl('a | select | A')), 1)               # select sin opciones
        self.assertEqual(len(errores_dsl('a | text\na | text')), 1)           # duplicado
        w = widgets.obtener('form_dinamico_widget')
        self.assertTrue(w.validar_config({'campos': ''}))
        self.assertEqual(w.validar_config({'campos': dsl}), [])

    def test_form_dinamico_lee_valida_y_puntua(self):
        dsl = 'tipo|text|Tipo||*\naltura|number|Altura\nestado|select|Estado|Bueno,Malo|*\nacceso|toggle|Acceso'
        w = widgets.obtener('form_dinamico_widget')
        cfg = {'campos': dsl}
        datos, errs = w.leer({'form_dinamico_widget__tipo': 'Torre', 'form_dinamico_widget__altura': '12,5',
                              'form_dinamico_widget__estado': 'Malo'}, {}, cfg)
        self.assertEqual((errs, datos), ([], {'tipo': 'Torre', 'altura': 12.5, 'estado': 'Malo', 'acceso': False}))
        self.assertEqual(w.nivel(datos, cfg, ctx(self.r)), 3)
        self.assertEqual(w.nivel({'tipo': 'Torre'}, cfg, ctx(self.r)), 2)
        self.assertEqual(w.nivel({}, cfg, ctx(self.r)), 1)
        for malo in ({'form_dinamico_widget__estado': 'Inventado', 'form_dinamico_widget__tipo': 'x'},
                     {'form_dinamico_widget__altura': 'abc', 'form_dinamico_widget__tipo': 'x', 'form_dinamico_widget__estado': 'Bueno'},
                     {'form_dinamico_widget__estado': 'Bueno'}):          # falta el obligatorio «tipo»
            self.assertTrue(w.leer(malo, {}, cfg)[1], malo)

    def test_form_dinamico_toggle_marcado(self):
        w = widgets.obtener('form_dinamico_widget')
        datos, _ = w.leer({'form_dinamico_widget__acceso': 'on'}, {}, {'campos': 'acceso|toggle|Acceso'})
        self.assertEqual(datos, {'acceso': True})

    def test_ubicacion(self):
        w, (datos, errs) = self.leer('ubicacion_widget', lat='-33,4569', lon='-70.6483', accuracy='12.5')
        self.assertEqual((errs, datos), ([], {'lat': -33.4569, 'lon': -70.6483, 'accuracy': 12.5}))
        self.assertEqual(w.nivel(datos, {}, ctx(self.r)), 3)
        for malo in ({'lat': '95', 'lon': '10'}, {'lat': '10', 'lon': '200'}, {'lat': 'x', 'lon': '1'}, {'lat': '10'}):
            self.assertTrue(self.leer('ubicacion_widget', **malo)[1][1], malo)
        self.assertEqual(self.leer('ubicacion_widget')[1], ({}, []))         # vacía es válida (nivel 1)
        self.assertEqual(w.nivel({}, {}, ctx(self.r)), 1)

    def test_las_coordenadas_se_repintan_con_punto_decimal(self):
        w = widgets.obtener('ubicacion_widget')
        c = w.contexto({'lat': -33.4569, 'lon': -70.0, 'accuracy': 12.0}, {}, ctx(self.r))
        self.assertEqual((c['lat'], c['lon'], c['accuracy']), ('-33.4569', '-70', '12'))

    def test_ubicacion_calcula_la_distancia_al_proyecto(self):
        ProyectoUbicacion.objects.create(proyecto=self.p1, etiqueta='Sede', lat='-33.0000', lon='-70.0000')
        r = RegTxtss.objects.get(pk=self.r.pk)
        w = widgets.obtener('ubicacion_widget')
        c = w.contexto({'lat': -33.0009, 'lon': -70.0}, {}, ctx(r))
        self.assertEqual(c['referencia'], 'Poste Norte')
        self.assertTrue(c['distancia'].endswith(' m'))
        self.assertIn('100 m', c['distancia'])

    def test_distancia_se_calcula_en_el_servidor(self):
        w, (datos, errs) = self.leer('distancia_widget', lat1='0', lon1='0', lat2='0', lon2='1')
        self.assertEqual(errs, [])
        self.assertAlmostEqual(datos['distancia_metros'], 111195.0, delta=100)
        self.assertEqual(w.nivel(datos, {}, ctx(self.r)), 3)
        _w, (parcial, _e) = self.leer('distancia_widget', lat1='1', lon1='1')
        self.assertNotIn('distancia_metros', parcial)
        self.assertEqual(w.nivel(parcial, {}, ctx(self.r)), 2)
        self.assertTrue(self.leer('distancia_widget', lat1='999', lon1='0')[1][1])

    def test_widgets_de_fotos_validan_su_configuracion(self):
        for slug in ('camera_widget', 'camera_libro_widget'):
            w = widgets.obtener(slug)
            self.assertEqual(w.validar_config({'foto_min': 4, 'opcional': True}), [])
            self.assertTrue(w.validar_config({'foto_min': 'x'}))
            self.assertTrue(w.validar_config({'foto_min': -1}))
            self.assertTrue(w.validar_config({'etapa': ''}))
        imgs = widgets.obtener('imgs_desc_widget')
        self.assertTrue(imgs.validar_config({}))
        self.assertEqual(imgs.validar_config({'descripciones': 'Frente, Lateral'}), [])


class PlantillaTests(BaseRegistros):
    def crear(self, clave='txtss', tipo=None, activa=True, empresa=None, nombre='P'):
        return Plantilla.objects.create(empresa=empresa or self.a, nombre=nombre, tipo_registro=clave, tipo_proyecto=tipo, activa=activa)

    def test_prefiere_la_del_tipo_de_proyecto_y_cae_a_la_general(self):
        general, poste = self.crear(nombre='general'), self.crear(tipo=self.poste, nombre='poste')
        r_poste = RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1)
        r_torre = RegTxtss.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1)
        self.assertEqual(servicios.plantilla_de(r_poste, 'txtss'), poste)
        self.assertEqual(servicios.plantilla_de(r_torre, 'txtss'), general)

    def test_sin_plantilla_o_inactiva_o_de_otra_empresa_o_otro_tipo(self):
        r = RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1)
        self.assertIsNone(servicios.plantilla_de(r, 'txtss'))
        self.crear(activa=False)
        self.crear(empresa=self.b, nombre='ajena')
        self.crear(clave='construccion', nombre='otro tipo')
        self.assertIsNone(servicios.plantilla_de(r, 'txtss'))

    def test_una_sola_plantilla_activa_por_combinacion(self):
        from django.db import IntegrityError, transaction
        self.crear()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.crear(nombre='otra')
        self.crear(nombre='inactiva', activa=False)       # las inactivas no cuentan
        self.crear(tipo=self.poste, nombre='con tipo')    # otra combinación

    def test_el_tipo_de_proyecto_debe_ser_de_la_empresa(self):
        from django.core.exceptions import ValidationError
        ajeno = self.pb.tipo or __import__('proyectos.models', fromlist=['TipoProyecto']).TipoProyecto.objects.create(empresa=self.b, nombre='X')
        with self.assertRaises(ValidationError):
            Plantilla(empresa=self.a, nombre='x', tipo_registro='txtss', tipo_proyecto=ajeno).clean()


class MotorBase(BaseRegistros):
    """Plantilla TX/TSS con 3 pasos: «datos» (comentario + lista), «medidas» (formulario) y «fotos» (cámara)."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        ctx_ = override_settings(MEDIA_ROOT=str(self.tmp), STORAGES=STORAGES_TEST)
        ctx_.enable()
        self.addCleanup(ctx_.disable)
        self.plantilla = Plantilla.objects.create(empresa=self.a, nombre='TX', tipo_registro='txtss')
        self.datos = self.paso('datos', 'Datos', [('comentario_widget', {'label': 'Comentario'}), ('lista_widget', {'label': 'Pendientes'})])
        self.medidas = self.paso('medidas', 'Medidas', [('form_dinamico_widget', {'campos': 'altura|number|Altura||*\nestado|select|Estado|Bueno,Malo'})])
        self.fotos = self.paso('fotos', 'Fotos', [('camera_widget', {'foto_min': 2})])
        self.r = RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1)

    def paso(self, nombre, titulo, ws):
        p = Paso.objects.create(empresa=self.a, nombre=nombre, titulo=titulo)
        for i, (slug, cfg) in enumerate(ws, 1):
            PasoWidget.objects.create(paso=p, widget_slug=slug, orden=i, config=cfg)
        PasoAsignado.objects.create(plantilla=self.plantilla, paso=p, orden=self.plantilla.asignados.count() + 1)
        return p

    def url(self, ruta='', registro=None, clave='txtss'):
        return f'/tekon/registros/{clave}/{(registro or self.r).pk}/{ruta}'

    def guardar(self, user, nombre, datos, registro=None):
        self.client.force_login(user)
        return self.client.post(self.url(f'paso/{nombre}/guardar/', registro), datos)


class MotorTests(MotorBase):
    def test_guardar_persiste_los_datos_por_widget(self):
        ok, errs = servicios.guardar_paso(self.r, self.datos, {'comentario_widget__comentario': 'Hola', 'lista_widget__entradas': 'a\nb'}, {})
        self.assertEqual((ok, errs), (True, {}))
        d = DatoPaso.objects.get()
        self.assertEqual(d.datos, {'comentario_widget': {'comentario': 'Hola'}, 'lista_widget': {'entradas': ['a', 'b']}})
        self.assertTrue(d.tiene_datos)

    def test_si_un_widget_falla_no_se_guarda_nada(self):
        ok, errs = servicios.guardar_paso(self.r, self.medidas, {'form_dinamico_widget__altura': ''}, {})    # falta el obligatorio
        self.assertFalse(ok)
        self.assertIn('form_dinamico_widget', errs)
        self.assertFalse(DatoPaso.objects.filter(paso_nombre='medidas', tiene_datos=True).exists())
        # Un paso con dos widgets: uno válido y otro inválido → tampoco guarda el válido.
        PasoWidget.objects.create(paso=self.datos, widget_slug='ubicacion_widget', orden=3, config={})
        ok, errs = servicios.guardar_paso(self.r, self.datos, {'comentario_widget__comentario': 'ok', 'ubicacion_widget__lat': '999', 'ubicacion_widget__lon': '1'}, {})
        self.assertFalse(ok)
        self.assertEqual(DatoPaso.objects.filter(paso_nombre='datos').count(), 0)

    def test_guardar_dos_veces_actualiza_sin_duplicar(self):
        servicios.guardar_paso(self.r, self.datos, {'comentario_widget__comentario': 'uno'}, {})
        servicios.guardar_paso(self.r, self.datos, {'comentario_widget__comentario': 'dos'}, {})
        self.assertEqual(DatoPaso.objects.count(), 1)
        self.assertEqual(DatoPaso.objects.get().datos['comentario_widget']['comentario'], 'dos')

    def test_vaciar_los_campos_apaga_tiene_datos(self):
        servicios.guardar_paso(self.r, self.datos, {'comentario_widget__comentario': 'x'}, {})
        servicios.guardar_paso(self.r, self.datos, {'comentario_widget__comentario': ''}, {})
        self.assertFalse(DatoPaso.objects.get().tiene_datos)

    def test_un_toggle_en_no_cuenta_como_dato(self):
        p = self.paso('t', 'T', [('form_dinamico_widget', {'campos': 'acceso|toggle|Acceso'})])
        servicios.guardar_paso(self.r, p, {}, {})
        self.assertTrue(DatoPaso.objects.get(paso_nombre='t').tiene_datos)

    def test_estado_del_registro_segun_los_pasos(self):
        color = lambda: estado.color_estado(RegTxtss.objects.with_estado().get(pk=self.r.pk))
        self.assertEqual(color(), 'rojo')
        servicios.guardar_paso(self.r, self.datos, {'comentario_widget__comentario': 'algo'}, {})
        self.assertEqual(color(), 'amarillo')
        servicios.guardar_paso(self.r, self.datos, {}, {})                       # se vacía
        self.assertEqual(color(), 'rojo')

    def test_los_pasos_opcionales_de_construccion_no_cuentan_para_el_color(self):
        v = RegConstruccion.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1)
        opcional = Paso.objects.create(empresa=self.a, nombre='obra_libro', titulo='Libro')
        obligatorio = Paso.objects.create(empresa=self.a, nombre='obra_avance', titulo='Avance')
        for p in (opcional, obligatorio):
            PasoWidget.objects.create(paso=p, widget_slug='comentario_widget', orden=1, config={})
        servicios.guardar_paso(v, opcional, {'comentario_widget__comentario': 'x'}, {})
        self.assertEqual(estado.color_estado(RegConstruccion.objects.with_estado().get(pk=v.pk)), 'rojo')
        servicios.guardar_paso(v, obligatorio, {'comentario_widget__comentario': 'x'}, {})
        self.assertEqual(estado.color_estado(RegConstruccion.objects.with_estado().get(pk=v.pk)), 'amarillo')

    def test_color_de_cada_paso(self):
        self.assertEqual(servicios.nivel_paso([], False), 'rojo')
        self.assertEqual(servicios.nivel_paso([], True), 'verde')
        self.assertEqual(servicios.nivel_paso([3, 3], True), 'verde')
        self.assertEqual(servicios.nivel_paso([1, 1], False), 'rojo')
        self.assertEqual(servicios.nivel_paso([3, 1], True), 'amarillo')
        self.assertEqual(servicios.nivel_paso([2], True), 'amarillo')

    def test_resumen_de_pasos_y_fotos(self):
        servicios.guardar_paso(self.r, self.datos, {'comentario_widget__comentario': 'x', 'lista_widget__entradas': 'a'}, {})
        colores = {p['paso'].nombre: p['color'] for p in servicios.resumen(self.r, 'txtss', self.ito1, True)}
        self.assertEqual(colores, {'datos': 'verde', 'medidas': 'rojo', 'fotos': 'rojo'})
        self.client.force_login(self.ito1)
        self.client.post(f'/tekon/registros/txtss/{self.r.pk}/fotos/fotos/subir/', {'fotos': [subida()]})
        colores = {p['paso'].nombre: p['color'] for p in servicios.resumen(self.r, 'txtss', self.ito1, True)}
        self.assertEqual(colores['fotos'], 'amarillo')        # 1 de 2 fotos mínimas
        self.client.post(f'/tekon/registros/txtss/{self.r.pk}/fotos/fotos/subir/', {'fotos': [subida('b.jpg', imagen((1, 2, 3)))]})
        colores = {p['paso'].nombre: p['color'] for p in servicios.resumen(self.r, 'txtss', self.ito1, True)}
        self.assertEqual(colores['fotos'], 'verde')

    def test_widgets_opcionales_no_pesan_en_el_color_del_paso(self):
        p = self.paso('mixto', 'Mixto', [('comentario_widget', {'label': 'a'}), ('lista_widget', {'opcional': True})])
        servicios.guardar_paso(self.r, p, {'comentario_widget__comentario': 'x'}, {})
        self.assertEqual({x['paso'].nombre: x['color'] for x in servicios.resumen(self.r, 'txtss', self.ito1, True)}['mixto'], 'verde')

    def test_widget_de_tipo_desconocido_se_ignora(self):
        PasoWidget.objects.create(paso=self.datos, widget_slug='ya_no_existe', orden=9, config={})
        self.assertEqual(len(servicios.widgets_de(self.datos)), 2)
        self.assertTrue(servicios.guardar_paso(self.r, self.datos, {'comentario_widget__comentario': 'x'}, {})[0])


class PasosVistasTests(MotorBase):
    def test_vista_general_lista_los_pasos_con_su_color(self):
        self.client.force_login(self.ito1)
        r = self.client.get(self.url('pasos/'))
        self.assertEqual([p['paso'].nombre for p in r.context['pasos']], ['datos', 'medidas', 'fotos'])
        self.assertContains(r, 'Medidas')

    def test_sin_plantilla_avisa(self):
        self.plantilla.activa = False
        self.plantilla.save()
        self.client.force_login(self.ito1)
        r = self.client.get(self.url('pasos/'))
        self.assertFalse(r.context['hay_plantilla'])
        self.assertContains(r, 'aún no tiene una plantilla')

    def test_pagina_de_un_paso_muestra_sus_widgets_y_navegacion(self):
        self.client.force_login(self.ito1)
        r = self.client.get(self.url('paso/medidas/'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.context['anterior'].nombre, r.context['siguiente'].nombre), ('datos', 'fotos'))
        self.assertContains(r, 'name="form_dinamico_widget__altura"')
        self.assertContains(r, 'Guardar paso')

    def test_guardar_desde_la_pagina(self):
        r = self.guardar(self.ito1, 'medidas', {'form_dinamico_widget__altura': '15', 'form_dinamico_widget__estado': 'Bueno'})
        self.assertRedirects(r, self.url('paso/medidas/'), fetch_redirect_response=False)
        self.assertEqual(DatoPaso.objects.get().datos['form_dinamico_widget']['altura'], 15.0)
        # Los números se pintan con punto decimal y sin localizar (con coma, <input type=number> no los acepta).
        self.client.post(self.url('paso/medidas/guardar/'), {'form_dinamico_widget__altura': '15,5', 'form_dinamico_widget__estado': 'Bueno'})
        html = self.client.get(self.url('paso/medidas/')).content.decode()
        self.assertIn('value="15.5"', html)
        self.assertNotIn('value="15,5"', html)

    def test_con_errores_no_guarda_repinta_lo_escrito_y_responde_422(self):
        r = self.guardar(self.ito1, 'medidas', {'form_dinamico_widget__altura': 'abc', 'form_dinamico_widget__estado': 'Bueno'})
        self.assertEqual(r.status_code, 422)
        self.assertContains(r, 'debe ser un número', status_code=422)
        self.assertContains(r, 'selected', status_code=422)          # el select conserva «Bueno»
        self.assertFalse(DatoPaso.objects.exists())

    def test_ubicacion_con_error_repinta_el_valor(self):
        PasoWidget.objects.create(paso=self.datos, widget_slug='ubicacion_widget', orden=3, config={})
        r = self.guardar(self.ito1, 'datos', {'ubicacion_widget__lat': '999', 'ubicacion_widget__lon': '10'})
        self.assertEqual(r.status_code, 422)
        self.assertContains(r, 'value="999"', status_code=422)

    def test_permisos_de_lectura_y_escritura(self):
        for u in (self.visita, self.patro):
            self.assertEqual(self.guardar(u, 'medidas', {}).status_code, 403, u.email)       # ven pero no escriben
            self.client.force_login(u)
            r = self.client.get(self.url('paso/medidas/'))
            self.assertEqual(r.status_code, 200)
            self.assertNotContains(r, 'Guardar paso')
            self.assertContains(r, 'disabled')
        self.assertEqual(self.guardar(self.ito2, 'medidas', {}).status_code, 404)            # registro ajeno
        self.assertEqual(self.guardar(self.dir2, 'medidas', {}).status_code, 404)            # otra contratista
        self.assertEqual(self.guardar(self.dir1, 'medidas', {'form_dinamico_widget__altura': '1', 'form_dinamico_widget__estado': 'Bueno'}).status_code, 302)

    def test_concluido_es_solo_lectura(self):
        RegTxtss.objects.filter(pk=self.r.pk).update(concluido=True)
        self.assertEqual(self.guardar(self.ito1, 'medidas', {}).status_code, 403)
        self.assertContains(self.client.get(self.url('paso/medidas/')), 'solo lectura')

    def test_paso_que_no_es_de_la_plantilla_da_404(self):
        Paso.objects.create(empresa=self.a, nombre='suelto', titulo='Suelto')
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.get(self.url('paso/suelto/')).status_code, 404)
        self.assertEqual(self.client.get(self.url('paso/inexistente/')).status_code, 404)

    def test_otra_empresa_y_tipo_desconocido(self):
        self.client.force_login(self.pmo_b)
        self.assertEqual(self.client.get(f'/otra/registros/txtss/{self.r.pk}/pasos/').status_code, 404)
        self.client.force_login(self.pmo)
        self.assertEqual(self.client.get('/tekon/registros/inventado/1/pasos/').status_code, 404)

    def test_sin_acceso_al_reporte(self):
        from cuentas.models import RolPermiso
        RolPermiso.objects.create(rol_empresa=self.ito1.membresias.get().rol, capacidad='reg.txtss.ver', habilitado=False)
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.get(self.url('pasos/')).status_code, 403)

    def test_los_pasos_dependen_del_tipo_de_proyecto(self):
        torre = Plantilla.objects.create(empresa=self.a, nombre='Torres', tipo_registro='txtss', tipo_proyecto=self.torre)
        solo = Paso.objects.create(empresa=self.a, nombre='solo_torre', titulo='Solo torres')
        PasoAsignado.objects.create(plantilla=torre, paso=solo, orden=1)
        r_torre = RegTxtss.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1)
        self.client.force_login(self.ito1)
        self.assertEqual([p['paso'].nombre for p in self.client.get(self.url('pasos/', r_torre)).context['pasos']], ['solo_torre'])
        self.assertEqual(len(self.client.get(self.url('pasos/')).context['pasos']), 3)         # el poste usa la general

    def test_el_detalle_enlaza_a_los_pasos(self):
        self.client.force_login(self.ito1)
        r = self.client.get(f'/tekon/registros/txtss/{self.r.pk}/')
        self.assertContains(r, f'/tekon/registros/txtss/{self.r.pk}/paso/datos/')
        self.client.force_login(self.visita)
        self.assertContains(self.client.get(f'/tekon/registros/txtss/{self.r.pk}/'), f'/tekon/registros/txtss/{self.r.pk}/paso/datos/')

    def test_widget_de_fotos_enlaza_a_la_galeria_de_su_etapa(self):
        self.client.force_login(self.ito1)
        self.assertContains(self.client.get(self.url('paso/fotos/')), f'/registros/txtss/{self.r.pk}/fotos/fotos/')


class ConfigTests(BaseRegistros):
    def setUp(self):
        super().setUp()
        # Estos tests prueban la configuración de pasos desde cero: sin la plantilla estándar que toda empresa nueva recibe.
        Plantilla.objects.all().delete()
        Paso.objects.all().delete()

    def post(self, ruta, datos=None, user=None):
        self.client.force_login(user or self.root)
        return self.client.post(f'/tekon/registros/config/{ruta}', datos or {})

    def test_solo_el_superusuario_configura(self):
        for u in (self.pmo, self.dir1, self.ito1, self.visita, self.patro):
            self.client.force_login(u)
            for ruta in ('pasos/', 'plantillas/'):
                self.assertEqual(self.client.get(f'/tekon/registros/config/{ruta}').status_code, 403, (u.email, ruta))
            self.assertEqual(self.post('pasos/', {'titulo': 'x', 'nombre': 'x'}, u).status_code, 403)
        self.assertFalse(Paso.objects.exists())

    def test_crear_paso_y_nombre_unico_por_empresa(self):
        r = self.post('pasos/', {'titulo': 'Datos', 'nombre': 'datos'})
        paso = Paso.objects.get()
        self.assertRedirects(r, f'/tekon/registros/config/pasos/{paso.pk}/', fetch_redirect_response=False)
        self.assertEqual(self.post('pasos/', {'titulo': 'Otro', 'nombre': 'datos'}).status_code, 200)
        self.assertEqual(Paso.objects.count(), 1)
        Paso.objects.create(empresa=self.b, nombre='datos', titulo='De otra')          # otra empresa: mismo nombre ok

    def test_agregar_widget_valida_la_configuracion(self):
        paso = Paso.objects.create(empresa=self.a, nombre='p', titulo='P')
        agregar = lambda **d: self.post(f'pasos/{paso.pk}/widgets/agregar/', d)
        agregar(widget_slug='camera_widget', orden=1, config='{"foto_min": 3}')
        self.assertEqual(PasoWidget.objects.get().config, {'foto_min': 3})
        agregar(widget_slug='camera_widget', orden=2, config='{}')                       # repetido en el mismo paso
        agregar(widget_slug='lista_widget', orden=2, config='no es json')
        agregar(widget_slug='lista_widget', orden=2, config='[1,2]')
        agregar(widget_slug='lista_widget', orden=2, config='{"max_items": "x"}')
        agregar(widget_slug='form_dinamico_widget', orden=3, config='{"campos": "Mal | text"}')
        agregar(widget_slug='inventado', orden=4, config='{}')
        self.assertEqual(PasoWidget.objects.count(), 1)

    def test_editar_y_quitar_widget(self):
        paso = Paso.objects.create(empresa=self.a, nombre='p', titulo='P')
        pw = PasoWidget.objects.create(paso=paso, widget_slug='comentario_widget', orden=1, config={})
        self.post(f'pasos/{paso.pk}/widgets/{pw.pk}/', {'orden': 5, 'config': '{"max_length": 100}'})
        pw.refresh_from_db()
        self.assertEqual((pw.orden, pw.config), (5, {'max_length': 100}))
        self.post(f'pasos/{paso.pk}/widgets/{pw.pk}/', {'orden': 5, 'config': '{"max_length": "x"}'})
        pw.refresh_from_db()
        self.assertEqual(pw.config, {'max_length': 100})                                 # inválido: no cambia
        self.post(f'pasos/{paso.pk}/widgets/{pw.pk}/eliminar/')
        self.assertFalse(PasoWidget.objects.exists())

    def test_no_se_toca_la_configuracion_de_otra_empresa(self):
        ajeno = Paso.objects.create(empresa=self.b, nombre='p', titulo='Ajeno')
        pw = PasoWidget.objects.create(paso=ajeno, widget_slug='comentario_widget', orden=1, config={})
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(f'/tekon/registros/config/pasos/{ajeno.pk}/').status_code, 404)
        self.assertEqual(self.post(f'pasos/{ajeno.pk}/eliminar/').status_code, 404)
        self.assertEqual(self.post(f'pasos/{ajeno.pk}/widgets/{pw.pk}/eliminar/').status_code, 404)
        self.assertTrue(Paso.objects.filter(pk=ajeno.pk).exists() and PasoWidget.objects.filter(pk=pw.pk).exists())

    def test_no_se_elimina_un_paso_asignado(self):
        paso = Paso.objects.create(empresa=self.a, nombre='p', titulo='P')
        pl = Plantilla.objects.create(empresa=self.a, nombre='X', tipo_registro='txtss')
        PasoAsignado.objects.create(plantilla=pl, paso=paso, orden=1)
        self.post(f'pasos/{paso.pk}/eliminar/')
        self.assertTrue(Paso.objects.filter(pk=paso.pk).exists())
        pl.delete()
        self.post(f'pasos/{paso.pk}/eliminar/')
        self.assertFalse(Paso.objects.filter(pk=paso.pk).exists())

    def test_nombre_del_paso_no_se_cambia(self):
        paso = Paso.objects.create(empresa=self.a, nombre='fijo', titulo='Antes')
        self.post(f'pasos/{paso.pk}/', {'titulo': 'Después', 'nombre': 'cambiado'})
        paso.refresh_from_db()
        self.assertEqual((paso.titulo, paso.nombre), ('Después', 'fijo'))

    def test_plantilla_crear_asignar_ordenar_quitar(self):
        a, b = (Paso.objects.create(empresa=self.a, nombre=n, titulo=n.upper()) for n in 'ab')
        self.post('plantillas/', {'nombre': 'TX', 'tipo_registro': 'txtss', 'activa': 'on'})
        pl = Plantilla.objects.get()
        self.post(f'plantillas/{pl.pk}/pasos/agregar/', {'paso': a.pk})
        self.post(f'plantillas/{pl.pk}/pasos/agregar/', {'paso': b.pk})
        self.post(f'plantillas/{pl.pk}/pasos/agregar/', {'paso': b.pk})                  # repetido: no duplica
        self.assertEqual(list(pl.asignados.values_list('paso__nombre', flat=True)), ['a', 'b'])
        asig_b = pl.asignados.get(paso=b)
        self.post(f'plantillas/{pl.pk}/pasos/{asig_b.pk}/orden/', {'orden': '0'})
        self.assertEqual(list(pl.asignados.values_list('paso__nombre', flat=True)), ['b', 'a'])
        self.post(f'plantillas/{pl.pk}/pasos/{asig_b.pk}/quitar/')
        self.assertEqual(pl.asignados.count(), 1)

    def test_no_se_asigna_un_paso_de_otra_empresa(self):
        ajeno = Paso.objects.create(empresa=self.b, nombre='z', titulo='Z')
        pl = Plantilla.objects.create(empresa=self.a, nombre='X', tipo_registro='txtss')
        self.assertEqual(self.post(f'plantillas/{pl.pk}/pasos/agregar/', {'paso': ajeno.pk}).status_code, 404)
        self.assertFalse(pl.asignados.exists())

    def test_dos_plantillas_activas_para_lo_mismo_se_rechazan(self):
        self.post('plantillas/', {'nombre': 'A', 'tipo_registro': 'txtss', 'activa': 'on'})
        r = self.post('plantillas/', {'nombre': 'B', 'tipo_registro': 'txtss', 'activa': 'on'})
        self.assertEqual((r.status_code, Plantilla.objects.count()), (200, 1))
        self.post('plantillas/', {'nombre': 'B', 'tipo_registro': 'txtss'})               # inactiva: ok
        self.post('plantillas/', {'nombre': 'C', 'tipo_registro': 'txtss', 'tipo_proyecto': self.poste.pk, 'activa': 'on'})
        self.assertEqual(Plantilla.objects.count(), 3)

    def test_tipo_de_proyecto_de_otra_empresa_rechazado(self):
        from proyectos.models import TipoProyecto
        ajeno = TipoProyecto.objects.create(empresa=self.b, nombre='Ajeno')
        self.post('plantillas/', {'nombre': 'A', 'tipo_registro': 'txtss', 'tipo_proyecto': ajeno.pk, 'activa': 'on'})
        self.assertFalse(Plantilla.objects.exists())

    def test_ejemplo_es_idempotente(self):
        self.post('ejemplo/')
        n = (Paso.objects.count(), PasoWidget.objects.count(), Plantilla.objects.count(), PasoAsignado.objects.count())
        self.assertEqual(n, (6, 11, 2, 6))
        self.post('ejemplo/')
        self.assertEqual((Paso.objects.count(), PasoWidget.objects.count(), Plantilla.objects.count(), PasoAsignado.objects.count()), n)

    def test_comando_de_siembra(self):
        out = StringIO()
        call_command('sembrar_registros', 'tekon', stdout=out)
        self.assertIn('6 paso(s) y 2 plantilla(s)', out.getvalue())
        from django.core.management import CommandError
        with self.assertRaises(CommandError):
            call_command('sembrar_registros', 'no-existe')

    def test_menu_de_configuracion(self):
        self.client.force_login(self.root)
        nombres = [i['nombre'] for i in self.client.get('/tekon/registros/config/').context['menu_lateral']]
        self.assertIn('Pasos', nombres)
        self.assertIn('Plantillas', nombres)
        for u in (self.pmo, self.ito1):
            self.client.force_login(u)
            self.assertNotIn('Pasos', [i['nombre'] for i in self.client.get('/tekon/registros/').context['menu_lateral']])


class RecorridoCompletoTests(MotorBase):
    """De la configuración de ejemplo a un registro concluido, como lo haría una empresa nueva."""

    def test_empresa_nueva_con_la_configuracion_de_ejemplo(self):
        Plantilla.objects.all().delete()
        Paso.objects.all().delete()
        servicios.sembrar_ejemplo(self.a)
        r = RegTxtss.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1)
        self.client.force_login(self.ito1)
        pasos = self.client.get(f'/tekon/registros/txtss/{r.pk}/pasos/').context['pasos']
        self.assertEqual([p['paso'].nombre for p in pasos], ['sitio', 'inspeccion'])

        self.client.post(f'/tekon/registros/txtss/{r.pk}/paso/inspeccion/guardar/', {
            'form_dinamico_widget__tipo_estructura': 'Torre ventada', 'form_dinamico_widget__altura': '42',
            'form_dinamico_widget__estado': 'Bueno', 'form_dinamico_widget__acceso_camion': 'on'})
        self.client.post(f'/tekon/registros/txtss/{r.pk}/paso/sitio/guardar/', {
            'ubicacion_widget__lat': '-33.45', 'ubicacion_widget__lon': '-70.66', 'comentario_widget__comentario': 'ok'})
        self.client.post(f'/tekon/registros/txtss/{r.pk}/fotos/sitio/subir/', {'fotos': [subida()]})
        colores = {p['paso'].nombre: p['color'] for p in servicios.resumen(r, 'txtss', self.ito1, True)}
        self.assertEqual(colores, {'sitio': 'verde', 'inspeccion': 'verde'})
        self.assertEqual(estado.color_estado(RegTxtss.objects.with_estado().get(pk=r.pk)), 'amarillo')
        self.client.post(f'/tekon/registros/txtss/{r.pk}/concluir/')
        self.assertEqual(estado.color_estado(RegTxtss.objects.with_estado().get(pk=r.pk)), 'verde')
        self.assertEqual(self.client.post(f'/tekon/registros/txtss/{r.pk}/paso/sitio/guardar/', {}).status_code, 403)

    def test_construccion_con_la_configuracion_de_ejemplo(self):
        Plantilla.objects.all().delete()
        Paso.objects.all().delete()
        servicios.sembrar_ejemplo(self.a)
        v = RegConstruccion.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1)
        self.client.force_login(self.ito1)
        pasos = self.client.get(f'/tekon/registros/construccion/{v.pk}/pasos/').context['pasos']
        self.assertEqual([p['paso'].nombre for p in pasos], ['obra_objetivos', 'obra_avance', 'obra_electrico', 'obra_comentarios'])
        # El libro de obras (en «Actividades») y el paso Eléctrico son opcionales: no cambian el color de la visita.
        self.client.post(f'/tekon/registros/construccion/{v.pk}/fotos/obra_libro/subir/', {'fotos': [subida()]})
        self.assertEqual(estado.color_estado(RegConstruccion.objects.with_estado().get(pk=v.pk)), 'rojo')
        self.client.post(f'/tekon/registros/construccion/{v.pk}/paso/obra_objetivos/guardar/', {'lista_widget__entradas': 'Revisión de izaje'})
        self.assertEqual(estado.color_estado(RegConstruccion.objects.with_estado().get(pk=v.pk)), 'amarillo')


@override_settings(**__import__('reg_base.tests', fromlist=['AJUSTES']).AJUSTES)
class PasosMovilTests(TestCase):
    """Vista de pasos como botones táctiles y pantalla de un componente suelto (?w=)."""

    @classmethod
    def setUpTestData(cls):
        from datetime import date
        from cuentas.services import crear_empresa
        from proyectos.models import Proyecto
        from reg_txtss.models import RegTxtss
        from .models import Paso, PasoAsignado, PasoWidget, Plantilla
        from reg_base import tipos
        cls.empresa = crear_empresa(nombre='Tekon', slug='tekon', modulos=['reg'])
        tipos.habilitar(cls.empresa, 'txtss')
        cls.user = User.objects.create_superuser('adm@x.cl', 'x')
        cls.proyecto = Proyecto.objects.create(empresa=cls.empresa, nombre='Sitio', codigo='S1')
        cls.reg = RegTxtss(empresa=cls.empresa, proyecto=cls.proyecto, user=cls.user, fecha=date.today())
        cls.reg.save()
        paso = Paso.objects.create(empresa=cls.empresa, nombre='sitio', titulo='Sitio')
        PasoWidget.objects.create(paso=paso, widget_slug='ubicacion_widget', orden=1)
        PasoWidget.objects.create(paso=paso, widget_slug='comentario_widget', orden=2, config={'opcional': True})
        PasoWidget.objects.create(paso=paso, widget_slug='camera_widget', orden=3, config={'foto_min': 2})
        pl = Plantilla.objects.create(empresa=cls.empresa, nombre='P', tipo_registro='txtss')
        PasoAsignado.objects.create(plantilla=pl, paso=paso, orden=1)

    def setUp(self):
        self.client.force_login(self.user)

    def test_pasos_muestra_un_boton_por_componente(self):
        r = self.client.get(f'/tekon/registros/txtss/{self.reg.pk}/pasos/')
        self.assertEqual(r.status_code, 200)
        botones = r.context['pasos'][0]['botones']
        self.assertEqual([b['slug'] for b in botones], ['ubicacion_widget', 'comentario_widget', 'camera_widget'])
        self.assertEqual([b['estado'] for b in botones], ['rojo', 'opcional', 'rojo'])
        self.assertEqual(botones[2]['galeria'], 'sitio')
        self.assertContains(r, '?w=ubicacion_widget')

    def test_componente_suelto_y_guardado_parcial(self):
        from .models import DatoPaso
        base = f'/tekon/registros/txtss/{self.reg.pk}/paso/sitio/'
        r = self.client.get(base + '?w=ubicacion_widget')
        self.assertEqual([b['pw'].widget_slug for b in r.context['bloques']], ['ubicacion_widget'])
        self.assertEqual(self.client.get(base + '?w=no_existe').status_code, 404)
        # guardar un componente no pisa los datos de los demás
        self.client.post(base + 'guardar/', {'comentario_widget__comentario': 'hola'})
        r = self.client.post(base + 'guardar/', {'w': 'ubicacion_widget', 'ubicacion_widget__lat': '-33.4',
                                                'ubicacion_widget__lon': '-70.6'})
        self.assertRedirects(r, f'/tekon/registros/txtss/{self.reg.pk}/pasos/', fetch_redirect_response=False)
        datos = DatoPaso.objects.get(paso_nombre='sitio').datos
        self.assertEqual(datos['ubicacion_widget']['lat'], -33.4)
        self.assertEqual(datos['comentario_widget']['comentario'], 'hola')
