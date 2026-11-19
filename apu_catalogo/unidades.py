"""Unidades de medida de uso común en obra: abreviatura canónica, nombre y sinónimos. `normalizar` convierte lo que
escribe la persona («hectárea», «metros cuadrados», «m2», «hactarea») en la abreviatura («ha», «m²»). Lo desconocido se
respeta tal cual (solo con espacios normalizados): no se inventa una unidad."""
import difflib
import re
import unicodedata
from decimal import Decimal

# (abreviatura, nombre, sinónimos sin tildes). La abreviatura también cuenta como sinónimo.
UNIDADES = [
    ('m', 'metro', ('metro', 'metros', 'mt', 'mts', 'mtr', 'mtrs', 'metr')),
    ('ml', 'metro lineal', ('metro lineal', 'metros lineales', 'ml', 'm.l.', 'm lineal', 'mlin')),
    ('m²', 'metro cuadrado', ('metro cuadrado', 'metros cuadrados', 'm2', 'mt2', 'mts2', 'm^2', 'mc2')),
    ('m³', 'metro cúbico', ('metro cubico', 'metros cubicos', 'm3', 'mt3', 'mts3', 'm^3')),
    ('cm', 'centímetro', ('centimetro', 'centimetros', 'cms')),
    ('mm', 'milímetro', ('milimetro', 'milimetros')),
    ('km', 'kilómetro', ('kilometro', 'kilometros', 'kms')),
    ('pie', 'pie', ('pie', 'pies', 'ft')),
    ('pie²', 'pie cuadrado', ('pie cuadrado', 'pies cuadrados', 'pie2', 'pies2', 'ft2', 'p2')),
    ('pie³', 'pie cúbico', ('pie cubico', 'pies cubicos', 'pie3', 'pies3', 'ft3', 'p3')),
    ('pulg', 'pulgada', ('pulgada', 'pulgadas', 'pulg', 'plg')),
    ('lb', 'libra', ('libra', 'libras', 'lbs')),
    ('ha', 'hectárea', ('hectarea', 'hectareas', 'has', 'hect')),
    ('kg', 'kilogramo', ('kilogramo', 'kilogramos', 'kilo', 'kilos', 'kgs', 'kgr')),
    ('g', 'gramo', ('gramo', 'gramos', 'gr', 'grs')),
    ('t', 'tonelada', ('tonelada', 'toneladas', 'ton', 'tons', 'tn')),
    ('l', 'litro', ('litro', 'litros', 'lt', 'lts', 'lit')),
    ('gl', 'galón', ('galon', 'galones', 'gal', 'gls')),
    ('u', 'unidad', ('unidad', 'unidades', 'und', 'unds', 'un', 'unid')),
    ('pza', 'pieza', ('pieza', 'piezas', 'pz', 'pzas', 'pzs')),
    ('glb', 'global', ('global', 'gb', 'globl')),
    ('jor', 'jornada', ('jornada', 'jornadas', 'jorn')),
    ('h', 'hora', ('hora', 'horas', 'hr', 'hrs')),
    ('día', 'día', ('dia', 'dias', 'd')),
    ('mes', 'mes', ('mes', 'meses')),
    ('bls', 'bolsa', ('bolsa', 'bolsas', 'bol')),
    ('rollo', 'rollo', ('rollo', 'rollos', 'rll')),
    ('viaje', 'viaje', ('viaje', 'viajes', 'vje')),
    ('pto', 'punto', ('punto', 'puntos', 'pto', 'ptos')),
    ('par', 'par', ('par', 'pares')),
    ('jgo', 'juego', ('juego', 'juegos', 'jg')),
]


def _clave(texto):
    sin = unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', sin).strip().lower().rstrip('.')


_POR_SINONIMO = {}
for _abr, _nombre, _sins in UNIDADES:
    for _s in (_abr, _nombre, *_sins):
        _POR_SINONIMO.setdefault(_clave(_s), _abr)
_PALABRAS = [k for k in _POR_SINONIMO if len(k) >= 5]   # para tolerar errores de tipeo solo en palabras largas


def normalizar(texto):
    """La abreviatura canónica de lo escrito, o el texto limpio si no se reconoce."""
    limpio = ' '.join(str(texto or '').split())
    clave = _clave(limpio)
    if not clave:
        return ''
    if clave in _POR_SINONIMO:
        return _POR_SINONIMO[clave]
    if len(clave) >= 5:
        parecida = difflib.get_close_matches(clave, _PALABRAS, n=1, cutoff=0.8)
        if parecida:
            return _POR_SINONIMO[parecida[0]]
    return limpio


def sugerencias():
    """[(abreviatura, nombre)] para un `<datalist>`."""
    return [(abr, nombre) for abr, nombre, _ in UNIDADES]


# Equivalencias exactas dentro de una misma magnitud: cuántas unidades base hay en 1 de cada una (longitud en m, área en m²,
# volumen en m³, masa en kg). La jornada y la hora no entran: dependen de las horas de la jornada de cada cuadrilla.
_BASE = {
    'longitud': {'m': '1', 'ml': '1', 'cm': '0.01', 'mm': '0.001', 'km': '1000', 'pie': '0.3048', 'pulg': '0.0254'},
    'área': {'m²': '1', 'ha': '10000', 'pie²': '0.09290304'},
    'volumen': {'m³': '1', 'l': '0.001', 'gl': '0.003785411784', 'pie³': '0.028316846592'},
    'masa': {'kg': '1', 'g': '0.001', 't': '1000', 'lb': '0.45359237'},
}
_MAGNITUD = {u: (m, Decimal(f)) for m, tabla in _BASE.items() for u, f in tabla.items()}


def factor(origen, destino):
    """Cuántas `destino` hay en 1 `origen` (p. ej. de «m²» a «pie²» = 10.7639…), o None si no se pueden convertir solas
    (otra magnitud, o una unidad que no está en la tabla). Acepta lo que escribe la persona («m2», «pie2»)."""
    a, b = _MAGNITUD.get(normalizar(origen)), _MAGNITUD.get(normalizar(destino))
    if not a or not b or a[0] != b[0]:
        return None
    return a[1] / b[1]
