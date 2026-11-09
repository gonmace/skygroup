"""Imagen estática de los widgets de mapa (`mapa_1p`, `mapa_2_puntos`): coordenadas, zoom, descarga a Google Static
Maps y persistencia en `ImagenMapa`.

Las coordenadas se resuelven SIEMPRE en el servidor a partir de lo guardado (nunca del cuerpo de la petición), así la
imagen del informe refleja los datos reales del registro."""
import logging
import math
import re
import unicodedata

import requests
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import transaction

from reg_base.geo import distancia_m

from .models import DatoPaso, ImagenMapa

logger = logging.getLogger(__name__)

URL_STATIC_MAPS = 'https://maps.googleapis.com/maps/api/staticmap'
TAMANO = '640x640'
COLOR_1, COLOR_2 = '#e74c3c', '#0054ff'
_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def hay_clave():
    return bool(getattr(settings, 'GOOGLE_MAPS_API_KEY', ''))


def _sin_acentos(texto):
    texto = unicodedata.normalize('NFD', str(texto or ''))
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn').strip().lower()


def color_valido(valor):
    return bool(_HEX.match(str(valor or '')))


def _numero(valor):
    try:
        return float(str(valor).replace(',', '.'))
    except (TypeError, ValueError):
        return None


# ── coordenadas ──────────────────────────────────────────────────────────────────

def coordenada_de_paso(registro, nombre_paso):
    """(lat, lon) del paso `nombre_paso` del registro: la ubicación capturada en ese paso (cualquier widget con
    `lat` y `lon`, normalmente `ubicacion_widget`); si no hay, la ubicación del proyecto cuya etiqueta coincida con el
    nombre del paso (mandato, ingeniería, construcción…). (None, None) si no hay nada."""
    nombre = (nombre_paso or '').strip()
    if not nombre:
        return None, None
    ct = ContentType.objects.get_for_model(type(registro))
    dato = DatoPaso.objects.filter(content_type=ct, object_id=registro.pk, paso_nombre=nombre).first()
    for bloque in ((dato.datos if dato else None) or {}).values():
        if isinstance(bloque, dict):
            lat, lon = _numero(bloque.get('lat')), _numero(bloque.get('lon'))
            if lat is not None and lon is not None:
                return lat, lon
    proyecto = getattr(registro, 'proyecto', None)
    if proyecto is not None:
        objetivo = _sin_acentos(nombre)
        for u in proyecto.ubicaciones.all():
            if _sin_acentos(u.etiqueta) == objetivo:
                return float(u.lat), float(u.lon)
    return None, None


def coordenada_del_proyecto(registro):
    proyecto = getattr(registro, 'proyecto', None)
    if proyecto is not None:
        lat, lon = proyecto.coordenada_principal
        if lat is not None:
            return float(lat), float(lon)
    return None, None


def puntos_de_widget(slug, config, registro, paso):
    """Lista de puntos [{lat, lon, label, color}] que dibuja un widget de mapa (vacía si no hay coordenadas).

    - `mapa_1p`: la ubicación del propio paso (o del paso indicado en `paso`); si no hay, la del proyecto.
    - `mapa_2_puntos`: la de los pasos `paso1` y `paso2` de la config (el segundo es opcional en la imagen)."""
    config = config or {}
    if slug == 'mapa_2_puntos':
        pares = [(config.get('paso1'), config.get('label1') or 'A', config.get('color1') or COLOR_1),
                 (config.get('paso2'), config.get('label2') or 'B', config.get('color2') or COLOR_2)]
        puntos = []
        for nombre, etiqueta, color in pares:
            lat, lon = coordenada_de_paso(registro, nombre)
            if lat is not None:
                puntos.append({'lat': lat, 'lon': lon, 'label': str(etiqueta)[:1].upper(),
                               'color': color if color_valido(color) else COLOR_1})
            elif not puntos:      # sin el primero no hay mapa
                break
        return puntos
    lat, lon = coordenada_de_paso(registro, config.get('paso') or paso.nombre)
    if lat is None:
        lat, lon = coordenada_del_proyecto(registro)
    if lat is None:
        return []
    color = config.get('color')
    return [{'lat': lat, 'lon': lon, 'label': str(config.get('label') or 'M')[:1].upper(),
             'color': color if color_valido(color) else '#3b82f6'}]


def distancias(puntos):
    """(total, desfase) en metros: suma entre puntos consecutivos; el desfase solo con exactamente 2 puntos."""
    if len(puntos) < 2:
        return None, None
    total = 0.0
    for a, b in zip(puntos, puntos[1:]):
        d = distancia_m(a['lat'], a['lon'], b['lat'], b['lon'])
        if d is None:
            return None, None
        total += d
    return total, (total if len(puntos) == 2 else None)


# ── Google Static Maps ───────────────────────────────────────────────────────────

def _lat_rad_mercator(lat):
    s = math.sin(lat * math.pi / 180)
    r = math.log((1 + s) / (1 - s)) / 2
    return max(min(r, math.pi), -math.pi) / 2


def calcular_zoom_optimo(puntos, tamano=TAMANO, margen_px=60):
    """Zoom máximo (1..21) con TODOS los puntos dentro de la imagen, con `margen_px` de aire por lado. Un solo
    punto → 20; puntos idénticos → 21."""
    pts = [(float(p['lat']), float(p['lon'])) for p in puntos]
    if len(pts) < 2:
        return 20
    try:
        iw, ih = (int(x) for x in str(tamano).lower().split('x'))
    except (ValueError, AttributeError):
        iw, ih = 640, 640
    pw, ph = max(1, iw - 2 * margen_px), max(1, ih - 2 * margen_px)
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    lat_frac = (_lat_rad_mercator(max(lats)) - _lat_rad_mercator(min(lats))) / math.pi
    lon_frac = (max(lons) - min(lons)) / 360.0

    def ajuste(mapa_px, fraccion):
        return 21 if fraccion == 0 else math.floor(math.log(mapa_px / 256 / fraccion) / math.log(2))

    return max(1, min(ajuste(ph, lat_frac), ajuste(pw, lon_frac), 21))


def descargar_imagen(puntos, zoom=None, maptype='hybrid', scale=2, tamano=TAMANO):
    """Bytes PNG de la imagen estática con un marcador por punto; None si no hay clave, no hay puntos o Google falla."""
    clave = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')
    if not clave:
        logger.warning('GOOGLE_MAPS_API_KEY no está configurada: no se genera la imagen del mapa.')
        return None
    if not puntos:
        return None
    zoom = zoom or calcular_zoom_optimo(puntos, tamano)
    lats, lons = [p['lat'] for p in puntos], [p['lon'] for p in puntos]
    params = [('center', f'{(min(lats) + max(lats)) / 2},{(min(lons) + max(lons)) / 2}'), ('zoom', str(zoom)),
              ('size', tamano), ('maptype', maptype), ('scale', str(scale)), ('key', clave)]
    for p in puntos:
        color = '0x' + p['color'][1:].upper()
        params.append(('markers', f'color:{color}|size:mid|label:{p["label"][:1].upper() or "M"}|{p["lat"]},{p["lon"]}'))
    try:
        r = requests.get(URL_STATIC_MAPS, params=params, timeout=30)
    except requests.RequestException:
        logger.exception('Error de conexión con Google Maps')
        return None
    if r.status_code != 200:
        logger.error('Google Maps respondió %s: %s', r.status_code, r.text[:200])
        return None
    return r.content


# ── persistencia ─────────────────────────────────────────────────────────────────

def imagen_de(registro, etapa):
    ct = ContentType.objects.get_for_model(type(registro))
    return ImagenMapa.objects.filter(content_type=ct, object_id=registro.pk, etapa=etapa).first()


def _nombre_archivo(registro, etapa):
    codigo = getattr(getattr(registro, 'proyecto', None), 'codigo', '') or 'SIN_CODIGO'
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', f'{codigo}_{etapa}') + '.png'


def guardar_imagen(registro, etapa, puntos):
    """Genera y guarda (reemplazando) la imagen del mapa del paso. Devuelve la `ImagenMapa` o None si no se pudo
    generar (sin clave, sin puntos o error de Google); en ese caso no se toca la imagen anterior."""
    contenido = descargar_imagen(puntos)
    if not contenido:
        return None
    zoom = calcular_zoom_optimo(puntos)
    total, desfase = distancias(puntos)
    ct = ContentType.objects.get_for_model(type(registro))
    with transaction.atomic():
        obj, _creada = ImagenMapa.objects.update_or_create(
            content_type=ct, object_id=registro.pk, etapa=etapa,
            defaults={'empresa_id': registro.empresa_id, 'zoom': zoom, 'maptype': 'hybrid', 'scale': 2,
                      'tamano': TAMANO, 'coordenadas': puntos, 'distancia_total_metros': total,
                      'desfase_metros': desfase})
        anterior = obj.imagen.name if obj.imagen else None
        obj.imagen.save(_nombre_archivo(registro, etapa), ContentFile(contenido), save=True)
        if anterior and anterior != obj.imagen.name:
            try:
                obj.imagen.storage.delete(anterior)
            except Exception:
                logger.warning('No se pudo borrar la imagen de mapa anterior %s', anterior, exc_info=True)
    return obj


def regenerar_afectados(registro, clave, paso_cambiado):
    """Tras guardar el paso `paso_cambiado`: regenera la imagen de cada `mapa_2_puntos` del registro que lo use como
    `paso1`/`paso2` y cuyos puntos hayan cambiado respecto a lo guardado (no se gasta cuota si nada cambió). Solo
    actúa si ya existía una imagen (la primera la crea la persona con «Guardar imagen») y hay clave configurada."""
    if not hay_clave():
        return
    cambiado = _sin_acentos(paso_cambiado)
    from .servicios import asignados_de
    for a in asignados_de(registro, clave):
        for pw in a.paso.widgets.all():
            if pw.widget_slug != 'mapa_2_puntos':
                continue
            cfg = pw.config or {}
            if cambiado not in (_sin_acentos(cfg.get('paso1')), _sin_acentos(cfg.get('paso2'))):
                continue
            existente = imagen_de(registro, a.paso.nombre)
            puntos = puntos_de_widget('mapa_2_puntos', cfg, registro, a.paso)
            if existente is None or not puntos or existente.coordenadas == puntos:
                continue
            guardar_imagen(registro, a.paso.nombre, puntos)
