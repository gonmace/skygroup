from datetime import datetime

from django.utils import timezone

from cuentas.capacidades import membresia_activa, tiene_capacidad
from cuentas.roles import RolBase

from .estado import estado_del_dia
from .models import Jornada
from .servicios import lleva_jornada


def jornada_hoy(request):
    """Indicador de la tarjeta del módulo en el inicio: estado de la jornada de hoy de quien navega. Solo para
    Ejecutores (nivel de acceso base) de una empresa con Jornadas, que fichan (capacidad `jor.fichar` y perfil
    activo). Una consulta cuando ya fichó hoy."""
    user = getattr(request, 'user', None)
    empresa = getattr(request, 'empresa', None)
    if not user or not user.is_authenticated or empresa is None or not empresa.tiene_modulo('jor'):
        return {}
    if not tiene_capacidad(user, 'jor.fichar', empresa) or not lleva_jornada(user, empresa):
        return {}
    m = membresia_activa(user, empresa)
    if m is None or m.rol.rol_base != RolBase.MIEMBRO:
        return {}
    ini = timezone.make_aware(datetime.combine(timezone.localdate(), datetime.min.time()))
    hoy = Jornada.objects.filter(empresa=empresa, perfil__membresia__user=user, perfil__activo=True, inicio__gte=ini)
    estado, jornada = estado_del_dia(hoy)
    if jornada is None:
        from jor_empleados.models import Perfil
        # Sin perfil todavía (nunca abrió «Mi jornada») cuenta como activo; solo se oculta si fue desactivado.
        if Perfil.objects.filter(membresia__user=user, membresia__empresa=empresa, activo=False).exists():
            return {}
    return {'jornada_estado': estado, 'jornada_hoy': jornada}
