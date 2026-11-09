"""Borrar una foto (o su registro) elimina también los archivos del almacenamiento. Si el almacenamiento falla,
la excepción revierte el borrado: mejor abortar que dejar archivos huérfanos con la fila ya borrada."""
import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Foto

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Foto, dispatch_uid='reg_fotos.borrar_archivos')
def borrar_archivos(sender, instance, **kwargs):
    for campo in (instance.imagen, instance.miniatura):
        if campo:
            try:
                campo.delete(save=False)
            except Exception:
                logger.exception('No se pudo borrar el archivo %s', campo.name)
                raise
