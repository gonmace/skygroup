"""Tabla de filas repetibles. Las columnas se definen con el MISMO mini-lenguaje que el formulario dinámico:

    nombre | tipo | Etiqueta | opciones o placeholder | * (obligatoria) | ayuda

Tipos de columna: text, number, date, time, select (no toggle ni textarea: no caben en una celda).
Config: `columnas` (obligatoria), `min_filas` (filas que hacen falta para dar el widget por completo, 1 por defecto),
`max_filas` (100 por defecto) y `label`. Datos: `{'filas': [{columna: valor}, …]}`.

Los campos del POST son listas paralelas (`<slug>__<columna>` repetido, una vez por fila), así que el formulario
funciona sin JavaScript; el botón «Agregar fila» (static/js/reg-tabla.js) solo clona la última fila."""
import datetime

from . import registrar
from .base import WidgetBase, texto_numero
from .form_dinamico import errores_dsl, parsear_campos

TIPOS_CELDA = ('text', 'number', 'date', 'time', 'select')
MAX_FILAS = 100
FILAS_EN_BLANCO = 2   # filas vacías que se ofrecen al editar (además de las guardadas)


def _lista(post, nombre):
    """Valores repetidos de un campo (QueryDict.getlist, o una lista/valor suelto si el POST es un dict)."""
    if hasattr(post, 'getlist'):
        return post.getlist(nombre)
    valor = post.get(nombre, [])
    return list(valor) if isinstance(valor, (list, tuple)) else [valor]


def _columnas(config):
    return parsear_campos(config.get('columnas', ''))


def _convertir(col, valor):
    """(valor, error) de una celda ya recortada y no vacía."""
    tipo = col['tipo']
    if tipo == 'number':
        try:
            return float(valor.replace(',', '.')), None
        except ValueError:
            return None, 'debe ser un número'
    if tipo == 'date':
        try:
            return datetime.date.fromisoformat(valor).isoformat(), None
        except ValueError:
            return None, 'fecha inválida'
    if tipo == 'time':
        try:
            return datetime.time.fromisoformat(valor).strftime('%H:%M'), None
        except ValueError:
            return None, 'hora inválida'
    if tipo == 'select':
        return (valor, None) if valor in col['opciones'] else (None, 'opción inválida')
    return valor[:500], None


@registrar
class TablaWidget(WidgetBase):
    slug = 'tabla_widget'
    nombre = 'Tabla'
    plantilla = 'reg_actividades/widgets/tabla.html'
    icono = 'list'

    def validar_config(self, config):
        errores = errores_dsl(config.get('columnas', ''))
        columnas = parsear_campos(config.get('columnas', ''))
        if not errores and not columnas:
            errores.append('Define al menos una columna en «columnas».')
        for c in columnas:
            if c['tipo'] not in TIPOS_CELDA:
                errores.append(f"La columna «{c['nombre']}» es de tipo {c['tipo']}: una tabla admite {', '.join(TIPOS_CELDA)}.")
        for clave in ('min_filas', 'max_filas'):
            if clave in config and not (isinstance(config[clave], int) and config[clave] >= 0):
                errores.append(f'{clave} debe ser un entero mayor o igual a 0.')
        return errores

    def leer(self, post, files, config, ctx=None):
        columnas = _columnas(config)
        etiqueta = config.get('label', self.nombre)
        listas = {c['nombre']: _lista(post, self.nombre_campo(c['nombre'])) for c in columnas}
        n = max((len(v) for v in listas.values()), default=0)
        filas, errores = [], []
        for i in range(n):
            crudo = {c['nombre']: (listas[c['nombre']][i] if i < len(listas[c['nombre']]) else '').strip() for c in columnas}
            if not any(crudo.values()):
                continue   # fila en blanco: se descarta
            fila, n_fila = {}, len(filas) + 1
            for c in columnas:
                valor = crudo[c['nombre']]
                if not valor:
                    if c['obligatorio']:
                        errores.append(f"{etiqueta}, fila {n_fila}: «{c['label']}» es obligatorio.")
                    continue
                convertido, error = _convertir(c, valor)
                if error:
                    errores.append(f"{etiqueta}, fila {n_fila}, «{c['label']}»: {error}.")
                else:
                    fila[c['nombre']] = convertido
            filas.append(fila)
        tope = config.get('max_filas', MAX_FILAS)
        if len(filas) > tope:
            errores.append(f'{etiqueta}: máximo {tope} filas.')
        return {'filas': filas}, errores

    def nivel(self, datos, config, ctx):
        if not _columnas(config):
            return 0
        n = len((datos or {}).get('filas') or [])
        if n == 0:
            return 1
        return 3 if n >= max(config.get('min_filas', 1), 1) else 2

    def html_pdf(self, pw, datos, ctx, archivo):
        from html import escape
        filas = (datos or {}).get('filas') or []
        if not filas:
            return ''
        columnas = _columnas(pw.config)
        cab = ''.join(f'<th>{escape(c["label"])}</th>' for c in columnas)
        cuerpo = ''.join('<tr>' + ''.join(
            f'<td>{escape(texto_numero(f.get(c["nombre"])) if c["tipo"] == "number" else str(f.get(c["nombre"], "")))}</td>'
            for c in columnas) + '</tr>' for f in filas)
        return f'<h3>{escape(pw.config.get("label") or self.nombre)}</h3><table width="100%"><tr>{cab}</tr>{cuerpo}</table>'

    def contexto(self, datos, config, ctx):
        columnas = _columnas(config)
        guardadas = (datos or {}).get('filas') or []
        def celda(c, valor=''):
            return {**c, 'campo': self.nombre_campo(c['nombre']), 'valor': valor}

        filas = [[celda(c, texto_numero(f.get(c['nombre'])) if c['tipo'] == 'number' else f.get(c['nombre'], ''))
                  for c in columnas] for f in guardadas]
        en_blanco = [[celda(c) for c in columnas] for _ in range(FILAS_EN_BLANCO if ctx.puede_escribir else 0)]
        return {'columnas': columnas, 'filas': filas, 'filas_en_blanco': en_blanco,
                'etiqueta': config.get('label', self.nombre), 'max_filas': config.get('max_filas', MAX_FILAS)}
