"""Plantilla base del reporte de personal: un libro con todas las variables ya puestas.

Es el punto de partida: se descarga, se adapta (mover columnas, quitar bloques, cambiar el diseño) y se vuelve a subir.
Sin plantilla subida, el reporte se genera con esta misma."""
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as col

from . import variables

# Plantilla modelo: el certificado de pago original de skylog con variables (ver el comando `generar_plantilla_modelo`).
RUTA_MODELO = Path(__file__).resolve().parent / 'plantillas' / 'modelo_certificado.xlsx'

AZUL = '1F3A5F'
GRIS = 'F2F4F7'
BORDE = Border(bottom=Side(style='thin', color='D0D5DD'))
DIAS = variables.MAX_DIAS


def _cabecera(ws, fila, titulos, desde=1):
    for i, t in enumerate(titulos):
        c = ws.cell(row=fila, column=desde + i, value=t)
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor=AZUL)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    ws.row_dimensions[fila].height = 30


def _fila(ws, fila, valores, formatos=None, desde=1):
    for i, v in enumerate(valores):
        c = ws.cell(row=fila, column=desde + i, value=v)
        c.border = BORDE
        if formatos and formatos.get(i):
            c.number_format = formatos[i]


def _titulo(ws, filas):
    ws['A1'] = '{{ reporte.nombre }}'
    ws['A1'].font = Font(bold=True, size=16, color=AZUL)
    for r, (etiqueta, valor) in enumerate(filas, start=2):
        ws.cell(row=r, column=1, value=etiqueta).font = Font(bold=True, color='475467')
        ws.cell(row=r, column=2, value=valor)


def _total(ws, fila, etiqueta, columnas, primera, ultima=None, enteras=()):
    c = ws.cell(row=fila, column=1, value=etiqueta)
    c.font = Font(bold=True)
    for cc in range(1, max(columnas, default=1) + 1):
        ws.cell(row=fila, column=cc).fill = PatternFill('solid', fgColor=GRIS)
    for letra_col in columnas:
        c = ws.cell(row=fila, column=letra_col, value=f'=SUM({col(letra_col)}{primera}:{col(letra_col)}{ultima or primera})')
        c.font = Font(bold=True)
        c.number_format = 'General' if letra_col in enteras else '0.00'


def _resumen(wb):
    ws = wb.active
    ws.title = 'Resumen'
    _titulo(ws, [('Empresa:', '{{ empresa.nombre }}'), ('Período:', '{{ periodo.etiqueta }}'),
                 ('Generado:', '{{ generado.fecha }}')])
    cabecera = ['N.º', 'Persona', 'Cargo', 'Días trabajados', 'Horas netas', 'Atraso (min)', 'Ausencias', 'Sin cerrar']
    _cabecera(ws, 6, cabecera + [f'{{{{ periodo.dia.{n} }}}}' for n in range(1, DIAS + 1)])
    base = ['{{ persona.item }}', '{{ persona.nombre }}', '{{ persona.cargo_completo }}', '{{ persona.dias_trabajados }}',
            '{{ persona.horas_netas }}', '{{ persona.atraso_min }}', '{{ persona.ausencias }}', '{{ persona.sin_cerrar }}']
    dias = [f'{{{{ persona.horas.{n} }}}}' for n in range(1, DIAS + 1)]
    _fila(ws, 7, base + dias, {4: '0.00', **{8 + i: '0.0' for i in range(DIAS)}})
    _total(ws, 8, 'Total', [4, 5, 6, 7, 8] + list(range(9, 9 + DIAS)), 7, enteras=(4, 6, 7, 8))
    ws.column_dimensions['A'].width = 6
    ws.column_dimensions['B'].width = 30
    ws.column_dimensions['C'].width = 26
    for c in range(4, 9):
        ws.column_dimensions[col(c)].width = 13
    for c in range(9, 9 + DIAS):
        ws.column_dimensions[col(c)].width = 5
    ws.freeze_panes = 'C7'


def _hoja_persona(wb):
    ws = wb.create_sheet('{{ persona.nombre }}')
    _titulo(ws, [('Persona:', '{{ persona.nombre }}'), ('Cargo:', '{{ persona.cargo_completo }}'),
                 ('Período:', '{{ periodo.etiqueta }}')])
    _cabecera(ws, 6, ['Fecha', 'Día', 'Ingreso', 'Salida', 'Horas netas', 'Atraso (min)', 'Observaciones'])
    _fila(ws, 7, ['{{ dia.fecha }}', '{{ dia.dia_semana }}', '{{ dia.ingreso }}', '{{ dia.salida }}', '{{ dia.horas_netas }}',
                  '{{ dia.atraso_min }}', '{{ dia.observaciones }}'], {0: 'dd-mm-yyyy', 4: '0.00'})
    _total(ws, 8, 'Total', [5, 6], 7, enteras=(6,))
    ws.cell(row=10, column=1, value='Horas por proyecto').font = Font(bold=True, size=12, color=AZUL)
    _cabecera(ws, 11, ['Proyecto', 'Código', 'Jornadas', 'Horas'])
    _fila(ws, 12, ['{{ proyecto.nombre }}', '{{ proyecto.codigo }}', '{{ proyecto.jornadas }}', '{{ proyecto.horas }}'],
          {3: '0.00'})
    _total(ws, 13, 'Total', [3, 4], 12, enteras=(3,))
    for letra, ancho in zip('ABCDEFG', (30, 14, 12, 12, 13, 13, 60)):
        ws.column_dimensions[letra].width = ancho
    ws.freeze_panes = 'A7'


def _hoja_proyectos(wb):
    ws = wb.create_sheet('Proyectos')
    _titulo(ws, [('Período:', '{{ periodo.etiqueta }}')])
    _cabecera(ws, 6, ['Proyecto', 'Código', 'Jornadas', 'Horas'])
    _fila(ws, 7, ['{{ proyecto.nombre }}', '{{ proyecto.codigo }}', '{{ proyecto.jornadas }}', '{{ proyecto.horas }}'],
          {3: '0.00'})
    _total(ws, 8, 'Total', [3, 4], 7, enteras=(3,))
    for letra, ancho in zip('ABCD', (44, 22, 12, 12)):
        ws.column_dimensions[letra].width = ancho


def _hoja_variables(wb):
    ws = wb.create_sheet('_Variables')
    ws['A1'] = 'Variables disponibles (esta hoja no sale en el reporte: su nombre empieza con «_»)'
    ws['A1'].font = Font(bold=True, size=13, color=AZUL)
    notas = [
        'Escribe la variable tal cual, con llaves dobles: {{ persona.nombre }}.',
        'Una fila con variables de persona, día o proyecto se repite una vez por cada elemento. Una fila no mezcla tipos.',
        'Una hoja cuyo nombre contiene {{ persona.nombre }} se copia una vez por persona; en ella, «dia.*» repite por día.',
        'N va de 1 a 31: {{ persona.horas.1 }} … {{ persona.horas.31 }}. Las fórmulas (SUM, etc.) se conservan y se ajustan.',
    ]
    for i, n in enumerate(notas, start=3):
        ws.cell(row=i, column=1, value=n)
    fila = 3 + len(notas) + 1
    _cabecera(ws, fila, ['Variable', 'Descripción', 'Ejemplo'])
    for grupo, items in variables.catalogo_agrupado():
        fila += 1
        ws.cell(row=fila, column=1, value=grupo).font = Font(bold=True, color=AZUL)
        for nombre, descripcion, ejemplo in items:
            fila += 1
            # Se escriben como texto: si no, el motor las tomaría por variables reales de esta hoja.
            ws.cell(row=fila, column=1, value='{{ ' + nombre + ' }}')
            ws.cell(row=fila, column=2, value=descripcion)
            ws.cell(row=fila, column=3, value=ejemplo)
    ws.column_dimensions['A'].width = 36
    ws.column_dimensions['B'].width = 80
    ws.column_dimensions['C'].width = 24


def construir():
    """Libro nuevo con la plantilla base (openpyxl.Workbook)."""
    wb = openpyxl.Workbook()
    _resumen(wb)
    _hoja_persona(wb)
    _hoja_proyectos(wb)
    _hoja_variables(wb)
    return wb


def bytes_plantilla():
    import io
    buf = io.BytesIO()
    construir().save(buf)
    return buf.getvalue()


def bytes_modelo():
    return RUTA_MODELO.read_bytes()
