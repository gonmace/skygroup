"""WebSocket del chat. TransactionTestCase: el consumer usa threads de BD (database_sync_to_async) y los
avisos salen en on_commit."""
from unittest import mock

from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.test import TransactionTestCase, override_settings

from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from proyectos.models import Proyecto

from . import servicios
from .routing import websocket_urlpatterns


@override_settings(
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ChatWebSocketTests(TransactionTestCase):
    def setUp(self):
        self.a = crear_empresa(nombre='A', slug='emp-a', modulos=['msj'])
        self.b = crear_empresa(nombre='B', slug='emp-b', modulos=['msj'])
        self.ana = User.objects.create_user('ana@example.com', 'x')
        self.beto = User.objects.create_user('beto@example.com', 'x')
        self.cami = User.objects.create_user('cami@example.com', 'x')
        self.m = {}
        for u in (self.ana, self.beto, self.cami):
            self.m[u.pk] = agregar_miembro(u, self.a, rol_por_base(self.a, RolBase.MIEMBRO))
        self.p = Proyecto.objects.create(empresa=self.a, nombre='Secreto', codigo='S')
        self.p.equipo.add(self.m[self.ana.pk], self.m[self.beto.pk])   # cami queda fuera del proyecto
        self.app = URLRouter(websocket_urlpatterns)

    def com(self, slug, user):
        c = WebsocketCommunicator(self.app, f'/ws/empresa/{slug}/mensajes/')
        c.scope['user'] = user
        return c

    async def conectar(self, user, slug='emp-a'):
        c = self.com(slug, user)
        ok, _ = await c.connect()
        self.assertTrue(ok)
        self.assertEqual((await c.receive_json_from())['tipo'], 'resumen')
        return c

    async def test_anonimo_y_no_miembro_son_rechazados(self):
        ok, codigo = await self.com('emp-a', AnonymousUser()).connect()
        self.assertEqual((ok, codigo), (False, 4401))
        ok, codigo = await self.com('emp-b', self.ana).connect()   # ana solo pertenece a A
        self.assertEqual((ok, codigo), (False, 4403))

    async def test_modulo_apagado_o_persona_sin_acceso_es_rechazada(self):
        from cuentas.models import AccesoModulo
        from empresas.models import Empresa
        await database_sync_to_async(lambda: AccesoModulo.objects.create(
            membresia=self.m[self.cami.pk], modulo='msj', habilitado=False))()
        ok, codigo = await self.com('emp-a', self.cami).connect()     # el módulo está deshabilitado para cami
        self.assertEqual((ok, codigo), (False, 4403))
        await database_sync_to_async(lambda: Empresa.objects.filter(pk=self.a.pk).update(modulos=['tar']))()
        from django.core.cache import cache
        cache.clear()
        ok, codigo = await self.com('emp-a', self.ana).connect()      # la empresa ya no tiene el módulo
        self.assertEqual((ok, codigo), (False, 4403))

    async def test_al_conectar_recibe_el_resumen_de_no_leidos(self):
        gen = await database_sync_to_async(lambda: servicios.general(self.a))()
        await database_sync_to_async(servicios.enviar)(gen, self.ana, 'hola')
        c = self.com('emp-a', self.beto)
        await c.connect()
        r = await c.receive_json_from()
        self.assertEqual((r['tipo'], r['total'], r['por_conv']), ('resumen', 1, {str(gen.pk): 1}))
        await c.disconnect()

    async def test_mensaje_nuevo_llega_a_quien_lo_ve_y_solo_a_el(self):
        proy = await database_sync_to_async(servicios.de_proyecto)(self.p)
        beto, cami = await self.conectar(self.beto), await self.conectar(self.cami)
        msg = await database_sync_to_async(servicios.enviar)(proy, self.ana, 'reservado')
        ev = await beto.receive_json_from()
        self.assertEqual((ev['tipo'], ev['conv'], ev['id'], ev['autor']), ('mensaje', proy.pk, msg.pk, self.ana.pk))
        self.assertTrue(await cami.receive_nothing(timeout=0.3))   # no ve el canal: ni siquiera el aviso
        await beto.disconnect(); await cami.disconnect()

    async def test_leer_avisa_a_las_otras_pestanas(self):
        gen = await database_sync_to_async(lambda: servicios.general(self.a))()
        pestana1, pestana2 = await self.conectar(self.beto), await self.conectar(self.beto)
        await database_sync_to_async(servicios.enviar)(gen, self.ana, 'x')
        await pestana1.receive_json_from(); await pestana2.receive_json_from()
        await database_sync_to_async(servicios.marcar_leido)(gen, self.beto)
        self.assertEqual((await pestana2.receive_json_from())['tipo'], 'leida')
        await pestana1.disconnect(); await pestana2.disconnect()

    async def test_editar_y_borrar_avisan_a_los_participantes(self):
        gen = await database_sync_to_async(lambda: servicios.general(self.a))()
        msg = await database_sync_to_async(servicios.enviar)(gen, self.ana, 'v1')
        beto = await self.conectar(self.beto)
        await database_sync_to_async(servicios.editar)(msg, 'v2')
        self.assertEqual((await beto.receive_json_from())['tipo'], 'cambio')
        await beto.disconnect()

    async def test_un_fallo_del_canal_no_rompe_el_envio(self):
        gen = await database_sync_to_async(lambda: servicios.general(self.a))()
        with mock.patch('mje_mensajes.realtime.get_channel_layer', side_effect=RuntimeError('redis caído')), \
                self.assertLogs('mje_mensajes.realtime', level='WARNING'):
            msg = await database_sync_to_async(servicios.enviar)(gen, self.ana, 'sigue guardándose')
        self.assertIsNotNone(msg.pk)
