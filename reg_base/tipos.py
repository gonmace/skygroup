"""Registro de los tipos de registro (TX/TSS, Construcción, Construcción base…).

Las apps que operan sobre «cualquier registro» (fotos, pasos, PDF) se resuelven por la clave corta de la URL
(`txtss`, `construccion`, `construccion-base`) a través de este registro, sin importar los modelos concretos.

Los tipos se definen en código (todos existen en la plataforma), pero cada EMPRESA tiene activos solo los que
use: `TipoHabilitado`. Un tipo desactivado desaparece del menú y sus rutas dan 404, pero sus datos se conservan.
"""
from dataclasses import dataclass
from typing import Callable, Optional

from django.http import Http404


@dataclass(frozen=True)
class Tipo:
    clave: str            # va en la URL: /registros/<clave>/<pk>/…
    modelo: type
    capacidad_ver: str    # capacidad que da acceso al reporte
    url_detalle: str      # nombre de URL del detalle (recibe pk)
    nombre: str
    descripcion: str = ''
    # Gancho al activar el tipo en una empresa (p. ej. sembrar su plantilla de pasos): fn(empresa).
    al_habilitar: Optional[Callable] = None
    # Panel del Resumen de Registros: fn(user, empresa) -> dict de contexto (o None) y plantilla que lo pinta.
    panel: Optional[Callable] = None
    plantilla_panel: str = ''
    # Restaura la plantilla de pasos estándar del tipo en una empresa: fn(empresa). Solo si el tipo tiene una.
    restaurar: Optional[Callable] = None
    # El modelo del tipo incluye `RevisionesMixin`: se habilitan las revisiones (crear con comentario, elegir la vigente).
    con_revisiones: bool = False


_TIPOS = {}


def registrar_tipo(clave, modelo, capacidad_ver, url_detalle, nombre, descripcion='', al_habilitar=None,
                   panel=None, plantilla_panel='', restaurar=None, con_revisiones=False):
    _TIPOS[clave] = Tipo(clave, modelo, capacidad_ver, url_detalle, nombre, descripcion, al_habilitar, panel,
                         plantilla_panel, restaurar, con_revisiones)


def tipo(clave):
    try:
        return _TIPOS[clave]
    except KeyError:
        raise Http404(f'Tipo de registro desconocido: {clave}')


def tipo_de_modelo(modelo):
    for t in _TIPOS.values():
        if t.modelo is modelo:
            return t
    return None


def todos():
    return list(_TIPOS.values())


# ── Tipos activos por empresa ───────────────────────────────────────────────────────────────────────

def _claves_habilitadas(empresa):
    """Claves activas de la empresa. Se guarda en la instancia (una consulta por petición); `habilitar` y
    `deshabilitar` la invalidan."""
    if empresa is None:
        return set()
    cache = getattr(empresa, '_tipos_habilitados', None)
    if cache is None:
        from .models import TipoHabilitado
        cache = set(TipoHabilitado.objects.filter(empresa=empresa).values_list('clave', flat=True))
        empresa._tipos_habilitados = cache
    return cache


def esta_habilitado(empresa, clave):
    return clave in _claves_habilitadas(empresa)


def habilitados(empresa):
    """Tipos activos de la empresa, en el orden en que se registraron."""
    activas = _claves_habilitadas(empresa)
    return [t for t in _TIPOS.values() if t.clave in activas]


def habilitar(empresa, clave):
    """Activa el tipo en la empresa (idempotente) y ejecuta su gancho `al_habilitar` la primera vez."""
    from .models import TipoHabilitado
    t = tipo(clave)
    _, creado = TipoHabilitado.objects.get_or_create(empresa=empresa, clave=clave)
    empresa._tipos_habilitados = None
    if creado and t.al_habilitar:
        t.al_habilitar(empresa)
    return creado


def deshabilitar(empresa, clave):
    """Desactiva el tipo: se oculta, pero sus registros, fotos y plantillas NO se borran."""
    from .models import TipoHabilitado
    TipoHabilitado.objects.filter(empresa=empresa, clave=clave).delete()
    empresa._tipos_habilitados = None


def tipo_de_request(request, clave):
    """El tipo de la URL, solo si está activo en la empresa de la petición; si no, 404."""
    t = tipo(clave)
    if not esta_habilitado(getattr(request, 'empresa', None), t.clave):
        raise Http404(f'El tipo de registro «{clave}» no está activo en esta empresa.')
    return t
