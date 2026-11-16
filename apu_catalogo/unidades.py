"""Unidades de medida de uso común en obra: abreviatura canónica, nombre y sinónimos. `normalizar` convierte lo que
escribe la persona («hectárea», «metros cuadrados», «m2», «hactarea») en la abreviatura («ha», «m²»). Lo desconocido se
respeta tal cual (solo con espacios normalizados): no se inventa una unidad."""
import difflib
import re
import unicodedata

# (abreviatura, nombre, sinónimos sin tildes). La abreviatura también cuenta como sinónimo.
UNIDADES = [
    ('m', 'metro', ('metro', 'metros', 'mt', 'mts', 'mtr', 'mtrs', 'metr')),
    ('ml', 'metro lineal', ('metro lineal', 'metros lineales', 'ml', 'm.l.', 'm lineal', 'mlin')),
    ('m²', 'metro cuadrado', ('metro cuadrado', 'metros cuadrados', 'm2', 'mt2', 'mts2', 'm^2', 'mc2')),
    ('m³', 'metro cúbico', ('metro cubico', 'metros cubicos', 'm3', 'mt3', 'mts3', 'm^3')),
    ('cm', 'centímetro', ('centimetro', 'centimetros', 'cms')),
    ('mm', 'milímetro', ('milimetro', 'milimetros')),
    ('km', 'kilómetro', ('kilometro', 'kilometros', 'kms')),
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
