from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .capacidades import invalidar_rol
from .models import RolEmpresa, RolPermiso


@receiver([post_save, post_delete], sender=RolPermiso)
def _rol_permiso_cambio(sender, instance, **kwargs):
    invalidar_rol(instance.rol_empresa_id)


@receiver([post_save, post_delete], sender=RolEmpresa)
def _rol_empresa_cambio(sender, instance, **kwargs):
    cache.delete(f'rol_tonos:{instance.empresa_id}:{instance.rol_base}')   # tono del avatar (RolEmpresa.tono)
    # Cambiar el rol base cambia los defaults efectivos.
    invalidar_rol(instance.pk)
