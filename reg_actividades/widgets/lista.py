from . import registrar
from .base import WidgetBase


@registrar
class ListaWidget(WidgetBase):
    slug = 'lista_widget'
    nombre = 'Lista'
    plantilla = 'reg_actividades/widgets/lista.html'
    CAMPO = 'entradas'

    def validar_config(self, config):
        errores = []
        if 'max_items' in config and not (isinstance(config['max_items'], int) and config['max_items'] > 0):
            errores.append('max_items debe ser un entero positivo.')
        if 'numerada' in config and not isinstance(config['numerada'], bool):
            errores.append('numerada debe ser verdadero o falso.')
        return errores

    def leer(self, post, files, config, ctx=None):
        # Un elemento por línea; las líneas vacías se descartan.
        campo = self.nombre_campo(self.CAMPO)
        crudos = post.getlist(campo) if hasattr(post, 'getlist') else [post.get(campo) or '']
        items = [l.strip() for c in crudos for l in (c or '').splitlines() if l.strip()]
        tope = config.get('max_items', 200)
        if len(items) > tope:
            return {self.CAMPO: items}, [f'{config.get("label", "Lista")}: máximo {tope} elementos.']
        if any(len(i) > 1000 for i in items):
            return {self.CAMPO: items}, [f'{config.get("label", "Lista")}: un elemento supera los 1000 caracteres.']
        return {self.CAMPO: items}, []

    def nivel(self, datos, config, ctx):
        return 3 if (datos or {}).get(self.CAMPO) else 1

    def contexto(self, datos, config, ctx):
        items = (datos or {}).get(self.CAMPO) or []
        return {'campo': self.nombre_campo(self.CAMPO), 'texto': '\n'.join(items), 'items': items,
                'etiqueta': config.get('label', self.nombre), 'numerada': config.get('numerada', True),
                'placeholder': config.get('placeholder', ''), 'max_items': config.get('max_items', 200)}
