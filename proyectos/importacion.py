"""Importación de proyectos desde Excel: plantilla descargable + lectura validada.

Se valida todo el archivo antes de guardar: si alguna fila tiene errores no se importa nada (todo o nada).
El código identifica el registro: si ya existe uno activo con ese código se actualiza (las celdas vacías no
borran datos); sin código, o con uno nuevo, se crea."""
from decimal import Decimal, InvalidOperation
import zipfile
from io import BytesIO

from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from jor_reportes.excel import ROJO, seguro

from .models import Proyecto, ProyectoUbicacion

MAX_BYTES = 5 * 1024 * 1024
MAX_FILAS = 2000
MAX_DESCOMPRIMIDO = 50 * 1024 * 1024   # un .xlsx es un zip: se limita lo que ocupa abierto, no solo lo subido
ETIQUETA_UBICACION = 'Principal'

# (encabezado, ancho, clave interna)
COLUMNAS = [
    ('Código', 14, 'codigo'), ('Nombre', 36, 'nombre'), ('Código operador', 16, 'codigo_operador'),
    ('Tipo', 16, 'tipo'), ('Estado', 16, 'estado'), ('Región', 18, 'region'), ('Comuna', 18, 'comuna'),
    ('Ciudad', 18, 'ciudad'), ('Descripción', 40, 'descripcion'), ('Latitud', 12, 'lat'), ('Longitud', 12, 'lon'),
]
LARGOS = {'codigo': 40, 'nombre': 160, 'codigo_operador': 60, 'region': 80, 'comuna': 80, 'ciudad': 80, 'descripcion': 5000}


class ErrorArchivo(Exception):
    pass


def plantilla_xlsx(empresa):
    """Libro con la hoja «Proyectos» (solo encabezados) y la hoja «Instrucciones» con los valores admitidos."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Proyectos'
    for c, (titulo, ancho, _) in enumerate(COLUMNAS, 1):
        celda = ws.cell(row=1, column=c, value=titulo)
        celda.font, celda.fill = Font(bold=True, color='FFFFFF'), PatternFill('solid', fgColor=ROJO)
        celda.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(c)].width = ancho
    ws.freeze_panes = 'A2'

    ins = wb.create_sheet('Instrucciones')
    ins.column_dimensions['A'].width = 24
    ins.column_dimensions['B'].width = 90
    filas = [
        ('Cómo llenar', 'Una fila por registro en la hoja «Proyectos». No cambies ni muevas los encabezados.'),
        ('Nombre', 'Obligatorio.'),
        ('Código', 'Opcional. Si ya existe un registro con ese código se actualiza; si no, se crea. '
                   'En una actualización las celdas vacías no borran el dato actual.'),
        ('Tipo', 'Debe existir: ' + (', '.join(empresa.tipos_proyecto.values_list('nombre', flat=True)) or '(aún no hay tipos)')),
        ('Estado', 'Uno de: ' + ', '.join(l for _, l in Proyecto.Estado.choices) + '. Vacío = Construcción al crear.'),
        ('Latitud / Longitud', 'Decimales con punto o coma (ej. -33.4489). Se indican las dos o ninguna.'),
        ('Límites', f'Hasta {MAX_FILAS} filas y {MAX_BYTES // (1024 * 1024)} MB. Si alguna fila tiene errores no se importa nada.'),
    ]
    for i, (a, b) in enumerate(filas, 1):
        ins.cell(row=i, column=1, value=a).font = Font(bold=True)
        ins.cell(row=i, column=2, value=seguro(b)).alignment = Alignment(wrap_text=True, vertical='top')
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _texto(v):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _decimal(valor, fila, nombre, minimo, maximo, errores):
    if valor == '':
        return None
    try:
        d = Decimal(valor.replace(',', '.'))
    except InvalidOperation:
        errores.append(f'Fila {fila}: {nombre} «{valor}» no es un número.')
        return None
    if not d.is_finite() or not minimo <= d <= maximo:
        errores.append(f'Fila {fila}: {nombre} fuera de rango ({minimo} a {maximo}).')
        return None
    return d.quantize(Decimal('0.000001'))


def leer(archivo, empresa):
    """→ lista de dicts por fila con claves de COLUMNAS (+ 'fila', 'tipo_obj', 'estado', 'lat', 'lon'), y errores."""
    if archivo.size > MAX_BYTES:
        raise ErrorArchivo(f'El archivo supera {MAX_BYTES // (1024 * 1024)} MB.')
    if not archivo.name.lower().endswith('.xlsx'):
        raise ErrorArchivo('Sube un archivo Excel (.xlsx). Puedes partir de la plantilla.')
    try:
        with zipfile.ZipFile(archivo) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_DESCOMPRIMIDO:
                raise ErrorArchivo('El archivo es demasiado grande al abrirlo. Reduce las filas o el contenido.')
        archivo.seek(0)
    except zipfile.BadZipFile:
        raise ErrorArchivo('No se pudo leer el archivo: no parece un Excel .xlsx válido.')
    try:
        wb = load_workbook(archivo, read_only=True, data_only=True)
        ws = wb['Proyectos'] if 'Proyectos' in wb.sheetnames else wb.worksheets[0]
        filas = list(ws.iter_rows(values_only=True, max_row=MAX_FILAS + 2, max_col=len(COLUMNAS) + 10))
    except Exception:
        raise ErrorArchivo('No se pudo leer el archivo: no parece un Excel .xlsx válido.')
    if not filas:
        raise ErrorArchivo('La hoja está vacía.')
    cabecera = [_texto(c).lower() for c in filas[0]]
    indices = {}
    for titulo, _, clave in COLUMNAS:
        if titulo.lower() in cabecera:
            indices[clave] = cabecera.index(titulo.lower())
    if 'nombre' not in indices:
        raise ErrorArchivo('Falta la columna «Nombre». Usa los encabezados de la plantilla.')
    if len(filas) - 1 > MAX_FILAS:
        raise ErrorArchivo(f'Máximo {MAX_FILAS} filas por archivo.')

    tipos = {t.nombre.lower(): t for t in empresa.tipos_proyecto.all()}
    estados = {}
    for v, etiqueta in Proyecto.Estado.choices:
        estados[v.lower()] = estados[etiqueta.lower()] = v
    errores, datos, codigos_vistos = [], [], {}
    for n, fila in enumerate(filas[1:], 2):
        d = {clave: _texto(fila[i]) if i < len(fila) else '' for clave, i in indices.items()}
        if not any(d.values()):
            continue                                   # fila vacía
        d['fila'] = n
        if not d.get('nombre'):
            errores.append(f'Fila {n}: falta el nombre.')
        for clave, largo in LARGOS.items():
            if len(d.get(clave, '')) > largo:
                errores.append(f'Fila {n}: {clave.replace("_", " ")} supera {largo} caracteres.')
        cod = d.get('codigo', '').lower()
        if cod:
            if cod in codigos_vistos:
                errores.append(f'Fila {n}: el código «{d["codigo"]}» está repetido (también en la fila {codigos_vistos[cod]}).')
            codigos_vistos[cod] = n
        d['tipo_obj'] = None
        if d.get('tipo'):
            d['tipo_obj'] = tipos.get(d['tipo'].lower())
            if d['tipo_obj'] is None:
                errores.append(f'Fila {n}: el tipo «{d["tipo"]}» no existe.')
        d['estado_val'] = None
        if d.get('estado'):
            d['estado_val'] = estados.get(d['estado'].lower())
            if d['estado_val'] is None:
                errores.append(f'Fila {n}: estado «{d["estado"]}» no válido.')
        lat = _decimal(d.get('lat', ''), n, 'Latitud', Decimal(-90), Decimal(90), errores)
        lon = _decimal(d.get('lon', ''), n, 'Longitud', Decimal(-180), Decimal(180), errores)
        if bool(d.get('lat')) != bool(d.get('lon')):
            errores.append(f'Fila {n}: indica latitud y longitud juntas.')
        d['lat'], d['lon'] = lat, lon
        datos.append(d)
    if not datos and not errores:
        raise ErrorArchivo('No hay filas con datos debajo de los encabezados.')
    return datos, errores


CAMPOS_TEXTO = ('codigo', 'nombre', 'codigo_operador', 'region', 'comuna', 'ciudad', 'descripcion')


@transaction.atomic
def guardar(datos, empresa):
    """→ (creados, actualizados). Actualiza por código (sin distinguir mayúsculas) entre los registros activos."""
    existentes = {p.codigo.lower(): p for p in Proyecto.objects.de_empresa(empresa).activos().exclude(codigo='')}
    creados = actualizados = 0
    for d in datos:
        p = existentes.get(d.get('codigo', '').lower()) if d.get('codigo') else None
        nuevo = p is None
        if nuevo:
            p = Proyecto(empresa=empresa, estado=Proyecto.Estado.CONSTRUCCION)
        for campo in CAMPOS_TEXTO:
            if d.get(campo) and not (campo == 'codigo' and not nuevo):   # el código identifica: no se reescribe
                setattr(p, campo, d[campo])
        if d['tipo_obj']:
            p.tipo = d['tipo_obj']
        if d['estado_val']:
            p.estado = d['estado_val']
        p.save()
        if d['lat'] is not None:
            u = p.ubicaciones.order_by('pk').first()
            if u:
                u.lat, u.lon = d['lat'], d['lon']
                u.save(update_fields=['lat', 'lon'])
            else:
                ProyectoUbicacion.objects.create(proyecto=p, etiqueta=ETIQUETA_UBICACION, lat=d['lat'], lon=d['lon'])
        if d.get('codigo'):
            existentes[d['codigo'].lower()] = p
        creados, actualizados = creados + nuevo, actualizados + (not nuevo)
    return creados, actualizados
