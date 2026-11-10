from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from empresas.tenancy import empresa_por_slug, es_miembro

from . import realtime


class TableroConsumer(AsyncJsonWebsocketConsumer):
    """Un socket por pestaña. Se une al grupo de tablero DE LA EMPRESA de la URL y, opcionalmente, al de
    un ticket puntual (validando visibilidad antes de unirse). Exige sesión, empresa activa con el
    módulo Tareas habilitado y membresía (o superusuario)."""

    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            return await self.close(code=4401)
        self.empresa = await database_sync_to_async(self._empresa_permitida)(user, self.scope['url_route']['kwargs']['slug'])
        if self.empresa is None:
            return await self.close(code=4403)
        self.grupos = {realtime.grupo_tablero(self.empresa.pk)}
        await self.channel_layer.group_add(realtime.grupo_tablero(self.empresa.pk), self.channel_name)
        await self.accept()

    @staticmethod
    def _empresa_permitida(user, slug):
        empresa = empresa_por_slug(slug)
        if empresa is None or not empresa.activa or not empresa.tiene_modulo('tar'):
            return None
        from cuentas.capacidades import lee_modulo_como_admin   # el administrador de sistema ve el tablero en vivo
        permitido = user.is_superuser or es_miembro(user, empresa) or lee_modulo_como_admin(user, empresa, 'tar')
        return empresa if permitido else None

    async def disconnect(self, code):
        for grupo in getattr(self, 'grupos', ()):
            await self.channel_layer.group_discard(grupo, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get('action') != 'subscribe_ticket':
            return
        ticket_id = content.get('id')
        if not isinstance(ticket_id, int):
            return
        if not await database_sync_to_async(self._puede_ver)(self.scope['user'], ticket_id):
            return
        grupo = realtime.grupo_ticket(ticket_id)
        self.grupos.add(grupo)
        await self.channel_layer.group_add(grupo, self.channel_name)

    def _puede_ver(self, user, ticket_id):
        from . import servicios
        from .models import Ticket
        ticket = Ticket.objects.filter(pk=ticket_id, empresa_id=self.empresa.pk).first()
        return ticket is not None and servicios.puede_ver(user, ticket)

    # Handlers de grupo (los llama group_send desde realtime.py)
    async def tablero_cambio(self, event):
        await self.send_json({'type': 'board.changed', 'ticket_id': event.get('ticket_id')})

    async def ticket_cambio(self, event):
        await self.send_json({'type': 'ticket.changed', 'ticket_id': event.get('ticket_id')})

    async def comentario_nuevo(self, event):
        await self.send_json({'type': 'comment.new', 'ticket_id': event.get('ticket_id')})
