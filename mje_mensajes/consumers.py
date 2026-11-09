"""WebSocket del chat: empuja avisos a la persona; el envío y la lectura van por HTTP (CSRF, multipart)."""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from cuentas.capacidades import tiene_capacidad
from empresas.tenancy import empresa_por_slug, es_miembro

from . import servicios
from .realtime import grupo_usuario


class MensajeriaConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            return await self.close(code=4401)
        empresa = await database_sync_to_async(empresa_por_slug)(self.scope['url_route']['kwargs']['slug'])
        permitido = empresa is not None and empresa.activa and (
            user.is_superuser or await database_sync_to_async(es_miembro)(user, empresa))
        # El chat es un módulo: empresa con `msj` activo y persona con acceso (no deshabilitado por AccesoModulo).
        permitido = permitido and empresa.tiene_modulo('msj') and await database_sync_to_async(tiene_capacidad)(
            user, 'msj.usar', empresa)
        if not permitido:
            return await self.close(code=4403)
        self.grupo = grupo_usuario(empresa.pk, user.pk)
        await self.channel_layer.group_add(self.grupo, self.channel_name)
        await self.accept()
        # Estado inicial (y tras cada reconexión): el cliente se pone al día sin esperar al siguiente mensaje.
        total, por_conv = await database_sync_to_async(servicios.no_leidos)(user, empresa)
        await self.send_json({'tipo': 'resumen', 'total': total, 'por_conv': {str(k): v for k, v in por_conv.items()}})

    async def disconnect(self, code):
        if getattr(self, 'grupo', None):
            await self.channel_layer.group_discard(self.grupo, self.channel_name)

    async def mensaje_nuevo(self, event):
        await self.send_json({'tipo': 'mensaje', 'conv': event['conv'], 'id': event['id'], 'autor': event['autor']})

    async def mensaje_cambio(self, event):
        await self.send_json({'tipo': 'cambio', 'conv': event['conv'], 'id': event['id']})

    async def conv_leida(self, event):
        await self.send_json({'tipo': 'leida', 'conv': event['conv']})
