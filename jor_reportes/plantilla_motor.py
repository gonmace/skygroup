"""Motor de plantillas Excel con variables `{{ espacio.nombre }}` para el reporte de personal.

Reglas (ver `variables.CATALOGO` para las variables):
· Una celda con una sola variable recibe el valor nativo (número, fecha…); con texto alrededor, texto.
· Una FILA que usa `persona.*` (hoja general), `dia.*` (hoja por persona) o `proyecto.*` se repite una vez por elemento.
  Una fila no mezcla dos de esos espacios. Las fórmulas de la fila se trasladan y las que sumaban la fila plantilla
  pasan a sumar todas las filas nuevas.
· Una HOJA cuyo título contiene `{{ persona.… }}` se copia una vez por persona.
· Las hojas cuyo nombre empieza con `_` son notas/ayuda y no salen en el resultado.
· Los datos siempre se escriben como texto o número: nunca como fórmula. No se admiten variables dentro de fórmulas."""
import re
from datetime import date, datetime, time
from decimal import Decimal

from . import variables
from .excel import _nombre_hoja
from .xlsx_util import ajustar_formulas, extender_formato_condicional, redimensionar, texto, trasladar_formula

_VAR = re.compile(r'\{\{\s*([A-Za-z_]\w*(?:\.\w+)*)\s*\}\}')
_ESPACIOS_FILA = ('persona', 'dia', 'proyecto', *variables.ESPACIOS_ALIMENTACION)


def _nombres(valor):
    return [m.group(1) for m in _VAR.finditer(valor)] if isinstance(valor, str) else []


def _es_hoja_por_persona(ws):
    return any(n.split('.')[0] == 'persona' for n in _nombres(ws.title))


def _ignorada(ws):
    return ws.title.startswith('_')


def tiene_variables(wb):
    return any('{{' in ws.title or any(isinstance(c.value, str) and '{{' in c.value for fila in ws.iter_rows() for c in fila)
               for ws in wb.worksheets if not _ignorada(ws))


def _tipo_fila(ws, fila, por_persona):
    """Espacios repetidos que usa una fila (en una hoja por persona, `persona.*` es un dato fijo y no repite)."""
    usados = set()
    for celda in ws[fila]:
        for n in _nombres(celda.value):
            espacio = n.split('.')[0]
            if espacio in _ESPACIOS_FILA and not (por_persona and espacio == 'persona'):
                usados.add(espacio)
    return usados


def validar(wb):
    """Lista de problemas de la plantilla en español, con hoja y celda. Vacía = válida."""
    errores, validos = [], variables.nombres_validos()
    for ws in wb.worksheets:
        if _ignorada(ws):
            continue
        por_persona = _es_hoja_por_persona(ws)
        for n in _nombres(ws.title):
            if n not in validos or n.split('.')[0] != 'persona':
                errores.append(f'Hoja «{ws.title}»: el título solo admite variables de persona (no {{{{ {n} }}}}).')
        for fila in ws.iter_rows():
            for c in fila:
                if not (isinstance(c.value, str) and '{{' in c.value):
                    continue
                if c.value.startswith('='):
                    errores.append(f'Hoja «{ws.title}», celda {c.coordinate}: no se admiten variables dentro de una fórmula.')
                    continue
                for n in _nombres(c.value):
                    if n not in validos:
                        errores.append(f'Hoja «{ws.title}», celda {c.coordinate}: variable desconocida {{{{ {n} }}}}.')
                    elif n.split('.')[0] in variables.ESPACIOS_ALIMENTACION and por_persona:
                        errores.append(f'Hoja «{ws.title}», celda {c.coordinate}: {{{{ {n} }}}} solo se usa en la hoja general, '
                                       f'no en una hoja por persona.')
                    elif n.startswith('dia.') and not por_persona:
                        errores.append(f'Hoja «{ws.title}», celda {c.coordinate}: {{{{ {n} }}}} solo se usa en una hoja por persona '
                                       f'(cuyo título contenga {{{{ persona.nombre }}}}).')
        for r in range(1, ws.max_row + 1):
            tipos = _tipo_fila(ws, r, por_persona)
            if len(tipos) > 1:
                errores.append(f'Hoja «{ws.title}», fila {r}: mezcla variables de {" y ".join(sorted(tipos))}; '
                               f'una fila repite un solo tipo.')
    return errores


# ── Render ───────────────────────────────────────────────────────────────────────────────────────
def _valor(scope, nombre):
    actual = scope
    for parte in nombre.split('.'):
        if isinstance(actual, dict) and parte in actual:
            actual = actual[parte]
        else:
            return None
    return actual


def _a_texto(v):
    if v is None:
        return ''
    if isinstance(v, datetime):
        return f'{v:%d/%m/%Y %H:%M}'
    if isinstance(v, date):
        return f'{v:%d/%m/%Y}'
    if isinstance(v, time):
        return f'{v:%H:%M}'
    if isinstance(v, (float, Decimal)):
        return f'{v:.2f}'.rstrip('0').rstrip('.')
    return str(v)


def _poner(celda, valor):
    """Valor nativo para una celda que es solo una variable. Los textos nunca se interpretan como fórmula."""
    if valor is None or valor == '':
        celda.value = None
    elif isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal, date, datetime, time)):
        texto(celda.parent, celda.row, celda.column, valor)
    else:
        sin_formato = celda.number_format == 'General'        # openpyxl pone su formato ISO al asignar una fecha
        celda.value = float(valor) if isinstance(valor, Decimal) else valor
        if sin_formato and isinstance(valor, (date, datetime)):
            celda.number_format = 'dd-mm-yyyy hh:mm' if isinstance(valor, datetime) else 'dd-mm-yyyy'
        elif sin_formato and isinstance(valor, time):
            celda.number_format = 'hh:mm'


def _renderizar_celda(celda, scope):
    v = celda.value
    if not (isinstance(v, str) and '{{' in v) or v.startswith('='):
        return
    solo = _VAR.fullmatch(v.strip())
    if solo:
        _poner(celda, _valor(scope, solo.group(1)))
    else:
        texto(celda.parent, celda.row, celda.column, _VAR.sub(lambda m: _a_texto(_valor(scope, m.group(1))), v))


def _renderizar_escalares(ws, scope):
    for fila in ws.iter_rows():
        for celda in fila:
            _renderizar_celda(celda, scope)


def _expandir_filas(wb, ws, scope, por_persona):
    """Repite las filas plantilla (de abajo hacia arriba, para no mover las que faltan por procesar)."""
    filas = [(r, t) for r in range(ws.max_row, 0, -1) if (t := _tipo_fila(ws, r, por_persona))]
    for r, tipos in filas:
        espacio = next(iter(tipos))
        if espacio == 'persona':
            elementos = scope['personas']
        elif espacio in variables.ESPACIOS_ALIMENTACION:
            elementos = scope[espacio]
        elif espacio == 'dia':
            elementos = scope['persona']['dias']
        else:
            elementos = scope['persona']['proyectos'] if por_persona else scope['proyectos']
        n = max(len(elementos), 1)                         # sin elementos queda una fila vacía (sus sumas no se rompen)
        max_col = ws.max_column
        if n > 1:
            redimensionar(ws, r, 1, n, max_col)
            ajustar_formulas(wb, ws, r, n - 1)
            extender_formato_condicional(ws, r, n - 1)
        modelo = [(c, c.value) for c in ws[r]]             # tras ajustar: valores de la fila plantilla ya corregidos
        for i in range(n):
            fila = r + i
            elemento = elementos[i] if i < len(elementos) else {}
            local = {**scope, espacio: elemento}
            for celda, original in modelo:
                destino = ws.cell(row=fila, column=celda.column)
                if isinstance(original, str) and original.startswith('='):
                    destino.value = trasladar_formula(original, celda.coordinate, destino.coordinate) if i else original
                else:
                    destino.value = original
                    _renderizar_celda(destino, local)


def renderizar(wb, ctx):
    """Rellena el libro con el contexto de `variables.contexto`. Modifica `wb`."""
    base = {k: v for k, v in ctx.items()}
    for ws in list(wb.worksheets):
        if _ignorada(ws):
            wb.remove(ws)
        elif _es_hoja_por_persona(ws):
            usados = {s.title.lower() for s in wb.worksheets}
            for k, persona in enumerate(ctx['personas'], start=1):
                copia = wb.copy_worksheet(ws)
                wb.move_sheet(copia, offset=wb.index(ws) + k - wb.index(copia))      # las hojas de persona van donde estaba la plantilla
                scope = {**base, 'persona': persona}
                titulo = _VAR.sub(lambda m: _a_texto(_valor(scope, m.group(1))), ws.title)
                copia.title = _nombre_hoja(titulo or f'Persona {persona["item"]}', usados)
                _expandir_filas(wb, copia, scope, por_persona=True)
                _renderizar_escalares(copia, scope)
            wb.remove(ws)
        else:
            _expandir_filas(wb, ws, base, por_persona=False)
            _renderizar_escalares(ws, base)
    return wb
