"""Registro de tipos de widget. Cada módulo de este paquete se registra al importarse."""
_REGISTRO = {}


def registrar(cls):
    instancia = cls()
    _REGISTRO[instancia.slug] = instancia
    return cls


def obtener(slug):
    return _REGISTRO.get(slug)


def todos():
    return list(_REGISTRO.values())


from . import comentario, distancia, firma, fotos, lista, form_dinamico, poste, tabla, tabla_avance, ubicacion  # noqa: E402,F401
from . import mapas  # noqa: E402,F401  (mapa_1p, mapa_2_puntos)
