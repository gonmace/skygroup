"""Widgets de mapa: dibujan en Leaflet las ubicaciones ya capturadas en el registro y guardan una imagen estática
(Google Static Maps) para el informe. No capturan datos propios (`guarda_datos = False`): las coordenadas salen de los
widgets de ubicación de los pasos (o de las ubicaciones del proyecto) y la imagen vive en `ImagenMapa`."""
import json

from django.urls import reverse

from reg_base.geo import formatear_distancia

from .. import mapas
from . import registrar
from .base import WidgetBase


# Qué significa cada letra de los marcadores, para la leyenda de los mapas de dos puntos.
NOMBRES_LETRA = {'R': 'Referencia', 'I': 'Inspección', 'P': 'Poste', 'S': 'Sitio', 'E': 'Eléctrico'}


class _MapaBase(WidgetBase):
    guarda_datos = False
    plantilla = 'reg_actividades/widgets/mapa.html'
    esperados = 1   # puntos que debe tener para considerarse completo

    def validar_config(self, config):
        errores = []
        for clave in self._claves_color():
            if clave in config and not mapas.color_valido(config[clave]):
                errores.append(f'{clave} debe ser un color hexadecimal de 6 dígitos (p. ej. #e74c3c).')
        for clave in self._claves_letra():
            if clave in config and not (isinstance(config[clave], str) and config[clave].strip()):
                errores.append(f'{clave} debe ser una letra o símbolo.')
        return errores

    def _claves_color(self):
        return ()

    def _claves_letra(self):
        return ()

    def titulo(self, config):
        return config.get('titulo') or self.nombre

    def puntos(self, config, ctx):
        return mapas.puntos_de_widget(self.slug, config, ctx.registro, ctx.paso)

    def nivel(self, datos, config, ctx):
        puntos = self.puntos(config, ctx)
        if not puntos:
            return 1
        if len(puntos) < self.esperados:
            return 2
        # Sin clave de Google no se puede generar la imagen: lo capturado ya es todo lo que se puede pedir.
        return 3 if (mapas.imagen_de(ctx.registro, ctx.paso.nombre) or not mapas.hay_clave()) else 2

    def faltantes(self, config, ctx):
        """Mensaje de qué falta para dibujar el mapa ('' si ya hay lo necesario)."""
        return ''

    def contexto(self, datos, config, ctx):
        puntos = self.puntos(config, ctx)
        imagen = mapas.imagen_de(ctx.registro, ctx.paso.nombre)
        kw = {'clave': ctx.clave, 'pk': ctx.registro.pk, 'nombre': ctx.paso.nombre}
        total, desfase = (imagen.distancia_total_metros, imagen.desfase_metros) if imagen else mapas.distancias(puntos)
        return {
            'etiqueta': self.titulo(config), 'puntos': puntos, 'puntos_json': json.dumps(puntos),
            'leyenda': [{'letra': p['label'], 'nombre': NOMBRES_LETRA.get(p['label'], ''), 'color': p['color']}
                        for p in puntos] if len(puntos) > 1 else [],
            'hay_clave': mapas.hay_clave(), 'imagen': imagen,
            'imagen_url': reverse('reg_actividades:mapa_imagen', kwargs=kw) if imagen else '',
            'save_url': reverse('reg_actividades:mapa_guardar', kwargs=kw) if ctx.puede_escribir else '',
            'distancia': formatear_distancia(total) if total is not None else '',
            'faltantes': '' if len(puntos) >= self.esperados else self.faltantes(config, ctx),
        }


@registrar
class Mapa1pWidget(_MapaBase):
    slug = 'mapa_1p'
    nombre = 'Mapa de un punto'
    esperados = 1

    def _claves_color(self):
        return ('color',)

    def _claves_letra(self):
        return ('label',)

    def faltantes(self, config, ctx):
        paso = config.get('paso')
        if paso:
            return f'Falta la ubicación del paso «{paso}».'
        return 'Falta la ubicación: captúrala en este paso (widget «Ubicación GPS») o define las coordenadas del proyecto.'


@registrar
class Mapa2PuntosWidget(_MapaBase):
    slug = 'mapa_2_puntos'
    nombre = 'Mapa de dos puntos'
    esperados = 2

    def _claves_color(self):
        return ('color1', 'color2')

    def _claves_letra(self):
        return ('label1', 'label2')

    def validar_config(self, config):
        errores = super().validar_config(config)
        for clave in ('paso1', 'paso2'):
            if not (isinstance(config.get(clave), str) and config[clave].strip()):
                errores.append(f'{clave} es obligatorio: nombre del paso del que se toma la ubicación.')
        return errores

    def titulo(self, config):
        return config.get('label') or config.get('titulo') or self.nombre

    def faltantes(self, config, ctx):
        faltan = [config.get(c) for c in ('paso1', 'paso2')
                  if mapas.coordenada_de_paso(ctx.registro, config.get(c))[0] is None]
        if not faltan:
            return ''
        return 'Falta la ubicación de: ' + ', '.join(f'«{p}»' for p in faltan) + '.'
