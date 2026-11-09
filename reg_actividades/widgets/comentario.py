from . import registrar
from .base import WidgetBase


@registrar
class ComentarioWidget(WidgetBase):
    slug = 'comentario_widget'
    nombre = 'Comentario'
    plantilla = 'reg_actividades/widgets/comentario.html'
    CAMPO = 'comentario'

    def validar_config(self, config):
        errores = []
        if 'max_length' in config and not (isinstance(config['max_length'], int) and config['max_length'] > 0):
            errores.append('max_length debe ser un entero positivo.')
        return errores

    def leer(self, post, files, config, ctx=None):
        texto = (post.get(self.nombre_campo(self.CAMPO)) or '').strip()
        limite = config.get('max_length')
        if limite and len(texto) > limite:
            return {self.CAMPO: texto}, [f'{config.get("label", "Comentario")}: máximo {limite} caracteres.']
        return {self.CAMPO: texto}, []

    def nivel(self, datos, config, ctx):
        return 3 if (datos or {}).get(self.CAMPO, '').strip() else 1

    def contexto(self, datos, config, ctx):
        return {'campo': self.nombre_campo(self.CAMPO), 'valor': (datos or {}).get(self.CAMPO, ''),
                'etiqueta': config.get('label', self.nombre), 'max_length': config.get('max_length')}
