"""Eventos en tiempo real (Channels) disparados desde código síncrono.

Un grupo de tablero POR EMPRESA (`tar.tablero.<empresa_id>`) y uno por ticket (`tar.ticket.<id>`). El
evento solo lleva ids, sin datos: el cliente reacciona volviendo a pedir el fragmento del tablero, que ya
filtra por empresa y visibilidad en el servidor — no hay fuga aunque el aviso llegue a alguien sin
acceso a ese ticket.

Los avisos salen DESPUÉS del commit (si salieran antes, el cliente podría releer datos viejos) y se
agrupan por transacción: mover un ticket toca varias filas, pero genera un solo aviso por destino.
Todo es best-effort: si el canal no está disponible, nunca rompe la operación.
"""
import logging
import threading

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

logger = logging.getLogger(__name__)
_local = threading.local()


def grupo_tablero(empresa_id):
    return f'tar.tablero.{empresa_id}'


def grupo_ticket(ticket_id):
    return f'tar.ticket.{ticket_id}'


def _pendientes():
    if not hasattr(_local, 'pendientes'):
        _local.pendientes = set()
    return _local.pendientes


def _enviar(destinos):
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        for grupo, mensaje in destinos:
            async_to_sync(layer.group_send)(grupo, mensaje)
    except Exception:
        logger.warning('No se pudo emitir el aviso en vivo', exc_info=True)


def _una_vez(clave, destinos):
    """Programa el envío tras el commit, una sola vez por transacción para la misma `clave`."""
    pendientes = _pendientes()
    if clave in pendientes:
        return
    pendientes.add(clave)

    def enviar():
        pendientes.discard(clave)
        _enviar(destinos)

    transaction.on_commit(enviar)


def tablero_cambio(empresa_id, ticket_id=None):
    """El tablero de la empresa cambió (y, si hay ticket, quien tenga abierto su detalle)."""
    if empresa_id is None:
        return
    destinos = [(grupo_tablero(empresa_id), {'type': 'tablero.cambio', 'ticket_id': ticket_id})]
    if ticket_id:
        destinos.append((grupo_ticket(ticket_id), {'type': 'ticket.cambio', 'ticket_id': ticket_id}))
    _una_vez(('tablero', empresa_id, ticket_id), destinos)


def comentario_nuevo(empresa_id, ticket_id):
    """Hay un mensaje nuevo en el seguimiento: el tablero actualiza su contador y quien tenga abierto el
    detalle lo agrega por AJAX (sin recargar, para no pisar lo que otro esté escribiendo)."""
    if empresa_id is None:
        return
    _una_vez(('comentario', empresa_id, ticket_id), [
        (grupo_tablero(empresa_id), {'type': 'tablero.cambio', 'ticket_id': ticket_id}),
        (grupo_ticket(ticket_id), {'type': 'comentario.nuevo', 'ticket_id': ticket_id}),
    ])
