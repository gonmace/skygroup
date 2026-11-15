from . import registrar
from .base import WidgetBase


@registrar
class ListaWidget(WidgetBase):
    slug = 'lista_widget'
    nombre = 'Lista'
    plantilla = 'reg_actividades/widgets/lista.html'
    CAMPO = 'entradas'
    IMPORTADO = 'importado'

    def validar_config(self, config):
        errores = []
        if 'max_items' in config and not (isinstance(config['max_items'], int) and config['max_items'] > 0):
            errores.append('max_items debe ser un entero positivo.')
        if 'min_items' in config and not (isinstance(config['min_items'], int) and config['min_items'] >= 0):
            errores.append('min_items debe ser un entero mayor o igual a 0.')
        if isinstance(config.get('min_items'), int) and isinstance(config.get('max_items'), int) \
                and config['min_items'] > config['max_items']:
            errores.append('min_items no puede superar a max_items.')
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
        # Lista importada de la visita anterior: sigue «parcial» mientras no se cambie su contenido.
        previos = ((getattr(ctx, 'extra', None) or {}).get('previos')) or {}
        if previos.get(self.IMPORTADO) and items == previos.get(self.CAMPO):
            return {self.CAMPO: items, self.IMPORTADO: True}, []
        return {self.CAMPO: items}, []

    def nivel(self, datos, config, ctx):
        # Con `min_items`, menos elementos que el mínimo deja el elemento a medias (amarillo).
        n = len((datos or {}).get(self.CAMPO) or [])
        if n and (datos or {}).get(self.IMPORTADO):
            return 2
        return 1 if n == 0 else (2 if n < config.get('min_items', 1) else 3)

    def contexto(self, datos, config, ctx):
        items = (datos or {}).get(self.CAMPO) or []
        minimo = config.get('min_items', 0)
        return {'minimo': minimo, 'filas_vacias': [''] * max(0 if items else 1, minimo - len(items)),
                'campo': self.nombre_campo(self.CAMPO), 'texto': '\n'.join(items), 'items': items,
                'etiqueta': config.get('label', self.nombre), 'numerada': config.get('numerada', True),
                'placeholder': config.get('placeholder', ''), 'max_items': config.get('max_items', 200)}
