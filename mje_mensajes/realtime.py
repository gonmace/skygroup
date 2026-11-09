"""Avisos en vivo del chat (Channels), disparados desde código síncrono.

Un grupo POR PERSONA y empresa (`msj.user.<empresa_id>.<user_id>`): cada evento solo lleva ids, sin texto, y
se envía únicamente a quienes pueden ver la conversación, así que no hay fuga entre canales. El cliente
decide: si tiene esa conversación abierta pide los mensajes nuevos; si no, suma al contador de no leídos.
Salen DESPUÉS del commit y son best-effort: si el canal no está disponible nunca rompen el envío.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

logger = logging.getLogger(__name__)


def grupo_usuario(empresa_id, user_id):
    return f'msj.user.{empresa_id}.{user_id}'


def _enviar(destinos):
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        for grupo, evento in destinos:
            async_to_sync(layer.group_send)(grupo, evento)
    except Exception:
        logger.warning('No se pudo emitir el aviso del chat', exc_info=True)


def mensaje_nuevo(conv, msg, user_ids):
    evento = {'type': 'mensaje.nuevo', 'conv': conv.pk, 'id': msg.pk, 'autor': msg.autor_id}
    destinos = [(grupo_usuario(conv.empresa_id, uid), evento) for uid in user_ids]
    transaction.on_commit(lambda: _enviar(destinos))


def mensaje_cambio(conv, msg_id):
    """Un mensaje se editó o se borró: quien tenga la conversación abierta lo vuelve a pedir."""
    from .servicios import participantes
    evento = {'type': 'mensaje.cambio', 'conv': conv.pk, 'id': msg_id}
    destinos = [(grupo_usuario(conv.empresa_id, u.pk), evento) for u in participantes(conv)]
    transaction.on_commit(lambda: _enviar(destinos))


def leido(conv, user):
    """La persona leyó la conversación en una pestaña: las demás ponen su contador a cero."""
    evento = {'type': 'conv.leida', 'conv': conv.pk}
    transaction.on_commit(lambda: _enviar([(grupo_usuario(conv.empresa_id, user.pk), evento)]))
