"""Operaciones de alto nivel sobre empresas y membresías."""
from django.db import transaction

from empresas.models import Empresa

from .models import Membresia, RolEmpresa, RolPermiso
from .roles import NOMBRE_INICIAL, RolBase


def sembrar_roles(empresa, plantilla=None):
    """Crea los roles de la empresa. Sin plantilla: uno por rol base con su nombre RACI inicial.
    Con plantilla (otra empresa): copia nombres, orden y excepciones de su matriz."""
    if plantilla is None:
        for orden, rol in enumerate(RolBase):
            RolEmpresa.objects.get_or_create(
                empresa=empresa, nombre=NOMBRE_INICIAL[rol.value],
                defaults={'rol_base': rol.value, 'orden': orden},
            )
        return
    for origen in plantilla.roles.all():
        nuevo, _ = RolEmpresa.objects.get_or_create(
            empresa=empresa, nombre=origen.nombre,
            defaults={'rol_base': origen.rol_base, 'orden': origen.orden,
                      'descripcion': origen.descripcion, 'activo': origen.activo},
        )
        RolPermiso.objects.bulk_create(
            [RolPermiso(rol_empresa=nuevo, capacidad=p.capacidad, habilitado=p.habilitado)
             for p in origen.permisos.all()],
            ignore_conflicts=True,
        )


@transaction.atomic
def crear_empresa(*, plantilla=None, **campos):
    """Empresa lista para usar: validada y con sus roles sembrados."""
    empresa = Empresa(**campos)
    empresa.full_clean()
    empresa.save()
    sembrar_roles(empresa, plantilla)
    return empresa


def rol_por_base(empresa, rol_base):
    return empresa.roles.filter(rol_base=rol_base, activo=True).order_by('orden').first()


@transaction.atomic
def agregar_miembro(user, empresa, rol, contratista=None, sede=None):
    """Alta (o reactivación) de `user` en `empresa` con `rol` (RolEmpresa de esa empresa) y,
    opcionalmente, el `contratista` (de esa empresa) al que pertenece."""
    defaults = {'rol': rol, 'activa': True}
    if contratista is not None:  # reactivar sin indicarlo no debe borrar el contratista que ya tenía
        defaults['contratista'] = contratista
    if sede is not None:  # igual que el contratista: reactivar no borra la sede que ya tenía
        defaults['sede'] = sede
    membresia, _ = Membresia.objects.update_or_create(user=user, empresa=empresa, defaults=defaults)
    membresia.full_clean()
    user.__dict__.pop('_membresias', None)
    user.__dict__.pop('_caps', None)
    return membresia
