"""Verificación de presencia al marcar jornada: función pura (sin HTTP ni base de datos), fácil de probar.

Recibe las lecturas de GPS que envía el celular y la sede de la persona, y devuelve qué comprobaciones fallaron.
Las que fallan («motivos») mandan la jornada a revisión; los «avisos» solo quedan registrados para quien revisa."""
import math
import time

MAX_EDAD_S = 15            # la lectura más reciente no puede tener más antigüedad que esto
MIN_LECTURAS = 2
VELOCIDAD_MAX_MS = 55      # ≈200 km/h entre dos lecturas consecutivas: más que eso es un salto imposible
PRECISION_MIN_CREIBLE_M = 1  # un GPS real de celular no reporta menos de ~3 m; <1 m es típico de ubicaciones simuladas

MOTIVOS = {
    'pocas_lecturas': 'No se recibieron suficientes lecturas de GPS.',
    'lectura_vieja': 'La lectura de GPS no es reciente.',
    'precision': 'La precisión del GPS es insuficiente.',
    'precision_sospechosa': 'La precisión reportada por el GPS no es creíble.',
    'salto_imposible': 'Las lecturas de GPS saltan una distancia imposible.',
    'fuera_geocerca': 'Estás fuera del radio de la sede.',
    # Etiquetas históricas (ya no se generan): se conservan para mostrar jornadas antiguas.
    'no_movil': 'No se marcó desde un celular.',
    'cierre_pc': 'Cerrada desde un computador.',
}


def distancia_m(lat1, lon1, lat2, lon2):
    """Distancia haversine en metros."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _lectura(l):
    """Lectura saneada {lat, lon, acc, ts (segundos)} o None si viene mal formada."""
    try:
        lat, lon, acc, ts = float(l['lat']), float(l['lon']), float(l['accuracy']), float(l['timestamp']) / 1000
    except (KeyError, TypeError, ValueError):
        return None
    if not all(map(math.isfinite, (lat, lon, acc, ts))) or not -90 <= lat <= 90 or not -180 <= lon <= 180 or acc < 0:
        return None
    return {'lat': lat, 'lon': lon, 'acc': acc, 'ts': ts}


def verificar_presencia(sede, lecturas, ahora=None, min_lecturas=MIN_LECTURAS):
    """→ {'ok', 'motivos', 'avisos', 'distancia_m', 'precision_m', 'lat', 'lon'}.

    `sede`: objeto con `lat`, `lon`, `radio_m`, `precision_max_m` (o None). `lecturas`: lista de
    {lat, lon, accuracy, timestamp en ms}. `ahora`: segundos epoch (por defecto, el reloj del servidor)."""
    ahora = time.time() if ahora is None else ahora
    motivos, avisos = [], []
    ls = sorted(filter(None, (_lectura(l) for l in (lecturas if isinstance(lecturas, list) else []))),
                key=lambda l: l['ts'])
    res = {'ok': False, 'motivos': motivos, 'avisos': avisos, 'distancia_m': None, 'precision_m': None,
           'lat': None, 'lon': None}
    con_sede = sede is not None and sede.lat is not None and sede.lon is not None
    if not con_sede:
        avisos.append('sin_geocerca')   # sede sin ubicación: solo se captura dónde marcó; no bloquea ni exige aprobación
    if len(ls) < min_lecturas:
        motivos.append('pocas_lecturas')
        return res
    mejor = min(ls, key=lambda l: l['acc'])
    res.update(lat=mejor['lat'], lon=mejor['lon'], precision_m=mejor['acc'])
    if abs(ahora - ls[-1]['ts']) > MAX_EDAD_S:
        motivos.append('lectura_vieja')
    if mejor['acc'] < PRECISION_MIN_CREIBLE_M:
        motivos.append('precision_sospechosa')
    elif con_sede and mejor['acc'] > sede.precision_max_m:
        motivos.append('precision')
    for a, b in zip(ls, ls[1:]):
        dt = b['ts'] - a['ts']
        d = distancia_m(a['lat'], a['lon'], b['lat'], b['lon'])
        if (dt > 0 and d / dt > VELOCIDAD_MAX_MS) or (dt <= 0 and d > max(a['acc'], b['acc'], 50)):
            motivos.append('salto_imposible')
            break
    if len({(l['lat'], l['lon'], l['acc']) for l in ls}) == 1:
        avisos.append('lecturas_identicas')   # normal con ubicación por Wi-Fi; solo informa a quien revisa
    if con_sede:
        res['distancia_m'] = round(distancia_m(mejor['lat'], mejor['lon'], float(sede.lat), float(sede.lon)), 1)
        if res['distancia_m'] > sede.radio_m:
            motivos.append('fuera_geocerca')
    res['ok'] = not motivos
    return res

