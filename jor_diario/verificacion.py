"""Captura de la ubicación al marcar jornada: función pura (sin HTTP ni base de datos), fácil de probar.

No hay geocerca ni validación: se queda con la lectura de GPS más precisa que envía el navegador y la guarda para
auditoría y para el mapa. La ubicación es opcional: sin ninguna lectura legible se marca igual, sin coordenadas."""
import math

# Etiquetas de los motivos que quedan en `Jornada.verificacion`. Las de ubicación y passkey son históricas
# (ya no se generan): se conservan para mostrar jornadas antiguas.
MOTIVOS = {
    'cambio_equipo': 'Marcó desde un equipo distinto al registrado.',
    'pocas_lecturas': 'No se recibieron suficientes lecturas de GPS.',
    'lectura_vieja': 'La lectura de GPS no es reciente.',
    'precision': 'La precisión del GPS es insuficiente.',
    'precision_sospechosa': 'La precisión reportada por el GPS no es creíble.',
    'salto_imposible': 'Las lecturas de GPS saltan una distancia imposible.',
    'fuera_geocerca': 'Estás fuera del radio de la sede.',
    'sin_passkey': 'Cerrada sin passkey (desde un computador o sin celular vinculado).',
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
    """Lectura saneada {lat, lon, acc} o None si viene mal formada."""
    try:
        lat, lon, acc = float(l['lat']), float(l['lon']), float(l['accuracy'])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(map(math.isfinite, (lat, lon, acc))) or not -90 <= lat <= 90 or not -180 <= lon <= 180 or acc < 0:
        return None
    return {'lat': lat, 'lon': lon, 'acc': acc}


def mejor_lectura(lecturas):
    """→ {'lat', 'lon', 'precision_m', 'n_lecturas'} con la lectura más precisa, o None si no hay ninguna legible."""
    ls = [x for x in (_lectura(l) for l in (lecturas if isinstance(lecturas, list) else [])) if x]
    if not ls:
        return None
    mejor = min(ls, key=lambda l: l['acc'])
    return {'lat': mejor['lat'], 'lon': mejor['lon'], 'precision_m': mejor['acc'], 'n_lecturas': len(ls)}
