"""Utilidades de openpyxl compartidas por el generador clásico (`certificado`) y el motor de plantillas con variables."""
import re
from copy import copy

from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter


def texto(ws, row, col, value):
    """Escribe texto libre como texto, nunca como fórmula (un nombre o nota que empiece con = + - @ se ejecutaría)."""
    cell = ws.cell(row=row, column=col)
    cell.value = None if value in (None, '') else str(value)
    if cell.value is not None:
        cell.data_type = 's'
    return cell


def copiar_estilo(ws, src, dst, max_col):
    for c in range(1, max_col + 1):
        ws.cell(row=dst, column=c)._style = copy(ws.cell(row=src, column=c)._style)
    h = ws.row_dimensions[src].height
    if h is not None:
        ws.row_dimensions[dst].height = h


def redimensionar(ws, first_row, old, new, max_col):
    """Inserta/elimina filas para que el bloque que empieza en first_row pase de `old` a `new` filas
    (openpyxl no desplaza combinaciones ni alturas al insertar/eliminar: se reubican a mano)."""
    n = new - old
    if n == 0:
        return
    limite = first_row + old
    movidas = []
    for m in list(ws.merged_cells.ranges):
        c1, r1, c2, r2 = m.bounds
        if r1 >= limite:
            movidas.append((c1, r1, c2, r2))
            ws.unmerge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
    if n > 0:
        ws.insert_rows(limite, n)
        for r in range(limite, limite + n):
            copiar_estilo(ws, first_row, r, max_col)
    else:
        ws.delete_rows(first_row + new, -n)
        for r in range(first_row + new, limite):
            if r in ws.row_dimensions:
                ws.row_dimensions[r].height = None
    for c1, r1, c2, r2 in movidas:
        ws.merge_cells(start_row=r1 + n, start_column=c1, end_row=r2 + n, end_column=c2)
    alturas = sorted(((r, d.height) for r, d in ws.row_dimensions.items() if r >= limite and d.height is not None),
                     reverse=(n > 0))
    for r, h in alturas:
        ws.row_dimensions[r].height = None
        ws.row_dimensions[r + n].height = h


# ── Fórmulas ─────────────────────────────────────────────────────────────────────────────────────
def trasladar_formula(formula, origen, destino):
    """La fórmula de la celda `origen` (p. ej. 'F7') como si estuviera en `destino` (p. ej. 'F9')."""
    return Translator(formula, origin=origen).translate_formula(destino)


# Referencia de celda o rango, con hoja opcional: 'Hoja 1'!A1:B3 · Hoja!$A$1 · A1. No casa nombres de función (LOG10).
_REF = re.compile(
    r"(?<![A-Za-z0-9_.$'])((?:'[^']+'|[A-Za-z_][A-Za-z0-9_.]*)!)?"
    r"(\$?[A-Z]{1,3})(\$?)(\d+)(?::(\$?[A-Z]{1,3})(\$?)(\d+))?(?![A-Za-z0-9_(])")


def ajustar_formulas(wb, hoja, fila, delta):
    """Tras convertir la fila `fila` de `hoja` en `delta + 1` filas, corrige las referencias de todas las fórmulas del
    libro que apuntan a esa hoja: las filas posteriores bajan `delta`, y el extremo de un rango que termina en `fila`
    también (así `=SUM(F7:F7)` pasa a sumar todas las filas nuevas). Las fórmulas de la propia fila plantilla solo
    mueven lo que referencian por debajo de ella (lo demás es relativo a sí misma)."""
    if delta == 0:
        return

    def nueva(m, en_hoja, en_plantilla):
        prefijo = m.group(1) or ''
        destino = prefijo[:-1].strip("'") if prefijo else None
        if (destino or None) is not None and destino != hoja.title:
            return m.group(0)
        if destino is None and not en_hoja:
            return m.group(0)
        c1, a1, r1 = m.group(2), m.group(3), int(m.group(4))
        if m.group(5) is None:                                   # referencia suelta
            if r1 > fila:
                r1 += delta
            return f'{prefijo}{c1}{a1}{r1}'
        c2, a2, r2 = m.group(5), m.group(6), int(m.group(7))
        if r1 > fila:
            r1 += delta
        if r2 > fila or (r2 == fila and not en_plantilla):
            r2 += delta
        return f'{prefijo}{c1}{a1}{r1}:{c2}{a2}{r2}'

    for ws in wb.worksheets:
        for fila_celdas in ws.iter_rows():
            for celda in fila_celdas:
                v = celda.value
                if isinstance(v, str) and v.startswith('='):
                    en_hoja, en_plantilla = ws is hoja, ws is hoja and celda.row == fila
                    celda.value = _REF.sub(lambda m: nueva(m, en_hoja, en_plantilla), v)


# ── Formato condicional ──────────────────────────────────────────────────────────────────────────
def remapear_formato_condicional(ws, fila_inicio, fila_fin=None):
    """Reescribe las filas de cada rango del formato condicional (openpyxl no las mueve al insertar/eliminar filas):
    `fila_inicio(fila)` da la nueva primera fila y `fila_fin(fila)` la nueva última (por defecto, la misma función)."""
    from openpyxl.formatting.formatting import ConditionalFormattingList
    fila_fin = fila_fin or fila_inicio
    nuevo = ConditionalFormattingList()
    for cf in ws.conditional_formatting:
        rangos = ' '.join(f'{get_column_letter(r.min_col)}{fila_inicio(r.min_row)}:{get_column_letter(r.max_col)}{fila_fin(r.max_row)}'
                          for r in cf.sqref.ranges)
        for regla in cf.rules:
            nuevo.add(rangos, regla)
    ws.conditional_formatting = nuevo


def extender_formato_condicional(ws, fila, delta):
    """Tras convertir la fila `fila` en `delta + 1` filas: los rangos que la cubren crecen `delta` filas y los que
    quedan debajo bajan `delta`."""
    if delta:
        remapear_formato_condicional(ws, lambda r: r + delta if r > fila else r, lambda r: r + delta if r >= fila else r)
