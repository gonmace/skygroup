"""Push en tiempo real de la campana: un grupo por (empresa, usuario)."""
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer

from empresas.tenancy import empresa_por_slug, es_miembro


def grupo(empresa_id, user_id):
    return f'notif.{empresa_id}.{user_id}'


def _puede_recibir(user, empresa):
    """Miembro, o administrador de sistema de la empresa (puede entrar a sus pantallas aunque no sea miembro)."""
    from cuentas.capacidades import administra
    return es_miembro(user, empresa) or administra(user, empresa.pk)


class NotificacionesConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            return await self.close(code=4401)
        empresa = await database_sync_to_async(empresa_por_slug)(self.scope['url_route']['kwargs']['slug'])
        permitido = empresa is not None and empresa.activa and (
            user.is_superuser or await database_sync_to_async(_puede_recibir)(user, empresa)
        )
        if not permitido:
            return await self.close(code=4403)
        self.grupo = grupo(empresa.pk, user.pk)
        await self.channel_layer.group_add(self.grupo, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if getattr(self, 'grupo', None):
            await self.channel_layer.group_discard(self.grupo, self.channel_name)

    async def notificacion(self, event):
        await self.send_json({k: event[k] for k in ('id', 'mensaje', 'url', 'no_leidas')})


def empujar_notificacion(notif):
    """Envía el aviso al grupo del destinatario. Un fallo del canal (Redis caído, config mala)
    nunca debe romper la operación que notifica: el aviso ya está guardado en la BD."""
    import logging

    from .models import Notificacion
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        no_leidas = Notificacion.objects.filter(
            destinatario_id=notif.destinatario_id, empresa_id=notif.empresa_id, leida=False,
        ).count()
        async_to_sync(layer.group_send)(grupo(notif.empresa_id, notif.destinatario_id), {
            'type': 'notificacion', 'id': notif.pk, 'mensaje': notif.mensaje, 'url': notif.url,
            'no_leidas': no_leidas,
        })
    except Exception:
        logging.getLogger(__name__).warning('No se pudo empujar la notificación %s', notif.pk, exc_info=True)
