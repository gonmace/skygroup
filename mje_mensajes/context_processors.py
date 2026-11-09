from cuentas.capacidades import tiene_capacidad

from .servicios import no_leidos


def mensajeria(request):
    """`msj_activo`: la empresa tiene el módulo Mensajería y la persona tiene acceso (decide si se monta el panel
    lateral, el botón de la barra superior y el JS). `mensajes_no_leidos`: contador inicial del botón."""
    user = getattr(request, 'user', None)
    empresa = getattr(request, 'empresa', None)
    if not user or not user.is_authenticated or empresa is None:
        return {'msj_activo': False}
    if not empresa.tiene_modulo('msj') or not tiene_capacidad(user, 'msj.usar', empresa):
        return {'msj_activo': False}
    return {'msj_activo': True, 'mensajes_no_leidos': no_leidos(user, empresa)[0]}
