"""Iniciar la jornada desde el computador escaneando un QR con el celular.

El computador (con la sesión de la persona) crea una solicitud de un solo uso y muestra su QR. El celular lo abre SIN
iniciar sesión: el token firmado dice a quién corresponde y el passkey del celular vinculado prueba que es él; la
ubicación que se captura es la del celular. La solicitud vive en caché (caduca sola) y se invalida al completarse."""
import secrets

from django.core import signing
from django.core.cache import cache

TTL_S = 300
_SAL = 'jor-marca-qr'


class ErrorSolicitud(Exception):
    """Mensaje apto para mostrar a la persona."""


def _clave(nonce):
    return f'jor:qr:{nonce}'


def crear(perfil, proyecto_id=None):
    """→ (nonce, token). El nonce lo conserva el computador (consulta el estado); el token va en el QR."""
    nonce = secrets.token_urlsafe(18)
    cache.set(_clave(nonce), {'p': perfil.pk, 'pr': proyecto_id, 'e': 'pendiente'}, TTL_S + 30)
    return nonce, signing.dumps({'n': nonce}, salt=_SAL)


def cargar(token):
    """→ (nonce, datos) de una solicitud vigente y pendiente; ErrorSolicitud si caducó, se usó o no es válida."""
    try:
        nonce = signing.loads(token, salt=_SAL, max_age=TTL_S)['n']
    except (signing.BadSignature, KeyError, TypeError):
        raise ErrorSolicitud('Este código no es válido.')
    datos = cache.get(_clave(nonce))
    if not datos or datos['e'] != 'pendiente':
        raise ErrorSolicitud('Este código ya se usó o caducó. Genera uno nuevo desde tu computador.')
    return nonce, datos


def completar(nonce):
    datos = cache.get(_clave(nonce))
    if datos:
        cache.set(_clave(nonce), {**datos, 'e': 'hecha'}, 120)


def estado(nonce, perfil):
    """'pendiente' | 'hecha' | 'caducada' para el computador que creó la solicitud (solo su dueño)."""
    datos = cache.get(_clave(nonce))
    if not datos or datos['p'] != perfil.pk:
        return 'caducada'
    return datos['e']
