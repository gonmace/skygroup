"""Exportaciones a Excel. Todo texto que viene de personas (nombres, notas) pasa por `seguro` para que Excel
no lo interprete como fórmula (=, +, -, @)."""
import re
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROJO = 'B91C1C'
_PELIGRO = ('=', '+', '-', '@', '\t', '\r')
_HEX = re.compile(r'^#?([0-9a-fA-F]{6})$')
_BORDE = Border(*(Side(style='thin', color='E5E7EB') for _ in range(4)))


def seguro(valor):
    if isinstance(valor, str) and valor.startswith(_PELIGRO):
        return "'" + valor
    return valor


def _nombre_hoja(nombre, usados):
    base = re.sub(r'[\\/*?:\[\]]', '', nombre).strip()[:28] or 'Hoja'
    n, final = 1, base
    while final.lower() in usados:
        n += 1
        final = f'{base[:28]}{n}'[:31]
    usados.add(final.lower())
    return final


def _encabezado(ws, fila, titulos, anchos=None):
    for c, t in enumerate(titulos, 1):
        celda = ws.cell(row=fila, column=c, value=seguro(t))
        celda.font, celda.fill = Font(bold=True, color='FFFFFF'), PatternFill('solid', fgColor=ROJO)
        celda.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        celda.border = _BORDE
    for c, a in enumerate(anchos or [], 1):
        ws.column_dimensions[get_column_letter(c)].width = a


def _bytes(wb):
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def asistencia_xlsx(personas, periodo, empresa):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Resumen'
    usados = {'resumen'}
    ws['A1'] = seguro(f'Asistencia · {empresa.nombre} · {periodo.etiqueta}')
    ws['A1'].font = Font(bold=True, size=14)
    _encabezado(ws, 3, ['Persona', 'Cargo', 'Días trabajados', 'Horas netas', 'Atrasos (min)', 'Ausencias (días)', 'Sin cerrar'],
                [30, 24, 16, 14, 14, 16, 12])
    for i, p in enumerate(personas, 4):
        for c, v in enumerate([p['nombre'], p['cargo'], p['dias'], p['horas'], p['atraso_min'], p['ausencias'], p['no_cerro']], 1):
            ws.cell(row=i, column=c, value=seguro(v)).border = _BORDE
    for p in personas:
        hoja = wb.create_sheet(_nombre_hoja(p['nombre'], usados))
        hoja['A1'], hoja['A2'] = seguro(p['nombre']), seguro(p['cargo'])
        hoja['A1'].font = Font(bold=True, size=13)
        _encabezado(hoja, 4, ['Fecha', 'Día', 'Ingreso', 'Salida', 'Horas netas', 'Atraso (min)', 'Comentario'],
                    [13, 12, 10, 10, 12, 12, 48])
        for i, f in enumerate(p['filas'], 5):
            comentario = '; '.join(f['comentarios']) + (' · jornada sin cerrar' if f['no_cerro'] else '')
            valores = [f['fecha'].strftime('%d-%m-%Y'), f['dia'], f['ingreso'], f['salida'], f['horas'],
                       f['atraso_min'] if f['atraso_min'] is not None else '', comentario]
            for c, v in enumerate(valores, 1):
                celda = hoja.cell(row=i, column=c, value=seguro(v))
                celda.border = _BORDE
                if f['fin_semana']:
                    celda.fill = PatternFill('solid', fgColor='FEE2E2')
        fin = 5 + len(p['filas'])
        hoja.cell(row=fin, column=1, value='Total').font = Font(bold=True)
        hoja.cell(row=fin, column=5, value=p['horas']).font = Font(bold=True)
        hoja.cell(row=fin, column=6, value=p['atraso_min']).font = Font(bold=True)
        hoja.freeze_panes = 'A5'
    return _bytes(wb)


def estadisticas_xlsx(datos, empresa):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Categorías'
    ws['A1'] = seguro(f'Estadísticas · {empresa.nombre} · {datos["periodo"].etiqueta}')
    ws['A1'].font = Font(bold=True, size=14)
    ws['A2'] = f'{datos["total"]} actividades en {datos["reportes"]} reportes'
    _encabezado(ws, 4, ['Categoría', 'Actividades', '%'], [40, 14, 10])
    for i, c in enumerate(datos['categorias'], 5):
        m = _HEX.match(c['color'] or '')
        a = ws.cell(row=i, column=1, value=seguro(c['etiqueta']))
        if m:
            a.fill = PatternFill('solid', fgColor=m.group(1).upper())
        ws.cell(row=i, column=2, value=c['n'])
        ws.cell(row=i, column=3, value=c['pct'])
    pers = wb.create_sheet('Por persona')
    _encabezado(pers, 1, ['Persona', 'Cargo', 'Reportes', 'Total', 'Último reporte'] +
                [datos['etiquetas_categoria'].get(c, c) for c in datos['codigos']], [28, 20, 10, 10, 14] + [14] * len(datos['codigos']))
    for i, p in enumerate(datos['personas'], 2):
        for c, v in enumerate([p['nombre'], p['rol'], p['reportes'], p['total'], p['ultimo'].strftime('%d/%m/%Y')] + p['por_cat'], 1):
            pers.cell(row=i, column=c, value=seguro(v))
    for titulo, clave in (('Proyectos', 'proyectos'), ('Sedes', 'ubicaciones'), ('Entregables', 'entregables')):
        h = wb.create_sheet(titulo)
        _encabezado(h, 1, ['Nombre', 'Actividades'], [48, 14])
        for i, e in enumerate(datos[clave], 2):
            h.cell(row=i, column=1, value=seguro(e['nombre']))
            h.cell(row=i, column=2, value=e['n'])
    hp = wb.create_sheet('Horas por proyecto')
    _encabezado(hp, 1, ['Proyecto', 'Jornadas', 'Horas'], [40, 12, 12])
    for i, r in enumerate(datos['horas_proyecto'], 2):
        hp.cell(row=i, column=1, value=seguro(r['nombre']))
        hp.cell(row=i, column=2, value=r['jornadas'])
        hp.cell(row=i, column=3, value=r['horas'])
    return _bytes(wb)
