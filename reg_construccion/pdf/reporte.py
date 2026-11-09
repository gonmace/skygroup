"""PDF «Reporte de avance» de una visita de Construcción (plantilla heredada de reg.tekon-rl.cl).

weasyprint se importa de forma perezosa (tarda en cargar). Las imágenes viajan incrustadas como data URI: viven en
el storage privado (disco o S3) y WeasyPrint no debe pedir nada por red.
"""
import base64
import io
import re
from decimal import Decimal
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string

from reg_actividades.models import DatoPaso
from reg_actividades.widgets.tabla_avance import redondear, serie_proyecto
from reg_fotos.models import Foto

from ..models import PASO_AVANCE, RegConstruccion

PASO_ACTIVIDADES = 'obra_objetivos'   # la clave conserva su nombre original para no migrar datos
PASO_LIBRO = 'obra_libro'
PASO_ELECTRICO = 'obra_electrico'
PASO_COMENTARIOS = 'obra_comentarios'
# Clave del selector «1/2 por fila» → (etapa de las fotos, título).
SECCIONES_FOTOS = (('actividades', PASO_ACTIVIDADES, 'Actividades'),
                   ('libro', PASO_LIBRO, 'Libro de obras'),
                   ('electrico', PASO_ELECTRICO, 'Eléctrico'))
LADO_MAX = 1600   # px: WeasyPrint decodifica a resolución nativa; una foto de 12 MP ocupa ~48 MB en RAM
CSS = Path(__file__).with_name('reporte.css')


def _dato(registro, ct, paso):
    return DatoPaso.objects.filter(content_type=ct, object_id=registro.pk, paso_nombre=paso).first()


def _lista(registro, ct, paso):
    d = _dato(registro, ct, paso)
    return [str(i) for i in (_buscar(d, 'entradas') or []) if str(i).strip()]


def _texto(registro, ct, paso):
    return str(_buscar(_dato(registro, ct, paso), 'comentario') or '').strip()


def _buscar(dato, campo):
    """Los datos son {widget_slug: {campo: …}}; devuelve el primer `campo` que aparezca."""
    for valores in ((dato.datos if dato else None) or {}).values():
        if isinstance(valores, dict) and campo in valores:
            return valores[campo]
    return None


def _dms(valor, positivo, negativo):
    """41° 52′ 03,4″ S — segundos con 1 decimal y coma decimal."""
    if valor is None:
        return '—'
    a = abs(valor)
    g = int(a)
    mt = (a - g) * 60
    m = int(mt)
    s = round((mt - m) * 60, 1)
    if s >= 60:
        s, m = 0.0, m + 1
    if m >= 60:
        m, g = 0, g + 1
    return f"{g}° {m:02d}′ {s:04.1f}″ {positivo if valor >= 0 else negativo}".replace('.', ',')


def _decimal(valor):
    return f'{valor:.6f}'.replace('.', ',') if valor is not None else '—'


def _fmt(d, decimales=1):
    return f'{redondear(d, decimales):.{decimales}f}'.replace('.', ',')


def _data_uri(campo):
    """(data URI JPEG reducido y derecho, 'portrait'|'landscape') de un ImageField, o (None, …) si no se lee."""
    from PIL import Image, ImageOps
    try:
        with campo.open('rb') as f:
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(f.read())))   # WeasyPrint no aplica la orientación EXIF
        img.thumbnail((LADO_MAX, LADO_MAX))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        salida = io.BytesIO()
        img.save(salida, 'JPEG', quality=82)
    except Exception:
        return None, 'landscape'
    uri = 'data:image/jpeg;base64,' + base64.b64encode(salida.getvalue()).decode()
    return uri, 'portrait' if img.height > img.width else 'landscape'


def _fotos(registro, ct, etapa, desde=1):
    """Fotos de una etapa; la numeración («Imagen n») continúa entre secciones."""
    salida = []
    qs = Foto.objects.filter(content_type=ct, object_id=registro.pk, etapa=etapa).order_by('orden', 'id')
    for n, p in enumerate(qs, start=desde):
        uri, orientacion = _data_uri(p.imagen)
        if uri is None:
            continue
        leyenda = (p.descripcion or '').strip()
        salida.append({
            'url': uri, 'orientation': orientacion,
            'descripcion': f'Imagen {n}: {leyenda}' if leyenda else f'Imagen {n}',
            'exif_datetime': p.exif_fecha.strftime('%d/%m/%Y %H:%M') if p.exif_fecha else None,
            'exif_lat': round(p.exif_lat, 6) if p.exif_lat is not None else None,
            'exif_lon': round(p.exif_lon, 6) if p.exif_lon is not None else None,
        })
    return salida


def secciones_con_fotos(registro):
    ct = ContentType.objects.get_for_model(RegConstruccion)
    con = set(Foto.objects.filter(content_type=ct, object_id=registro.pk).values_list('etapa', flat=True))
    return [{'key': k, 'label': l} for k, paso, l in SECCIONES_FOTOS if paso in con]


def nombre_archivo(registro):
    def limpio(s):
        return re.sub(r'[\\/:*?"<>|]', '', str(s or '')).strip()
    p = registro.proyecto
    partes = [limpio(p.codigo), limpio(p.codigo_operador),
              f'reporte{registro.numero_visita}', registro.fecha.strftime('%Y%m%d')]
    if not registro.concluido:
        partes.append('borrador')
    return '-'.join(x for x in partes if x) + '.pdf'


def contexto(registro, columnas):
    """`columnas`: {'actividades'|'libro'|'electrico': 1 | 2}."""
    proyecto = registro.proyecto
    ct = ContentType.objects.get_for_model(RegConstruccion)
    serie = serie_proyecto(registro, PASO_AVANCE)
    actual = serie[-1][1]
    anterior = serie[-2][1]['total'] if len(serie) > 1 else None
    partidas = [{
        'nombre': f['nombre'],
        'incidencia': _fmt(f['incidencia'], 0 if f['incidencia'] == int(f['incidencia']) else 1),
        'anterior': _fmt(f['anterior'], 0), 'actual': _fmt(f['actual'], 0),
        'acumulada': _fmt(f['acumulada'], 0), 'total': _fmt(f['total'], 1),
        'w_anterior': float(f['anterior']), 'w_actual': float(f['acumulada'] - f['anterior']),
    } for f in actual['filas']]

    inicio = (RegConstruccion.objects.filter(proyecto=proyecto, empresa=registro.empresa, is_deleted=False)
              .order_by('fecha').values_list('fecha', flat=True).first())
    lat, lon = registro.coordenadas
    f_act = _fotos(registro, ct, PASO_ACTIVIDADES)
    f_lib = _fotos(registro, ct, PASO_LIBRO, desde=len(f_act) + 1)
    f_ele = _fotos(registro, ct, PASO_ELECTRICO, desde=len(f_act) + len(f_lib) + 1)
    empresa = registro.empresa
    logo = None
    if getattr(empresa, 'logo_claro', None):
        logo = _data_uri(empresa.logo_claro)[0]
    cols = lambda k: columnas.get(k, 2)   # noqa: E731
    return {
        'registro': registro, 'empresa': empresa, 'logo_empresa': logo, 'proyecto': proyecto,
        'codigo': proyecto.codigo,
        'borrador': not registro.concluido,   # sin concluir → marca de agua «BORRADOR»
        'supervisor': registro.responsable_nombre,
        'fecha_inicio': inicio,
        'dias_transcurridos': (registro.fecha - inicio).days if inicio else None,
        'coord_lat': _dms(lat, 'N', 'S'), 'coord_lon': _dms(lon, 'E', 'O'),
        'coord_lat_deg': _decimal(lat), 'coord_lon_deg': _decimal(lon),
        'actividades': _lista(registro, ct, PASO_ACTIVIDADES),
        'comentarios': _lista(registro, ct, PASO_COMENTARIOS),
        'electrico_texto': _texto(registro, ct, PASO_ELECTRICO),
        'partidas': partidas,
        'total_general': _fmt(actual['total'], 1),
        'suma_incidencia': _fmt(sum((f['incidencia'] for f in actual['filas']), Decimal('0')), 0),
        'total_anterior': _fmt(anterior, 1) if anterior is not None else None,
        'delta': _fmt(actual['total'] - anterior, 1) if anterior is not None else None,
        'delta_positivo': anterior is not None and actual['total'] >= anterior,
        'w_total': float(actual['total']),
        'fotos_actividades': f_act, 'fotos_actividades_cols': cols('actividades'),
        'fotos_libro': f_lib, 'fotos_libro_cols': cols('libro'),
        'fotos_electrico': f_ele, 'fotos_electrico_cols': cols('electrico'),
    }


def generar(registro, columnas=None):
    """Bytes del PDF."""
    from weasyprint import CSS as Css, HTML
    html = render_to_string('reg_construccion/pdf/reporte.html', contexto(registro, columnas or {}))
    return HTML(string=html).write_pdf(stylesheets=[Css(filename=str(CSS))])
