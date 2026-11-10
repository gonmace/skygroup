"""Control de acceso común a las vistas de un módulo."""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404

from cuentas.capacidades import administra, tiene_capacidad


def _puede_entrar(user, empresa, capacidades):
    """Superusuario o miembro activo; o administrador de sistema de la empresa SIN ser miembro, pero solo si la vista
    exige capacidades (de ámbito empresa: son las únicas que recibe sin membresía) y las tiene todas. Una vista que
    pide solo «ser miembro» sigue cerrada para él."""
    if user.is_superuser or user.membresias.filter(empresa=empresa, activa=True).exists():
        return True
    return bool(capacidades) and administra(user, empresa.pk) and all(tiene_capacidad(user, c, empresa) for c in capacidades)


def acceso_modulo(codigo, *capacidades):
    """Decorador de vistas de un módulo (`reg`, `tar`, `jor`): sesión → empresa con el módulo ACTIVO →
    membresía activa (o superusuario; o administrador de la empresa si la vista exige capacidades de ámbito
    empresa) → TODAS las capacidades indicadas. Sin capacidades basta ser miembro.
    Una ruta sin prefijo de empresa, o de un módulo no habilitado, es 404."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            empresa = getattr(request, 'empresa', None)
            if empresa is None or not empresa.tiene_modulo(codigo):
                raise Http404
            if not _puede_entrar(request.user, empresa, capacidades):
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
            if not _puede_entrar(request.user, empresa, capacidades):
                raise PermissionDenied
            if not all(tiene_capacidad(request.user, c, empresa) for c in capacidades):
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador
