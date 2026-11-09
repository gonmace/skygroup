"""Control de acceso de las vistas de un TIPO de registro."""
from functools import wraps

from django.http import Http404

from empresas.acceso import acceso_modulo

from . import tipos


def acceso_tipo(clave, *capacidades):
    """Como `acceso_modulo('reg', …)`, y además 404 si el tipo de registro no está activo en la empresa
    (ver `reg_base.tipos.habilitar`). El tipo se comprueba antes que las capacidades."""
    def decorador(vista):
        protegida = acceso_modulo('reg', *capacidades)(vista)

        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if request.user.is_authenticated and not tipos.esta_habilitado(getattr(request, 'empresa', None), clave):
                raise Http404
            return protegida(request, *args, **kwargs)
        return envoltura
    return decorador
