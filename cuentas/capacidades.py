"""Registro central de capacidades y API única de permisos.

Cada app declara sus capacidades con `registrar()` (normalmente en `AppConfig.ready()`):

    registrar('tar', {
        'tar.tickets.create': ('Crear tickets', {RolBase.COORDINADOR, RolBase.MIEMBRO}),
        'cuentas.usuarios.manage': ('Gestionar miembros', {RolBase.COORDINADOR}, {'empresa': True}),
    })

El tercer elemento opcional `{'empresa': True}` marca una capacidad de ámbito empresa: un
Coordinador cuya membresía tiene `contratista` (Coordinador acotado) no la recibe por rol,
solo por excepción de persona. Los demás roles con contratista (Ejecutor, Observador…) no se acotan.

Resolución de `tiene_capacidad(user, cap, empresa)`:
  superusuario → sí
  sin membresía activa en la empresa y sin administrarla → no
  administrador de sistema de la empresa (User.empresas_administradas, se define en Plataforma) → suma las
    capacidades de ámbito empresa; las de cada módulo solo las tiene si además es miembro
  excepción por persona (UsuarioPermiso) → su valor
  excepción del rol de la empresa (RolPermiso) → su valor
  default del rol base declarado en código

En BD solo se guardan las DIFERENCIAS respecto a los defaults. El conjunto efectivo de
cada rol se cachea (Redis) y se invalida al editar la matriz.
"""
from dataclasses import dataclass
from functools import wraps

from django.core.cache import cache
from django.core.exceptions import PermissionDenied

from .roles import RolBase

CACHE_KEY = 'caps:rol:{}'
CACHE_TTL = 600


@dataclass(frozen=True)
class Capacidad:
    clave: str
    etiqueta: str
    modulo: str
    roles_default: frozenset
    solo_empresa: bool = False


_REGISTRO = {}


def registrar(modulo, definiciones):
    """`definiciones`: {clave: (etiqueta, roles por defecto[, {'empresa': True}])}."""
    for clave, (etiqueta, roles, *opciones) in definiciones.items():
        if not clave.startswith(f'{modulo}.'):
            raise ValueError(f'La capacidad «{clave}» debe empezar con «{modulo}.»')
        solo_empresa = bool(opciones and opciones[0].get('empresa'))
        _REGISTRO[clave] = Capacidad(clave, etiqueta, modulo, frozenset(str(r) for r in roles), solo_empresa)


def todas():
    return dict(_REGISTRO)


def claves():
    return frozenset(_REGISTRO)


def agrupadas_por_modulo():
    grupos = {}
    for cap in sorted(_REGISTRO.values(), key=lambda c: c.clave):
        grupos.setdefault(cap.modulo, []).append(cap)
    return grupos


# ── Conjunto efectivo por rol de empresa ──────────────────────────────────────

def _conjunto_rol(rol_empresa):
    """Capacidades efectivas de un RolEmpresa: defaults del rol base + diferencias de BD."""
    key = CACHE_KEY.format(rol_empresa.pk)
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return cached
    efectivo = {c.clave for c in _REGISTRO.values() if str(rol_empresa.rol_base) in c.roles_default}
    for clave, habilitado in rol_empresa.permisos.values_list('capacidad', 'habilitado'):
        if habilitado:
            efectivo.add(clave)
        else:
            efectivo.discard(clave)
    efectivo = frozenset(efectivo & set(_REGISTRO))
    try:
        cache.set(key, efectivo, CACHE_TTL)
    except Exception:
        pass
    return efectivo


def invalidar_rol(rol_empresa_id):
    try:
        cache.delete(CACHE_KEY.format(rol_empresa_id))
    except Exception:
        pass


def _empresa_id(user, empresa):
    if empresa is not None:
        return getattr(empresa, 'pk', empresa)
    return user.__dict__.get('_empresa_activa_id')


def _membresia(user, empresa_id):
    """Membresía activa del usuario en la empresa, memoizada en el objeto `user`."""
    memo = user.__dict__.setdefault('_membresias', {})
    if empresa_id not in memo:
        from .models import Membresia
        memo[empresa_id] = (
            Membresia.objects.select_related('rol')
            .filter(user=user, empresa_id=empresa_id, activa=True, empresa__activa=True)
            .first()
        )
    return memo[empresa_id]


def administra(user, empresa_id):
    """¿Es administrador de sistema de esa empresa activa? Se define en Plataforma (no es un cargo RACI);
    memoizado en el objeto `user`. El superusuario no lo necesita: lo puede todo."""
    if empresa_id is None:
        return False
    memo = user.__dict__.setdefault('_administra', {})
    if empresa_id not in memo:
        memo[empresa_id] = user.empresas_administradas.filter(pk=empresa_id, activa=True).exists()
    return memo[empresa_id]


def membresia_activa(user, empresa):
    """Membresía activa del usuario en la empresa (None si no tiene; el superusuario no necesita una)."""
    if user is None or not user.is_authenticated:
        return None
    return _membresia(user, getattr(empresa, 'pk', empresa))


def capacidades_de(user, empresa=None):
    """Conjunto (frozenset) de capacidades efectivas del usuario en la empresa."""
    if user is None or not user.is_authenticated:
        return frozenset()
    if user.is_superuser:
        return claves()
    eid = _empresa_id(user, empresa)
    if eid is None:
        return frozenset()
    memo = user.__dict__.setdefault('_caps', {})
    if eid not in memo:
        membresia = _membresia(user, eid)
        admin = administra(user, eid)
        if membresia is None and not admin:
            memo[eid] = frozenset()
        elif membresia is None:   # administrador de sistema sin membresía: solo gestión de la empresa
            memo[eid] = frozenset(c for c, cap in _REGISTRO.items() if cap.solo_empresa)
        else:
            efectivo = set(_conjunto_rol(membresia.rol))
            acotado = (membresia.contratista_id is not None
                       and str(membresia.rol.rol_base) == str(RolBase.COORDINADOR))
            for acceso in membresia.accesos.select_related('rol_override'):
                prefijo = f'{acceso.modulo}.'
                efectivo = {c for c in efectivo if not c.startswith(prefijo)}
                if acceso.habilitado:
                    rol = acceso.rol_override or membresia.rol
                    efectivo |= {c for c in _conjunto_rol(rol) if c.startswith(prefijo)}
            if acotado:  # Coordinador acotado a su contratista: sin capacidades de ámbito empresa
                efectivo = {c for c in efectivo if c in _REGISTRO and not _REGISTRO[c].solo_empresa}
            if admin:   # administrador de sistema que además es miembro: suma la gestión de la empresa
                efectivo |= {c for c, cap in _REGISTRO.items() if cap.solo_empresa}
            for clave, habilitado in membresia.excepciones.values_list('capacidad', 'habilitado'):
                if habilitado:
                    efectivo.add(clave)
                else:
                    efectivo.discard(clave)
            memo[eid] = frozenset(efectivo & set(_REGISTRO))
    return memo[eid]


def tiene_capacidad(user, clave, empresa=None):
    if clave not in _REGISTRO:
        raise KeyError(f'Capacidad no registrada: {clave}')
    return clave in capacidades_de(user, empresa)


def usuarios_con_capacidad(empresa, clave):
    """Usuarios activos con membresía en `empresa` que tienen la capacidad (sin superusuarios)."""
    from .models import Membresia
    miembros = Membresia.objects.filter(empresa=empresa, activa=True, user__is_active=True).select_related('rol', 'user')
    return [m.user for m in miembros if clave in capacidades_de(m.user, empresa)]


def requiere_capacidad(clave):
    """Decorador de vistas: exige la capacidad en la empresa activa del request."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            empresa = getattr(request, 'empresa', None)
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path())
            if not tiene_capacidad(request.user, clave, empresa):
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador


class CapacidadRequeridaMixin:
    """Mixin para vistas basadas en clases. Definir `capacidad_requerida = 'mod.cap'`."""
    capacidad_requerida = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        if self.capacidad_requerida and not tiene_capacidad(
            request.user, self.capacidad_requerida, getattr(request, 'empresa', None)
        ):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
