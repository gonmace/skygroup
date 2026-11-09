"""Utilidades geográficas sin dependencias externas."""
from math import asin, cos, radians, sin, sqrt

RADIO_TIERRA_M = 6_371_008.8


def distancia_m(lat1, lon1, lat2, lon2):
    """Distancia (m) entre dos puntos por la fórmula de Haversine; None si algún dato no es numérico."""
    try:
        la1, lo1, la2, lo2 = (radians(float(x)) for x in (lat1, lon1, lat2, lon2))
    except (TypeError, ValueError):
        return None
    a = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * RADIO_TIERRA_M * asin(sqrt(a))


def formatear_distancia(metros):
    if metros is None:
        return 'Sin calcular'
    return f'{metros:.0f} m' if metros < 1000 else f'{metros / 1000:.3f} km ({metros:.0f} m)'
