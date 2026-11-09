"""Widgets de mapa (mapa_1p, mapa_2_puntos): coordenadas, nivel, contexto, imagen estática y permisos."""
import io
from unittest import mock

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

from proyectos.models import ProyectoUbicacion

from . import mapas, widgets
from .models import DatoPaso, ImagenMapa, Paso, PasoAsignado, PasoWidget
from .tests import MotorBase, ctx
from .widgets.base import Contexto


def png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 64), (20, 90, 160)).save(buf, 'PNG')
    return buf.getvalue()


def respuesta(codigo=200, contenido=None):
    r = mock.Mock()
    r.status_code, r.content, r.text = codigo, contenido if contenido is not None else png(), 'x'
    return r


CLAVE = override_settings(GOOGLE_MAPS_API_KEY='clave-de-prueba')
SIN_CLAVE = override_settings(GOOGLE_MAPS_API_KEY='')


class MapaBase(MotorBase):
    """Pasos «sitio» (con ubicación + mapa de un punto) y «enlace» (mapa de dos puntos entre «sitio» y «destino»)."""

    def setUp(self):
        super().setUp()
        self.sitio = self.paso('sitio', 'Sitio', [('ubicacion_widget', {}), ('mapa_1p', {'label': 'S', 'color': '#112233'})])
        self.destino = self.paso('destino', 'Destino', [('ubicacion_widget', {})])
        self.enlace = self.paso('enlace', 'Enlace', [('mapa_2_puntos', {'paso1': 'sitio', 'paso2': 'destino', 'label': 'Enlace'})])
        self.ct = ContentType.objects.get_for_model(type(self.r))

    def ubicar(self, paso, lat, lon, registro=None):
        r = registro or self.r
        DatoPaso.objects.update_or_create(
            content_type=ContentType.objects.get_for_model(type(r)), object_id=r.pk, paso_nombre=paso,
            defaults={'empresa_id': r.empresa_id, 'datos': {'ubicacion_widget': {'lat': lat, 'lon': lon}}, 'tiene_datos': True})

    def w(self, slug):
        return widgets.obtener(slug)

    def cx(self, paso, escribe=False):
        return Contexto(registro=self.r, paso=paso, clave='txtss', user=self.ito1, puede_escribir=escribe)

    def url_mapa(self, accion, nombre='enlace'):
        return self.url(f'paso/{nombre}/mapa/{accion}/')


class WidgetsMapaTests(MapaBase):
    def test_estan_registrados_y_no_guardan_datos(self):
        for slug in ('mapa_1p', 'mapa_2_puntos'):
            w = self.w(slug)
            self.assertIsNotNone(w)
            self.assertFalse(w.guarda_datos)

    def test_validar_config(self):
        m1, m2 = self.w('mapa_1p'), self.w('mapa_2_puntos')
        self.assertEqual(m1.validar_config({}), [])
        self.assertEqual(m1.validar_config({'color': '#aabbcc', 'label': 'M'}), [])
        self.assertTrue(m1.validar_config({'color': 'rojo'}))
        self.assertTrue(m1.validar_config({'label': ''}))
        self.assertTrue(m2.validar_config({}))                                             # paso1 y paso2 son obligatorios
        self.assertTrue(m2.validar_config({'paso1': 'a'}))
        self.assertEqual(m2.validar_config({'paso1': 'a', 'paso2': 'b', 'color1': '#e74c3c'}), [])
        self.assertTrue(m2.validar_config({'paso1': 'a', 'paso2': 'b', 'color2': '#12'}))

    def test_mapa_1p_usa_la_ubicacion_del_propio_paso(self):
        self.ubicar('sitio', -33.45, -70.66)
        self.assertEqual(mapas.puntos_de_widget('mapa_1p', {'label': 'sitio', 'color': '#112233'}, self.r, self.sitio),
                         [{'lat': -33.45, 'lon': -70.66, 'label': 'S', 'color': '#112233'}])

    def test_mapa_1p_cae_a_la_ubicacion_del_proyecto_con_el_nombre_del_paso_y_luego_al_proyecto(self):
        self.assertEqual(mapas.puntos_de_widget('mapa_1p', {}, self.r, self.sitio), [])
        ProyectoUbicacion.objects.create(proyecto=self.p1, etiqueta='Principal', lat='-33.100000', lon='-70.200000')
        p = mapas.puntos_de_widget('mapa_1p', {}, self.r, self.sitio)
        self.assertEqual((p[0]['lat'], p[0]['lon'], p[0]['label'], p[0]['color']), (-33.1, -70.2, 'M', '#3b82f6'))
        ProyectoUbicacion.objects.create(proyecto=self.p1, etiqueta='Sítio', lat='-34.000000', lon='-71.000000')   # sin tildes/mayúsculas
        p = mapas.puntos_de_widget('mapa_1p', {}, self.r, self.sitio)
        self.assertEqual((p[0]['lat'], p[0]['lon']), (-34.0, -71.0))

    def test_mapa_1p_con_config_paso_toma_ese_paso(self):
        self.ubicar('destino', -30.0, -71.0)
        p = mapas.puntos_de_widget('mapa_1p', {'paso': 'destino'}, self.r, self.sitio)
        self.assertEqual((p[0]['lat'], p[0]['lon']), (-30.0, -71.0))

    def test_mapa_2_puntos_lee_los_pasos_de_la_config(self):
        cfg = {'paso1': 'sitio', 'paso2': 'destino', 'label1': 'P', 'color1': '#ff0000', 'label2': 'm'}
        self.assertEqual(mapas.puntos_de_widget('mapa_2_puntos', cfg, self.r, self.enlace), [])
        self.ubicar('sitio', -33.0, -70.0)
        self.assertEqual(len(mapas.puntos_de_widget('mapa_2_puntos', cfg, self.r, self.enlace)), 1)
        self.ubicar('destino', -33.01, -70.01)
        puntos = mapas.puntos_de_widget('mapa_2_puntos', cfg, self.r, self.enlace)
        self.assertEqual([(p['label'], p['color']) for p in puntos], [('P', '#ff0000'), ('M', '#0054ff')])
        # Sin el primer punto no hay mapa aunque exista el segundo.
        DatoPaso.objects.filter(paso_nombre='sitio').delete()
        self.assertEqual(mapas.puntos_de_widget('mapa_2_puntos', cfg, self.r, self.enlace), [])

    def test_nivel_de_cada_estado(self):
        m1, m2 = self.w('mapa_1p'), self.w('mapa_2_puntos')
        cfg2 = {'paso1': 'sitio', 'paso2': 'destino'}
        with CLAVE:
            self.assertEqual(m1.nivel({}, {}, self.cx(self.sitio)), 1)                    # sin coordenadas
            self.ubicar('sitio', -33.0, -70.0)
            self.assertEqual(m1.nivel({}, {}, self.cx(self.sitio)), 2)                    # coordenadas, sin imagen
            self.assertEqual(m2.nivel({}, cfg2, self.cx(self.enlace)), 2)                 # solo 1 de 2 puntos
            ImagenMapa.objects.create(empresa=self.a, content_type=self.ct, object_id=self.r.pk, etapa='sitio',
                                      imagen='x/y.png', zoom=20, coordenadas=[])
            self.assertEqual(m1.nivel({}, {}, self.cx(self.sitio)), 3)                    # imagen guardada
            self.ubicar('destino', -33.01, -70.01)
            self.assertEqual(m2.nivel({}, cfg2, self.cx(self.enlace)), 2)                 # 2 puntos, sin imagen
        with SIN_CLAVE:
            self.assertEqual(m2.nivel({}, cfg2, self.cx(self.enlace)), 3)                 # sin clave: ya no se puede pedir más

    def test_contexto_informa_lo_que_falta_y_las_urls(self):
        m2 = self.w('mapa_2_puntos')
        cfg = {'paso1': 'sitio', 'paso2': 'destino', 'label': 'Enlace'}
        c = m2.contexto({}, cfg, self.cx(self.enlace, escribe=True))
        self.assertIn('«sitio»', c['faltantes'])
        self.assertIn('«destino»', c['faltantes'])
        self.assertEqual((c['etiqueta'], c['puntos']), ('Enlace', []))
        self.assertTrue(c['save_url'].endswith('/paso/enlace/mapa/guardar/'))
        self.assertEqual(m2.contexto({}, cfg, self.cx(self.enlace, escribe=False))['save_url'], '')   # solo lectura
        self.ubicar('sitio', -33.0, -70.0)
        self.ubicar('destino', -33.0, -70.001)
        c = m2.contexto({}, cfg, self.cx(self.enlace))
        self.assertEqual(c['faltantes'], '')
        self.assertTrue(c['distancia'].endswith('m'))
        self.assertIn('"lat": -33.0', c['puntos_json'])
        m1 = self.w('mapa_1p').contexto({}, {}, self.cx(Paso(nombre='otro')))
        self.assertIn('captúrala en este paso', m1['faltantes'])

    def test_distancias_y_zoom(self):
        a, b, c = ({'lat': -33.0, 'lon': -70.0}, {'lat': -33.0, 'lon': -70.001}, {'lat': -33.0, 'lon': -70.002})
        total, desfase = mapas.distancias([a, b])
        self.assertAlmostEqual(total, 93.3, delta=1)
        self.assertEqual(total, desfase)
        total3, desfase3 = mapas.distancias([a, b, c])
        self.assertAlmostEqual(total3, 2 * total, delta=1)
        self.assertIsNone(desfase3)
        self.assertEqual(mapas.distancias([a]), (None, None))
        self.assertEqual(mapas.calcular_zoom_optimo([a]), 20)
        self.assertEqual(mapas.calcular_zoom_optimo([a, dict(a)]), 21)
        self.assertGreater(mapas.calcular_zoom_optimo([a, b]), mapas.calcular_zoom_optimo([a, {'lat': -34.0, 'lon': -71.0}]))


class ImagenEstaticaTests(MapaBase):
    def test_descargar_imagen_arma_la_peticion_a_google(self):
        puntos = [{'lat': -33.0, 'lon': -70.0, 'label': 'a', 'color': '#e74c3c'},
                  {'lat': -33.1, 'lon': -70.1, 'label': 'B', 'color': '#0054ff'}]
        with CLAVE, mock.patch('reg_actividades.mapas.requests.get', return_value=respuesta()) as get:
            self.assertEqual(mapas.descargar_imagen(puntos), png())
        parametros = dict(get.call_args.kwargs['params'])
        self.assertEqual((parametros['key'], parametros['size'], parametros['maptype']), ('clave-de-prueba', '640x640', 'hybrid'))
        marcadores = [v for k, v in get.call_args.kwargs['params'] if k == 'markers']
        self.assertEqual(marcadores[0], 'color:0xE74C3C|size:mid|label:A|-33.0,-70.0')
        self.assertEqual(len(marcadores), 2)

    def test_sin_clave_o_sin_puntos_o_con_error_de_google_no_hay_imagen(self):
        p = [{'lat': 1.0, 'lon': 1.0, 'label': 'M', 'color': '#3b82f6'}]
        with SIN_CLAVE, mock.patch('reg_actividades.mapas.requests.get') as get:
            self.assertIsNone(mapas.descargar_imagen(p))
            get.assert_not_called()
        with CLAVE:
            self.assertIsNone(mapas.descargar_imagen([]))
            with mock.patch('reg_actividades.mapas.requests.get', return_value=respuesta(403)):
                self.assertIsNone(mapas.descargar_imagen(p))
            import requests
            with mock.patch('reg_actividades.mapas.requests.get', side_effect=requests.ConnectionError):
                self.assertIsNone(mapas.descargar_imagen(p))

    def test_el_ajuste_existe_y_el_csp_permite_las_teselas(self):
        self.assertTrue(hasattr(settings, 'GOOGLE_MAPS_API_KEY'))
        img = settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['img-src']
        self.assertIn('https://server.arcgisonline.com', img)
        self.assertIn('https://*.tile.openstreetmap.org', img)
        self.assertNotIn("'unsafe-inline'", settings.CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src'])


class VistasMapaTests(MapaBase):
    def guardar_mapa(self, user, nombre='enlace', registro=None):
        self.client.force_login(user)
        return self.client.post(self.url(f'paso/{nombre}/mapa/guardar/', registro))

    def preparar(self):
        self.ubicar('sitio', -33.0, -70.0)
        self.ubicar('destino', -33.0, -70.001)

    @CLAVE
    def test_guardar_genera_y_reemplaza_la_imagen(self):
        self.preparar()
        with mock.patch('reg_actividades.mapas.requests.get', return_value=respuesta()) as get:
            r = self.guardar_mapa(self.ito1)
            self.assertEqual(r.status_code, 200, r.content)
            d = r.json()
            self.assertTrue(d['success'])
            self.assertAlmostEqual(d['distancia_total_metros'], 93.3, delta=1)
            self.assertIn('/paso/enlace/mapa/imagen/', d['image_url'])
            obj = ImagenMapa.objects.get()
            self.assertEqual((obj.etapa, obj.empresa_id, obj.registro), ('enlace', self.a.pk, self.r))
            self.assertEqual(len(obj.coordenadas), 2)
            self.assertIn(f'{self.a.pk}/reg/', obj.imagen.name)                     # storage privado, por empresa
            primera = obj.imagen.name
            self.assertEqual(self.guardar_mapa(self.ito1).status_code, 200)
            obj.refresh_from_db()
            self.assertEqual(ImagenMapa.objects.count(), 1)                          # una por registro y paso
            self.assertNotEqual(obj.imagen.name, primera)
            self.assertFalse(obj.imagen.storage.exists(primera))                      # el archivo anterior se borra
            self.assertEqual(get.call_count, 2)

    @CLAVE
    def test_guardar_ignora_el_cuerpo_y_usa_lo_guardado(self):
        self.preparar()
        self.client.force_login(self.ito1)
        with mock.patch('reg_actividades.mapas.requests.get', return_value=respuesta()):
            self.client.post(self.url('paso/enlace/mapa/guardar/'), data='{"coordenadas":[{"lat":9,"lon":9}]}',
                             content_type='application/json')
        self.assertEqual(ImagenMapa.objects.get().coordenadas[0]['lat'], -33.0)

    @CLAVE
    def test_guardar_errores(self):
        with mock.patch('reg_actividades.mapas.requests.get', return_value=respuesta()):
            self.assertEqual(self.guardar_mapa(self.ito1).status_code, 400)           # sin coordenadas
            self.preparar()
            self.assertEqual(self.guardar_mapa(self.ito1, 'destino').status_code, 400)  # paso sin widget de mapa
            self.assertEqual(self.guardar_mapa(self.ito1, 'no_existe').status_code, 404)
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.get(self.url_mapa('guardar')).status_code, 405)    # solo POST
        with mock.patch('reg_actividades.mapas.requests.get', return_value=respuesta(500)):
            r = self.guardar_mapa(self.ito1)
        self.assertEqual((r.status_code, r.json()['success']), (502, False))
        self.assertEqual(ImagenMapa.objects.count(), 0)

    @CLAVE
    def test_un_fallo_de_google_conserva_la_imagen_anterior(self):
        self.preparar()
        with mock.patch('reg_actividades.mapas.requests.get', return_value=respuesta()):
            self.guardar_mapa(self.ito1)
        antes = ImagenMapa.objects.get().imagen.name
        with mock.patch('reg_actividades.mapas.requests.get', return_value=respuesta(500)):
            self.assertEqual(self.guardar_mapa(self.ito1).status_code, 502)
        self.assertEqual(ImagenMapa.objects.get().imagen.name, antes)

    @SIN_CLAVE
    def test_sin_clave_responde_503_con_mensaje_claro(self):
        self.preparar()
        r = self.guardar_mapa(self.ito1)
        self.assertEqual(r.status_code, 503)
        self.assertIn('clave de Google Maps', r.json()['error'])

    @CLAVE
    def test_permisos_de_guardar(self):
        self.preparar()
        with mock.patch('reg_actividades.mapas.requests.get', return_value=respuesta()):
            self.assertEqual(self.guardar_mapa(self.visita).status_code, 403)         # observador: no carga datos
            self.assertEqual(self.guardar_mapa(self.ito2).status_code, 404)           # otro ITO: fuera de alcance
            self.assertIn(self.guardar_mapa(self.pmo_b).status_code, (403, 404))      # persona de otra empresa
            self.client.logout()
            self.assertEqual(self.client.post(self.url_mapa('guardar')).status_code, 302)   # sin sesión: al login
            self.r.concluido = True
            self.r.save()
            self.assertEqual(self.guardar_mapa(self.ito1).status_code, 403)           # registro concluido: solo lectura
        self.assertEqual(ImagenMapa.objects.count(), 0)

    @CLAVE
    def test_la_imagen_se_sirve_con_permiso_de_lectura(self):
        self.preparar()
        with mock.patch('reg_actividades.mapas.requests.get', return_value=respuesta()):
            self.guardar_mapa(self.ito1)
        self.client.force_login(self.ito1)
        r = self.client.get(self.url_mapa('imagen'))
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'image/png'))
        self.assertEqual(b''.join(r.streaming_content), png())
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.client.get(self.url_mapa('imagen'), HTTP_IF_NONE_MATCH=r['ETag']).status_code, 304)
        for u, esperado in ((self.pmo, 200), (self.visita, 200), (self.ito2, 404)):    # observador ve todo; otro ITO no
            self.client.force_login(u)
            self.assertEqual(self.client.get(self.url_mapa('imagen')).status_code, esperado, u.email)
        self.client.force_login(self.pmo_b)
        self.assertIn(self.client.get(self.url_mapa('imagen')).status_code, (403, 404))
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.get(self.url_mapa('imagen').replace('/enlace/', '/sitio/')).status_code, 404)   # sin imagen

    def test_la_pagina_del_paso_carga_leaflet_y_muestra_el_mapa(self):
        self.preparar()
        self.client.force_login(self.ito1)
        with CLAVE:
            r = self.client.get(self.url('paso/enlace/'))
        self.assertContains(r, 'vendor/leaflet/leaflet.js')
        self.assertContains(r, 'js/reg-mapa.js')
        self.assertContains(r, 'data-mapa-guardar')
        self.assertContains(r, 'data-save-url="/tekon/registros/txtss/')
        self.assertContains(r, 'Guardar imagen')
        self.assertNotContains(self.client.get(self.url('paso/destino/')), 'leaflet.js')   # solo si hay un mapa

    def test_sin_clave_se_ven_los_puntos_con_aviso_y_sin_boton(self):
        self.preparar()
        self.client.force_login(self.ito1)
        with SIN_CLAVE:
            r = self.client.get(self.url('paso/enlace/'))
        self.assertContains(r, 'data-mapa-lienzo')
        self.assertContains(r, 'GOOGLE_MAPS_API_KEY')
        self.assertNotContains(r, 'data-mapa-guardar')

    @CLAVE
    def test_sin_coordenadas_dice_que_falta_y_no_ofrece_guardar(self):
        self.client.force_login(self.ito1)
        r = self.client.get(self.url('paso/enlace/'))
        self.assertContains(r, 'Falta la ubicación de')
        self.assertNotContains(r, 'data-mapa-guardar')
        self.assertNotContains(r, 'data-mapa-lienzo')

    @CLAVE
    def test_solo_lectura_no_ofrece_guardar(self):
        self.preparar()
        self.client.force_login(self.visita)       # el observador ve el mapa pero no puede cargar datos
        r = self.client.get(self.url('paso/enlace/'))
        self.assertNotContains(r, 'data-mapa-guardar')


class RegeneracionTests(MapaBase):
    """Al corregir la ubicación de un paso, el mapa de 2 puntos que lo usa se regenera (solo si ya existía y cambió)."""

    def llamadas(self, user, nombre, datos):
        with mock.patch('reg_actividades.mapas.requests.get', return_value=respuesta()) as get, \
                self.captureOnCommitCallbacks(execute=True):
            r = self.guardar(user, nombre, datos)
        self.assertEqual(r.status_code, 302, r.content)
        return get.call_count

    @CLAVE
    def test_regenera_solo_si_la_imagen_existia_y_las_coordenadas_cambiaron(self):
        loc = lambda lat, lon: {'ubicacion_widget__lat': lat, 'ubicacion_widget__lon': lon}
        self.ubicar('sitio', -33.0, -70.0)
        self.ubicar('destino', -33.0, -70.001)
        # Sin imagen previa: guardar la ubicación no genera nada (la primera la pide la persona).
        self.assertEqual(self.llamadas(self.ito1, 'destino', loc('-33.0', '-70.001')), 0)
        with mock.patch('reg_actividades.mapas.requests.get', return_value=respuesta()):
            self.client.force_login(self.ito1)
            self.client.post(self.url_mapa('guardar'))
        self.assertEqual(ImagenMapa.objects.count(), 1)
        # Mismos valores: sin llamada a Google (no gasta cuota).
        self.assertEqual(self.llamadas(self.ito1, 'destino', loc('-33.0', '-70.001')), 0)
        # Ubicación corregida: se regenera una vez y las coordenadas guardadas se actualizan.
        self.assertEqual(self.llamadas(self.ito1, 'destino', loc('-33.5', '-70.5')), 1)
        self.assertEqual(ImagenMapa.objects.get().coordenadas[1]['lat'], -33.5)
        # Un paso que el mapa no usa no dispara nada.
        self.assertEqual(self.llamadas(self.ito1, 'datos', {'comentario_widget__comentario': 'hola'}), 0)

    @SIN_CLAVE
    def test_sin_clave_no_intenta_regenerar(self):
        self.ubicar('sitio', -33.0, -70.0)
        self.ubicar('destino', -33.0, -70.001)
        self.assertEqual(self.llamadas(self.ito1, 'destino', {'ubicacion_widget__lat': '-1', 'ubicacion_widget__lon': '-1'}), 0)
