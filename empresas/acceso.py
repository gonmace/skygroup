"""Control de acceso común a las vistas de un módulo."""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404

from cuentas.capacidades import tiene_capacidad


def acceso_modulo(codigo, *capacidades):
    """Decorador de vistas de un módulo (`reg`, `tar`, `jor`): sesión → empresa con el módulo ACTIVO →
    membresía activa (o superusuario) → TODAS las capacidades indicadas. Sin capacidades basta ser miembro.
    Una ruta sin prefijo de empresa, o de un módulo no habilitado, es 404."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            empresa = getattr(request, 'empresa', None)
            if empresa is None or not empresa.tiene_modulo(codigo):
                raise Http404
            if not request.user.is_superuser and not request.user.membresias.filter(
                    empresa=empresa, activa=True).exists():
                raise PermissionDenied
            if not all(tiene_capacidad(request.user, c, empresa) for c in capacidades):
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador


def acceso_empresa(*capacidades):
    """Como `acceso_modulo` pero para funciones de la plataforma que no pertenecen a un módulo (mensajes…):
    sesión → empresa → membresía activa (o superusuario) → TODAS las capacidades indicadas."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            empresa = getattr(request, 'empresa', None)
            if empresa is None:
                raise Http404
            if not request.user.is_superuser and not request.user.membresias.filter(
                    empresa=empresa, activa=True).exists():
                raise PermissionDenied
            if not all(tiene_capacidad(request.user, c, empresa) for c in capacidades):
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador
