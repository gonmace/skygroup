import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage, storages
from django.core.management import CommandError, call_command
from django.test import Client, TestCase, override_settings

from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base

from .models import MediaStorageConfig, TareaMigracionMedia, get_media_config
from .storage import ConfigurableMediaStorage, HybridStorage, media_origin

STORAGES_HIBRIDOS = {
    'default': {'BACKEND': 'archivos.storage.HybridMediaStorage'},
    'privado': {'BACKEND': 'archivos.storage.HybridPrivateStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
CACHE_LOCAL = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


class BaseMedia(TestCase):
    """MEDIA_ROOT temporal y un InMemoryStorage como «bucket» (sin red)."""

    def setUp(self):
        cache.clear()  # get_media_config() cachea; el rollback de TestCase no la invalida
        self.addCleanup(cache.clear)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.remotos = {}

        def crear_remoto(storage, cfg):
            return self.remotos.setdefault(storage.privado, InMemoryStorage(base_url=f'/bucket-{int(storage.privado)}/'))

        patcher = mock.patch.object(HybridStorage, '_crear_remoto', crear_remoto)
        patcher.start()
        self.addCleanup(patcher.stop)

    def con_settings(self, **extra):
        ctx = override_settings(MEDIA_ROOT=str(self.tmp), STORAGES=STORAGES_HIBRIDOS, CACHES=CACHE_LOCAL, **extra)
        ctx.enable()
        self.addCleanup(ctx.disable)

    def activar_s3(self):
        """Modo S3 como lo dejaría el admin (el bucket es un InMemoryStorage, sin red)."""
        MediaStorageConfig.objects.create(mode='s3', s3_bucket='b', s3_access_key='k', s3_secret_key='s')

    def poner_local(self, nombre, datos=b'hola', privado=False):
        ruta = self.tmp / ('privado' if privado else '') / nombre
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(datos)
        return ruta


class StorageHibridoTests(BaseMedia):
    def test_modo_local_escribe_en_disco(self):
        self.con_settings()
        nombre = storages['default'].save('a/x.txt', ContentFile(b'x'))
        self.assertTrue((self.tmp / nombre).exists())
        self.assertEqual(storages['default'].url(nombre), '/media/a/x.txt')

    def test_modo_s3_escribe_en_bucket_y_sigue_leyendo_lo_local(self):
        self.poner_local('viejo/f.txt', b'viejo')
        self.con_settings()
        self.activar_s3()
        st = storages['default']
        nuevo = st.save('nuevo/g.txt', ContentFile(b'nuevo'))
        self.assertFalse((self.tmp / nuevo).exists())          # fue al bucket
        self.assertTrue(self.remotos[False].exists(nuevo))
        self.assertEqual(st.open('viejo/f.txt').read(), b'viejo')  # lo viejo sigue en disco
        self.assertEqual(st.open(nuevo).read(), b'nuevo')
        self.assertEqual(st.url('viejo/f.txt'), '/media/viejo/f.txt')
        self.assertEqual(st.url(nuevo), f'/bucket-0/{nuevo}')
        self.assertTrue(st.exists('viejo/f.txt') and st.exists(nuevo))

    def test_nombres_no_colisionan_entre_disco_y_bucket(self):
        self.poner_local('dup.txt', b'local')
        self.con_settings()
        self.activar_s3()
        nombre = storages['default'].save('dup.txt', ContentFile(b'remoto'))
        self.assertNotEqual(nombre, 'dup.txt')

    def test_path_falla_para_archivos_remotos(self):
        self.con_settings()
        self.activar_s3()
        nombre = storages['default'].save('r.txt', ContentFile(b'r'))
        with self.assertRaises(NotImplementedError):
            storages['default'].path(nombre)

    def test_privado_local_va_por_la_vista(self):
        self.con_settings()
        nombre = storages['privado'].save('1/reg/f.jpg', ContentFile(b'x'))
        self.assertTrue((self.tmp / 'privado' / nombre).exists())
        self.assertEqual(storages['privado'].url(nombre), f'/archivos/privado/{nombre}')


class MediaACdnTests(BaseMedia):
    def setUp(self):
        super().setUp()
        self.con_settings()
        self.activar_s3()
        self.pub = self.poner_local('photos/a.jpg', b'AAAA')
        self.priv = self.poner_local('1/reg/b.jpg', b'BB', privado=True)

    def correr(self, *args):
        out = StringIO()
        call_command('media_a_cdn', *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_dry_run_no_sube_ni_borra(self):
        self.correr('--dry-run', '--borrar-local')
        self.assertFalse(self.remotos.get(False, InMemoryStorage()).exists('photos/a.jpg'))
        self.assertTrue(self.pub.exists())
        self.assertEqual(TareaMigracionMedia.objects.get().archivos_subidos, 2)

    def test_sube_sin_borrar_y_luego_borra_local(self):
        self.correr()
        self.assertTrue(self.remotos[False].exists('photos/a.jpg'))
        self.assertTrue(self.remotos[True].exists('1/reg/b.jpg'))
        self.assertTrue(self.pub.exists() and self.priv.exists())

        self.correr('--borrar-local')  # segunda pasada: omite lo ya subido y borra lo verificado
        t = TareaMigracionMedia.objects.first()
        self.assertEqual((t.archivos_subidos, t.archivos_omitidos, t.archivos_borrados), (0, 2, 2))
        self.assertFalse(self.pub.exists() or self.priv.exists())
        # y siguen visibles vía storage
        self.assertEqual(storages['default'].open('photos/a.jpg').read(), b'AAAA')
        self.assertEqual(storages['privado'].open('1/reg/b.jpg').read(), b'BB')

    def test_prefijo_y_antiguedad(self):
        self.correr('--prefijo', 'photos/')
        self.assertTrue(self.remotos[False].exists('photos/a.jpg'))
        self.assertFalse(self.remotos.get(True, InMemoryStorage()).exists('1/reg/b.jpg'))
        TareaMigracionMedia.objects.all().delete()
        self.correr('--antiguedad', '7d')  # archivos recién creados: no califican
        self.assertEqual(TareaMigracionMedia.objects.get().archivos_total, 0)

    def test_no_borra_si_la_verificacion_falla(self):
        with mock.patch('archivos.services._verificado', return_value=False):
            with self.assertRaises(CommandError):
                self.correr('--borrar-local')
        self.assertTrue(self.pub.exists() and self.priv.exists())
        self.assertEqual(TareaMigracionMedia.objects.get().estado, 'PARCIAL')

    def test_exige_modo_s3(self):
        MediaStorageConfig.objects.all().delete()  # vuelve al modo local por defecto
        with self.assertRaises(CommandError):
            self.correr()

    def test_rechaza_ejecucion_concurrente(self):
        TareaMigracionMedia.objects.create(estado='EN_CURSO')
        with self.assertRaises(CommandError):
            self.correr()


class SyncMediaTests(BaseMedia):
    def test_no_copia_los_privados_al_bucket_publico(self):
        self.con_settings()
        self.activar_s3()
        self.poner_local('photos/a.jpg', b'AAAA')
        self.poner_local('1/reg/b.jpg', b'BB', privado=True)
        publico = InMemoryStorage()   # sync_media usa ConfigurableMediaStorage._backend(): sin red
        with mock.patch.object(ConfigurableMediaStorage, '_backend', return_value=publico):
            call_command('sync_media', stdout=StringIO(), stderr=StringIO())
        self.assertTrue(publico.exists('photos/a.jpg'))
        self.assertFalse(publico.exists('privado/1/reg/b.jpg'))


class VistaPrivadaTests(BaseMedia):
    def setUp(self):
        super().setUp()
        self.con_settings(SECURE_SSL_REDIRECT=False)
        self.a = crear_empresa(nombre='A', slug='emp-a')
        self.b = crear_empresa(nombre='B', slug='emp-b')
        self.ua = User.objects.create_user('a@example.com', 'x')
        agregar_miembro(self.ua, self.a, rol_por_base(self.a, RolBase.MIEMBRO))
        self.poner_local(f'{self.a.pk}/demo/f.jpg', b'secreto', privado=True)

    def url(self, empresa_id=None):
        return f'/archivos/privado/{empresa_id or self.a.pk}/demo/f.jpg'

    def test_anonimo_redirige_a_login(self):
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    def test_miembro_descarga(self):
        self.client.force_login(self.ua)
        r = self.client.get(self.url())
        self.assertEqual(b''.join(r.streaming_content), b'secreto')

    def test_otra_empresa_no_ve_el_archivo(self):
        ub = User.objects.create_user('b@example.com', 'x')
        agregar_miembro(ub, self.b, rol_por_base(self.b, RolBase.MIEMBRO))
        self.client.force_login(ub)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_empresa_inactiva_no_descarga(self):
        self.a.activa = False
        self.a.save()
        self.client.force_login(self.ua)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_ruta_sin_empresa_o_traversal(self):
        self.client.force_login(self.ua)
        self.assertEqual(self.client.get('/archivos/privado/x/y.jpg').status_code, 404)
        self.assertEqual(self.client.get(f'/archivos/privado/{self.a.pk}/../../etc/passwd').status_code, 404)

    def test_superusuario_descarga_de_cualquiera(self):
        root = User.objects.create_superuser('root@example.com', 'x')
        self.client.force_login(root)
        self.assertEqual(self.client.get(self.url()).status_code, 200)


class BucketPrivadoTests(BaseMedia):
    """Los archivos privados no deben quedar bajo la política pública del bucket."""

    CFG = dict(mode='s3', s3_bucket='publico', s3_access_key='k', s3_secret_key='s',
               s3_location='media', cdn_url='https://cdn.example.com')

    def backend(self, privado, **extra):
        from .storage import build_backend
        return build_backend({**dict(MediaStorageConfig().as_dict(), **self.CFG), **extra}, privado=privado)

    def test_con_bucket_privado_propio(self):
        s3 = self.backend(True, s3_private_bucket='privado-solo')
        self.assertEqual(s3.bucket_name, 'privado-solo')
        self.assertTrue(s3.querystring_auth)
        self.assertFalse(s3.custom_domain)  # nunca por la CDN pública

    def test_sin_bucket_privado_usa_prefijo_y_firma(self):
        s3 = self.backend(True)
        self.assertEqual((s3.bucket_name, s3.location), ('publico', 'media/privado'))
        self.assertTrue(s3.querystring_auth)
        self.assertFalse(s3.custom_domain)

    def test_publico_sigue_sin_firma_y_con_cdn(self):
        s3 = self.backend(False, s3_private_bucket='privado-solo')
        self.assertEqual(s3.bucket_name, 'publico')
        self.assertFalse(s3.querystring_auth)
        self.assertEqual(s3.custom_domain, 'cdn.example.com')

    def test_csp_incluye_el_origen_del_bucket_privado(self):
        self.con_settings(SECURE_SSL_REDIRECT=False)
        MediaStorageConfig.objects.create(
            **{**self.CFG, 's3_endpoint_url': 'https://acct.r2.cloudflarestorage.com', 's3_private_bucket': 'privado-solo'})
        csp = self.client.get('/')['Content-Security-Policy']
        self.assertIn('https://privado-solo.acct.r2.cloudflarestorage.com', csp)
        self.assertIn('https://cdn.example.com', csp)


TEST_SETTINGS_CDN = dict(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'archivos.storage.ConfigurableMediaStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


@override_settings(**TEST_SETTINGS_CDN)
class MediaConfigTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_por_defecto_es_local_en_el_vps(self):
        cfg = get_media_config()
        self.assertEqual(cfg['mode'], 'local')
        storage = ConfigurableMediaStorage()
        self.assertEqual(storage.url('a/b.jpg'), '/media/a/b.jpg')
        self.assertIsNone(media_origin(cfg))

    def test_local_con_cdn_pull(self):
        MediaStorageConfig.objects.create(cdn_url='https://cdn.example.com/')
        storage = ConfigurableMediaStorage()
        self.assertEqual(storage.url('a.jpg'), 'https://cdn.example.com/media/a.jpg')

    def test_cambio_aplica_sin_reiniciar(self):
        storage = ConfigurableMediaStorage()
        self.assertEqual(storage.url('a.jpg'), '/media/a.jpg')
        MediaStorageConfig.objects.create(cdn_url='https://cdn.example.com')
        self.assertEqual(storage.url('a.jpg'), 'https://cdn.example.com/media/a.jpg')

    def test_s3_con_dominio_cdn(self):
        MediaStorageConfig.objects.create(
            mode='s3', s3_bucket='b', s3_access_key='k', s3_secret_key='s',
            s3_endpoint_url='https://acct.r2.cloudflarestorage.com', cdn_url='https://media.example.com',
        )
        storage = ConfigurableMediaStorage()
        self.assertEqual(storage.url('x/y.png'), 'https://media.example.com/x/y.png')

    def test_s3_exige_credenciales(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            MediaStorageConfig(mode='s3').full_clean()

    def test_singleton(self):
        MediaStorageConfig.objects.create(cdn_url='https://a.example.com')
        MediaStorageConfig(cdn_url='https://b.example.com').save()
        self.assertEqual(MediaStorageConfig.objects.count(), 1)
        self.assertEqual(MediaStorageConfig.objects.get().cdn_url, 'https://b.example.com')

    def test_guardar_archivo_local(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            storage = ConfigurableMediaStorage()
            name = storage.save('t.txt', ContentFile(b'hola'))
            self.assertTrue(storage.exists(name))
            storage.delete(name)

    def test_csp_incluye_origen_de_la_cdn(self):
        home = self.client.get('/')
        self.assertNotIn('cdn.example.com', home['Content-Security-Policy'])
        MediaStorageConfig.objects.create(cdn_url='https://cdn.example.com')
        response = self.client.get('/')
        csp = response['Content-Security-Policy']
        self.assertIn('img-src', csp)
        self.assertIn('https://cdn.example.com', csp)

    def test_admin_edita_la_configuracion(self):
        user = get_user_model().objects.create_superuser('b@example.com', 'pass-12345-xyz')
        client = Client()
        client.force_login(user)
        url = f'/{settings.ADMIN_URL}archivos/mediastorageconfig/add/'
        resp = client.post(url, {'mode': 'local', 'cdn_url': 'https://cdn.example.com', 's3_endpoint_url': '',
                                 's3_bucket': '', 's3_region': '', 's3_access_key': '', 's3_secret_key': '',
                                 's3_location': ''})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(get_media_config()['cdn_url'], 'https://cdn.example.com')
        # El listado redirige al único registro
        self.assertEqual(client.get(f'/{settings.ADMIN_URL}archivos/mediastorageconfig/').status_code, 302)
