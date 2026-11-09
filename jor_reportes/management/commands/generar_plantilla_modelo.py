"""Convierte el certificado de pago original de skylog en la plantilla modelo con variables `{{ … }}`.

    python manage.py generar_plantilla_modelo ~/Django/skylog/templates/plantilla.xlsx

Parte del .xlsx real (estilos, celdas combinadas y logo se conservan tal cual), deja UNA fila modelo por bloque
(personal, cada planilla de alimentación, hoja por persona) y pone variables en lugar de datos. Escribe
`jor_reportes/plantillas/modelo_certificado.xlsx`, que se versiona y se sirve desde Configuración."""
import re
from pathlib import Path

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from openpyxl.utils import get_column_letter as col

from jor_reportes import plantilla_base
from jor_reportes.xlsx_util import redimensionar, remapear_formato_condicional

DESTINO = plantilla_base.RUTA_MODELO
COL_DIA_1, COL_DIA_31 = 6, 36                    # F..AJ: matriz de días de PL
FILAS_PL = {'personas': (14, 12), 'LPZ': (43, 3), 'CBA': (52, 3), 'SCZ': (61, 6)}   # (primera fila, filas) en el original
_CELDA = re.compile(r'(?<![A-Za-z0-9_$!])(\$?[A-Z]{1,3}\$?)(\d+)(?![A-Za-z0-9_(])')


def _var(nombre):
    return '{{ ' + nombre + ' }}'


def _estilo_dia_31(ws, fila):
    """La columna del día 31 (AJ) viene sin estilo en el original: hereda el del día 30."""
    from copy import copy
    ws.cell(row=fila, column=COL_DIA_31)._style = copy(ws.cell(row=fila, column=COL_DIA_31 - 1)._style)


def _matriz_dias(ws, fila, nombre):
    _estilo_dia_31(ws, fila)
    for d in range(1, 32):
        ws.cell(row=fila, column=COL_DIA_1 + d - 1).value = _var(f'{nombre}.{d}')


def _remapear_formulas(ws, nueva):
    """Las filas eliminadas dejan de contar: `nueva(fila)` lleva cada referencia a su fila definitiva, y un rango
    que cubría las filas eliminadas queda sobre la fila modelo (=SUM(AM14:AM25) → =SUM(AM14:AM14)). Respeta los textos."""
    for fila in ws.iter_rows():
        for c in fila:
            if isinstance(c.value, str) and c.value.startswith('='):
                trozos = c.value.split('"')
                for i in range(0, len(trozos), 2):                 # los pares quedan fuera de las comillas
                    trozos[i] = _CELDA.sub(lambda m: f'{m.group(1)}{nueva(int(m.group(2)))}', trozos[i])
                c.value = '"'.join(trozos)


def _hoja_pl(ws):
    ws['D1'] = _var('reporte.nombre')
    ws['AM1'] = _var('generado.fecha')
    ws['E3'] = 'NOMBRE DEL CLIENTE'
    ws['E5'] = 'DESCRIPCIÓN DEL SERVICIO'
    ws['Y3'] = _var('periodo.etiqueta')
    ws['AA5'] = _var('periodo.dias_habiles')
    ws['Y7'] = _var('reporte.moneda')
    ws['AL8'] = None
    ws['W9'] = 'T/C:'
    ws['W9']._style = ws['W7']._style
    ws['Y9'] = _var('reporte.tipo_cambio')
    ws['Y9']._style = ws['Y7']._style
    ws['Y9'].number_format = '0.000000'
    ws['C77'] = _var('empresa.nombre')
    # Pasajes, viáticos y equipos: bloque manual (importes y descripciones propios de cada cliente).
    for celda in ('W32', 'W34', 'AJ32', 'AL32', 'AJ34', 'AL34'):
        ws[celda] = None

    _matriz_dias(ws, 13, 'periodo.dia')
    ws['F13'].value = _var('periodo.dia.1')

    # Planilla de personal: fila modelo 14
    for c, v in zip('ABCDE', ('persona.item', 'persona.nombre', 'persona.cargo_completo', 'periodo.desde', 'persona.haber_basico')):
        ws[f'{c}14'] = _var(v)
    _matriz_dias(ws, 14, 'persona.pagado')
    ws['AM14'] = '=+AL14/$Y$9'

    # Planillas de alimentación por ciudad: fila modelo con las personas de esa ciudad
    for ciudad, (primera, _) in FILAS_PL.items():
        if ciudad == 'personas':
            continue
        espacio = f'alimentacion_{ciudad.lower()}'
        for c, v in zip('ABCD', (f'{espacio}.item', f'{espacio}.nombre', f'{espacio}.cargo_completo', 'periodo.desde')):
            ws[f'{c}{primera}'] = _var(v)
        ws[f'E{primera}'] = 25
        _matriz_dias(ws, primera, f'{espacio}.alimentacion')
        _matriz_dias(ws, primera - 1, 'periodo.dia')           # cabecera de días de cada planilla (F42, F51, F60)

    ws['W71'] = '="Son : " & TEXT(AL69,"#,##0.00") & " " & Y7'

    # Eliminar las filas sobrantes de abajo hacia arriba (así los números de fila originales siguen valiendo)
    eliminadas = []
    for ciudad in ('SCZ', 'CBA', 'LPZ', 'personas'):
        primera, cantidad = FILAS_PL[ciudad]
        redimensionar(ws, primera, cantidad, 1, max_col=39)
        eliminadas += range(primera + 1, primera + cantidad)

    def nueva(fila):
        return fila - sum(1 for e in eliminadas if e <= fila)

    _remapear_formulas(ws, nueva)
    remapear_formato_condicional(ws, nueva)
    # El formato condicional cubría F..AI: ahora también AJ (día 31)
    from openpyxl.formatting.formatting import ConditionalFormattingList
    ampliado = ConditionalFormattingList()
    for cf in ws.conditional_formatting:
        rangos = ' '.join(str(r).replace('AI', 'AJ') for r in cf.sqref.ranges)
        for regla in cf.rules:
            ampliado.add(rangos, regla)
    ws.conditional_formatting = ampliado


def _hoja_persona(ws):
    ws.title = _var('persona.item')
    ws['B4'] = _var('persona.item')
    ws['B5'] = _var('persona.nombre')
    ws['B6'] = _var('persona.cargo_completo')
    ws['B7'] = _var('persona.haber_basico')
    ws['A10'] = _var('dia.fecha')
    ws['C10'] = _var('dia.ingreso_hora')
    ws['D10'] = _var('dia.salida_hora')
    ws['E10'] = _var('dia.refrigerio')
    ws['H10'] = _var('dia.observaciones')
    redimensionar(ws, 10, 30, 1, max_col=8)
    ws['C11'] = '=+COUNT(C10:C10)'
    ws['C12'] = '=SUM(F10:F10)'
    ws['C13'] = '=SUM(G10:G10)'


class Command(BaseCommand):
    help = 'Genera la plantilla modelo (con variables) a partir del certificado de pago original de skylog.'

    def add_arguments(self, parser):
        parser.add_argument('origen', help='Ruta del plantilla.xlsx original de skylog (hojas «PL» y «1»…«12»).')

    def handle(self, *args, origen, **opts):
        ruta = Path(origen).expanduser()
        if not ruta.is_file():
            raise CommandError(f'No existe {ruta}')
        wb = openpyxl.load_workbook(ruta)
        if 'PL' not in wb.sheetnames or '1' not in wb.sheetnames:
            raise CommandError('El libro de origen debe tener las hojas «PL» y «1».')
        for nombre in wb.sheetnames:
            if nombre.isdigit() and nombre != '1':
                del wb[nombre]
        _hoja_pl(wb['PL'])
        _hoja_persona(wb['1'])
        plantilla_base._hoja_variables(wb)
        DESTINO.parent.mkdir(exist_ok=True)
        wb.save(DESTINO)
        self.stdout.write(self.style.SUCCESS(f'Plantilla modelo escrita en {DESTINO}'))
