"""Emite el aviso en vivo cuando cambia algo que se ve en el tablero o en el seguimiento."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from . import realtime
from .models import Asignacion, Comentario, Ticket


@receiver([post_save, post_delete], sender=Ticket, dispatch_uid='tar.ticket_en_vivo')
def _ticket(sender, instance, **kwargs):
    realtime.tablero_cambio(instance.empresa_id, instance.pk)


@receiver([post_save, post_delete], sender=Asignacion, dispatch_uid='tar.asignacion_en_vivo')
def _asignacion(sender, instance, **kwargs):
    realtime.tablero_cambio(instance.ticket.empresa_id, instance.ticket_id)


@receiver(post_save, sender=Comentario, dispatch_uid='tar.comentario_en_vivo')
def _comentario_guardado(sender, instance, created, **kwargs):
    if created:
        realtime.comentario_nuevo(instance.ticket.empresa_id, instance.ticket_id)


@receiver(post_delete, sender=Comentario, dispatch_uid='tar.comentario_borrado_en_vivo')
def _comentario_borrado(sender, instance, **kwargs):
    realtime.tablero_cambio(instance.ticket.empresa_id, instance.ticket_id)
