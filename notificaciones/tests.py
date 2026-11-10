from django.test import TestCase, override_settings

from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base

from .models import Notificacion
from .services import notificar, notificar_a_varios

AJUSTES = dict(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


@override_settings(**AJUSTES)
class NotificacionesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='A', slug='emp-a')
        cls.b = crear_empresa(nombre='B', slug='emp-b')
        cls.ana = User.objects.create_user('ana@example.com', 'x')
        cls.beto = User.objects.create_user('beto@example.com', 'x')
        for u in (cls.ana, cls.beto):
            agregar_miembro(u, cls.a, rol_por_base(cls.a, RolBase.MIEMBRO))
        agregar_miembro(cls.ana, cls.b, rol_por_base(cls.b, RolBase.MIEMBRO))

    def test_no_se_notifica_al_propio_actor(self):
        self.assertIsNone(notificar(self.ana, self.a, 'hola', actor=self.ana))
        self.assertEqual(Notificacion.objects.count(), 0)

    def test_url_externa_rechazada(self):
        for mala in ('//evil.com/x', 'https://evil.com', 'javascript:alert(1)', '/ok\nSet-Cookie: a=b'):
            with self.assertRaises(ValueError, msg=mala):
                notificar(self.ana, self.a, 'x', url=mala)

    def test_notificar_a_varios_omite_al_actor(self):
        creadas = notificar_a_varios([self.ana, self.beto], self.a, 'Nuevo ticket', actor=self.ana)
        self.assertEqual([n.destinatario for n in creadas], [self.beto])

    def test_lista_solo_las_propias_de_la_empresa_activa(self):
        notificar(self.ana, self.a, 'para ana en A')
        notificar(self.ana, self.b, 'para ana en B')
        notificar(self.beto, self.a, 'para beto en A')
        self.client.force_login(self.ana)
        html = self.client.get('/emp-a/notificaciones/').content.decode()
        self.assertIn('para ana en A', html)
        self.assertNotIn('para ana en B', html)
        self.assertNotIn('para beto en A', html)

    def test_contador_de_la_campana(self):
        notificar(self.ana, self.a, 'uno')
        notificar(self.ana, self.a, 'dos')
        n3 = notificar(self.ana, self.a, 'tres')
        Notificacion.objects.filter(pk=n3.pk).update(leida=True)
        self.client.force_login(self.ana)
        self.assertEqual(self.client.get('/emp-a/').context['notif_no_leidas'], 2)
        self.assertEqual(self.client.get('/emp-b/').context['notif_no_leidas'], 0)

    def test_leer_marca_y_redirige_con_prefijo_de_empresa(self):
        n = notificar(self.ana, self.a, 'ir', url='/config/miembros/')
        self.client.force_login(self.ana)
        r = self.client.post(f'/emp-a/notificaciones/{n.pk}/leer/')
        self.assertRedirects(r, '/emp-a/config/miembros/', fetch_redirect_response=False)
        n.refresh_from_db()
        self.assertTrue(n.leida)

    def test_no_se_puede_leer_la_de_otro_usuario(self):
        n = notificar(self.beto, self.a, 'privada')
        self.client.force_login(self.ana)
        self.assertEqual(self.client.post(f'/emp-a/notificaciones/{n.pk}/leer/').status_code, 404)
        n.refresh_from_db()
        self.assertFalse(n.leida)

    def test_leer_exige_post(self):
        n = notificar(self.ana, self.a, 'x')
        self.client.force_login(self.ana)
        self.assertEqual(self.client.get(f'/emp-a/notificaciones/{n.pk}/leer/').status_code, 405)

    def test_leer_todas_solo_afecta_a_la_empresa_activa(self):
        notificar(self.ana, self.a, 'A1')
        notificar(self.ana, self.b, 'B1')
        self.client.force_login(self.ana)
        self.client.post('/emp-a/notificaciones/leer-todas/')
        self.assertFalse(Notificacion.objects.filter(empresa=self.a, leida=False).exists())
        self.assertTrue(Notificacion.objects.filter(empresa=self.b, leida=False).exists())

    def test_anonimo_va_al_login(self):
        self.assertEqual(self.client.get('/emp-a/notificaciones/').status_code, 302)

    def test_filtro_sin_leer(self):
        notificar(self.ana, self.a, 'pendiente')
        n = notificar(self.ana, self.a, 'vieja')
        Notificacion.objects.filter(pk=n.pk).update(leida=True)
        self.client.force_login(self.ana)
        html = self.client.get('/emp-a/notificaciones/?filtro=no_leidas').content.decode()
        self.assertIn('pendiente', html)
        self.assertNotIn('vieja', html)


# ── WebSocket ────────────────────────────────────────────────────────────────
from channels.db import database_sync_to_async  # noqa: E402
from channels.routing import URLRouter  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402
from django.test import TransactionTestCase  # noqa: E402

from .routing import websocket_urlpatterns  # noqa: E402


@override_settings(
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class NotificacionesWebSocketTests(TransactionTestCase):
    """TransactionTestCase: el consumer usa threads de BD (database_sync_to_async)."""

    def setUp(self):
        self.a = crear_empresa(nombre='A', slug='emp-a')
        self.b = crear_empresa(nombre='B', slug='emp-b')
        self.ana = User.objects.create_user('ana@example.com', 'x')
        self.beto = User.objects.create_user('beto@example.com', 'x')
        for u in (self.ana, self.beto):
            agregar_miembro(u, self.a, rol_por_base(self.a, RolBase.MIEMBRO))
        self.app = URLRouter(websocket_urlpatterns)

    def com(self, slug, user):
        c = WebsocketCommunicator(self.app, f'/ws/empresa/{slug}/notificaciones/')
        c.scope['user'] = user
        return c

    async def test_miembro_recibe_su_notificacion_en_vivo(self):
        c = self.com('emp-a', self.ana)
        conectado, _ = await c.connect()
        self.assertTrue(conectado)
        await database_sync_to_async(notificar)(self.ana, self.a, 'Nuevo ticket', url='/tareas/1/')
        msg = await c.receive_json_from()
        self.assertEqual((msg['mensaje'], msg['url'], msg['no_leidas']), ('Nuevo ticket', '/tareas/1/', 1))
        await c.disconnect()

    async def test_no_recibe_las_de_otro_usuario_ni_otra_empresa(self):
        c = self.com('emp-a', self.ana)
        await c.connect()
        await database_sync_to_async(notificar)(self.beto, self.a, 'para beto')
        await database_sync_to_async(notificar)(self.ana, self.b, 'otra empresa')
        self.assertTrue(await c.receive_nothing(timeout=0.3))
        await c.disconnect()

    async def test_anonimo_es_rechazado(self):
        from django.contrib.auth.models import AnonymousUser
        c = self.com('emp-a', AnonymousUser())
        conectado, codigo = await c.connect()
        self.assertFalse(conectado)
        self.assertEqual(codigo, 4401)

    async def test_no_miembro_es_rechazado(self):
        c = self.com('emp-b', self.beto)  # beto solo pertenece a A
        conectado, codigo = await c.connect()
        self.assertFalse(conectado)
        self.assertEqual(codigo, 4403)

    async def test_el_administrador_de_sistema_sin_membresia_conecta_pero_no_el_de_otra_empresa(self):
        def crear():
            adm = User.objects.create_user('adm@example.com', 'x')
            adm.empresas_administradas.add(self.a)
            return adm
        adm = await database_sync_to_async(crear)()
        conectado, _ = await self.com('emp-a', adm).connect()
        self.assertTrue(conectado)
        conectado, codigo = await self.com('emp-b', adm).connect()   # administra A, no B
        self.assertEqual((conectado, codigo), (False, 4403))

    async def test_empresa_inactiva_o_inexistente_es_rechazada(self):
        await database_sync_to_async(lambda: self.a.__class__.objects.filter(pk=self.a.pk).update(activa=False))()
        from django.core.cache import cache
        cache.clear()
        for slug in ('emp-a', 'no-existe'):
            conectado, codigo = await self.com(slug, self.ana).connect()
            self.assertFalse(conectado, slug)
            self.assertEqual(codigo, 4403)

    async def test_un_fallo_del_canal_no_rompe_notificar(self):
        from unittest import mock
        for falla in (
            mock.patch('notificaciones.consumers.get_channel_layer', side_effect=RuntimeError('config mala')),
            mock.patch('channels.layers.InMemoryChannelLayer.group_send', side_effect=ConnectionError('redis caído')),
        ):
            with falla, self.assertLogs('notificaciones.consumers', level='WARNING'):
                n = await database_sync_to_async(notificar)(self.ana, self.a, 'sigue funcionando')
            self.assertIsNotNone(n)
            self.assertTrue(await database_sync_to_async(Notificacion.objects.filter(pk=n.pk).exists)())
