from reg_base.geo import distancia_m, formatear_distancia

from . import registrar
from .base import WidgetBase, texto_numero
from .ubicacion import _coordenada

PUNTOS = (('lat1', 'Latitud A', -90, 90), ('lon1', 'Longitud A', -180, 180),
          ('lat2', 'Latitud B', -90, 90), ('lon2', 'Longitud B', -180, 180))


@registrar
class DistanciaWidget(WidgetBase):
    slug = 'distancia_widget'
    nombre = 'Distancia entre puntos'
    plantilla = 'reg_actividades/widgets/distancia.html'

    def leer(self, post, files, config, ctx=None):
        datos, errores = {}, []
        for campo, etiqueta, minimo, maximo in PUNTOS:
            v, err = _coordenada(post.get(self.nombre_campo(campo)), minimo, maximo)
            if err:
                errores.append(f'{etiqueta}: {err}.')
            elif v is not None:
                datos[campo] = v
        if errores:   # se devuelve lo escrito para volver a mostrarlo junto al error
            return {k: post.get(self.nombre_campo(k), '') for k, *_ in PUNTOS}, errores
        if all(k in datos for k, *_ in PUNTOS):
            datos['distancia_metros'] = round(distancia_m(datos['lat1'], datos['lon1'], datos['lat2'], datos['lon2']), 1)
        return datos, []

    def nivel(self, datos, config, ctx):
        datos = datos or {}
        if datos.get('distancia_metros') is not None:
            return 3
        return 2 if datos else 1

    def contexto(self, datos, config, ctx):
        datos = datos or {}
        return {
            'campos': [{'nombre': self.nombre_campo(k), 'etiqueta': e, 'valor': texto_numero(datos.get(k))} for k, e, *_ in PUNTOS],
            'etiqueta': config.get('label', self.nombre),
            'distancia': formatear_distancia(datos.get('distancia_metros')),
            'calculada': datos.get('distancia_metros') is not None,
        }
