from unittest import mock

from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db import transaction
from django.test import TransactionTestCase, override_settings

from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base

from .models import Asignacion, Comentario, Ticket
from .routing import websocket_urlpatterns


@override_settings(
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class TableroEnVivoTests(TransactionTestCase):
    """TransactionTestCase: los avisos salen en on_commit y el consumer usa threads de BD."""

    def setUp(self):
        cache.clear()
        self.a = crear_empresa(nombre='Embol', slug='embol', modulos=['tar'])
        self.b = crear_empresa(nombre='Otra', slug='otra', modulos=['tar'])
        self.sin_tar = crear_empresa(nombre='Sin', slug='sintar', modulos=['reg'])
        self.director = self.usuario('dir@example.com', self.a, RolBase.COORDINADOR)
        self.ejec = self.usuario('ejec@example.com', self.a, RolBase.MIEMBRO)
        self.ejec2 = self.usuario('ejec2@example.com', self.a, RolBase.MIEMBRO)
        self.director_b = self.usuario('dirb@example.com', self.b, RolBase.COORDINADOR)
        self.app = URLRouter(websocket_urlpatterns)

    def usuario(self, email, empresa, rol):
        u = User.objects.create_user(email, 'x')
        agregar_miembro(u, empresa, rol_por_base(empresa, rol))
        return u

    def com(self, slug, user):
        c = WebsocketCommunicator(self.app, f'/ws/empresa/{slug}/tareas/')
        c.scope['user'] = user
        return c

    async def conectar(self, slug, user):
        c = self.com(slug, user)
        ok, _ = await c.connect()
        self.assertTrue(ok)
        return c

    def crear_ticket(self, empresa=None, creador=None):
        return Ticket.objects.create(empresa=empresa or self.a, titulo='T', solicitante='C', creador=creador or self.director)

    async def recibir_todo(self, c, espera=0.3):
        """Todos los mensajes que llegan en `espera` segundos."""
        mensajes = []
        while not await c.receive_nothing(timeout=espera):
            mensajes.append(await c.receive_json_from())
        return mensajes

    # ── Acceso ──
    async def test_acepta_a_un_miembro_y_a_un_superusuario(self):
        c = await self.conectar('embol', self.director)
        await c.disconnect()
        root = await database_sync_to_async(User.objects.create_superuser)('root@example.com', 'x')
        await (await self.conectar('embol', root)).disconnect()

    async def test_rechaza_anonimos_no_miembros_modulo_inactivo_e_inexistentes(self):
        casos = [('embol', AnonymousUser(), 4401), ('embol', self.director_b, 4403),
                 ('sintar', self.director, 4403), ('nada', self.director, 4403)]
        for slug, user, codigo in casos:
            ok, cod = await self.com(slug, user).connect()
            self.assertFalse(ok, slug)
            self.assertEqual(cod, codigo, slug)

    async def test_empresa_inactiva_es_rechazada(self):
        await database_sync_to_async(lambda: type(self.a).objects.filter(pk=self.a.pk).update(activa=False))()
        cache.clear()
        ok, cod = await self.com('embol', self.director).connect()
        self.assertEqual((ok, cod), (False, 4403))

    # ── Avisos ──
    async def test_un_cambio_en_el_ticket_avisa_al_tablero_de_su_empresa(self):
        c = await self.conectar('embol', self.ejec)
        t = await database_sync_to_async(self.crear_ticket)()
        msg = await c.receive_json_from()
        self.assertEqual((msg['type'], msg['ticket_id']), ('board.changed', t.pk))
        await c.disconnect()

    async def test_no_llegan_avisos_de_otra_empresa(self):
        c = await self.conectar('embol', self.ejec)
        await database_sync_to_async(self.crear_ticket)(self.b, self.director_b)
        self.assertTrue(await c.receive_nothing(timeout=0.3))
        await c.disconnect()

    async def test_los_avisos_se_agrupan_por_transaccion(self):
        c = await self.conectar('embol', self.ejec)

        def operacion():
            with transaction.atomic():
                t = self.crear_ticket()
                Asignacion.objects.create(ticket=t, user=self.ejec)
                t.recalcular_estado()          # varios saves del mismo ticket
                Comentario.objects.create(ticket=t, autor=self.director, texto='hola')
            return t

        await database_sync_to_async(operacion)()
        mensajes = await self.recibir_todo(c)
        # 1 por cambios del ticket + 1 por el comentario (nunca uno por cada save)
        self.assertEqual([m['type'] for m in mensajes], ['board.changed', 'board.changed'])
        await c.disconnect()

    async def test_nada_sale_antes_del_commit_ni_si_se_revierte(self):
        c = await self.conectar('embol', self.ejec)

        def operacion():
            try:
                with transaction.atomic():
                    self.crear_ticket()
                    raise RuntimeError('rollback')
            except RuntimeError:
                pass

        await database_sync_to_async(operacion)()
        self.assertTrue(await c.receive_nothing(timeout=0.3))
        await c.disconnect()

    async def test_el_comentario_solo_llega_a_quien_se_suscribio_al_ticket(self):
        t = await database_sync_to_async(self.crear_ticket)()
        await database_sync_to_async(lambda: Asignacion.objects.create(ticket=t, user=self.ejec))()
        participante = await self.conectar('embol', self.ejec)
        ajeno = await self.conectar('embol', self.ejec2)       # miembro, pero no puede ver ese ticket
        for c, u in ((participante, self.ejec), (ajeno, self.ejec2)):
            await c.send_json_to({'action': 'subscribe_ticket', 'id': t.pk})
        await self.recibir_todo(participante)
        await self.recibir_todo(ajeno)

        await database_sync_to_async(lambda: Comentario.objects.create(ticket=t, autor=self.director, texto='x'))()
        tipos_part = sorted(m['type'] for m in await self.recibir_todo(participante))
        tipos_ajeno = sorted(m['type'] for m in await self.recibir_todo(ajeno))
        self.assertEqual(tipos_part, ['board.changed', 'comment.new'])
        self.assertEqual(tipos_ajeno, ['board.changed'])   # el contador del tablero, pero no el chat
        await participante.disconnect()
        await ajeno.disconnect()

    async def test_suscripcion_con_datos_invalidos_se_ignora(self):
        c = await self.conectar('embol', self.ejec)
        t = await database_sync_to_async(self.crear_ticket)(self.b, self.director_b)   # de otra empresa
        for payload in ({'action': 'subscribe_ticket', 'id': 'x'}, {'action': 'subscribe_ticket', 'id': t.pk},
                        {'action': 'otra-cosa'}):
            await c.send_json_to(payload)
        self.assertTrue(await c.receive_nothing(timeout=0.3))
        await c.disconnect()

    async def test_un_fallo_del_canal_no_rompe_la_operacion(self):
        with mock.patch('tar_tickets.realtime.get_channel_layer', side_effect=RuntimeError('redis caído')):
            t = await database_sync_to_async(self.crear_ticket)()
        self.assertIsNotNone(t.pk)

    async def test_borrar_un_ticket_tambien_avisa(self):
        t = await database_sync_to_async(self.crear_ticket)()
        c = await self.conectar('embol', self.ejec)
        await database_sync_to_async(t.delete)()
        msg = await c.receive_json_from()
        self.assertEqual(msg['type'], 'board.changed')
        await c.disconnect()
