"""Borra el archivo del storage cuando se borra el adjunto (también en cascada). Si falla, la excepción
revierte el delete: mejor abortar que dejar el archivo huérfano (mismo criterio que tar_adjuntos)."""
import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import AdjuntoMensaje

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=AdjuntoMensaje, dispatch_uid='mje_mensajes.borrar_archivo')
def borrar_archivo(sender, instance, **kwargs):
    if not instance.archivo:
        return
    try:
        instance.archivo.delete(save=False)
    except Exception:
        logger.exception('No se pudo borrar el archivo %s', instance.archivo.name)
        raise
