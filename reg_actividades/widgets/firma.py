"""Firma manuscrita en pantalla (canvas). Se guarda como PNG en base64 dentro de los datos del paso
(`{'png': 'data:image/png;base64,…', 'nombre': '…'}`): pesa unos KB y viaja con las copias de revisión."""
import base64
import binascii

from . import registrar
from .base import WidgetBase

PREFIJO = 'data:image/png;base64,'
MAX_BYTES = 300_000
CAB_PNG = b'\x89PNG\r\n\x1a\n'


@registrar
class FirmaWidget(WidgetBase):
    slug = 'firma_widget'
    nombre = 'Firma'
    plantilla = 'reg_actividades/widgets/firma.html'
    icono = 'pencil'

    def leer(self, post, files, config, ctx=None):
        png = (post.get(self.nombre_campo('png')) or '').strip()
        nombre = (post.get(self.nombre_campo('nombre')) or '').strip()[:120]
        etiqueta = config.get('label', self.nombre)
        if post.get(self.nombre_campo('borrar')):
            return {'png': '', 'nombre': nombre}, []
        if not png:   # no se tocó la firma: se conserva la guardada
            previa = (getattr(ctx, 'extra', None) or {}).get('previos', {}).get('png', '')
            return {'png': previa, 'nombre': nombre}, []
        if not png.startswith(PREFIJO):
            return {'png': '', 'nombre': nombre}, [f'{etiqueta}: la firma no es una imagen PNG válida.']
        try:
            crudo = base64.b64decode(png[len(PREFIJO):], validate=True)
        except (binascii.Error, ValueError):
            return {'png': '', 'nombre': nombre}, [f'{etiqueta}: la firma está dañada.']
        if not crudo.startswith(CAB_PNG) or len(crudo) > MAX_BYTES:
            return {'png': '', 'nombre': nombre}, [f'{etiqueta}: la firma no es válida o es demasiado grande.']
        return {'png': png, 'nombre': nombre}, []

    def nivel(self, datos, config, ctx):
        return 3 if (datos or {}).get('png') else 1

    def vacio(self, datos):
        return not (datos or {}).get('png')

    def html_pdf(self, pw, datos, ctx, archivo):
        from html import escape
        png = (datos or {}).get('png', '')
        if not png.startswith(PREFIJO):
            return ''
        try:
            crudo = base64.b64decode(png[len(PREFIJO):], validate=True)
        except (binascii.Error, ValueError):
            return ''
        nombre = f'firma_{ctx.registro.pk}_{ctx.paso.pk}.png'
        archivo.add(crudo, nombre)
        quien = escape((datos or {}).get('nombre', ''))
        return (f'<h3>{escape(pw.config.get("label") or self.nombre)}</h3><p><img src="{nombre}" style="width: 160pt;"></p>'
                + (f'<p class="sub">{quien}</p>' if quien else ''))

    def contexto(self, datos, config, ctx):
        datos = datos or {}
        return {'campo_png': self.nombre_campo('png'), 'campo_nombre': self.nombre_campo('nombre'),
                'campo_borrar': self.nombre_campo('borrar'), 'png': datos.get('png', ''),
                'nombre': datos.get('nombre', ''), 'etiqueta': config.get('label', self.nombre)}
