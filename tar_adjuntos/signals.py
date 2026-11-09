"""post_delete (no override de delete()): corre también en los borrados por cascada (borrar un
mensaje o un ticket). Si borrar el archivo falla (almacenamiento caído), la excepción revierte
TODO el delete: mejor abortar que dejar el archivo huérfano con la fila ya borrada."""
import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Adjunto

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Adjunto, dispatch_uid='tar_adjuntos.borrar_archivo')
def borrar_archivo(sender, instance, **kwargs):
    if not instance.archivo:
        return
    try:
        instance.archivo.delete(save=False)
    except Exception:
        logger.exception('No se pudo borrar el archivo %s', instance.archivo.name)
        raise
