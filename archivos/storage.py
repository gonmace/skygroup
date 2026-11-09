"""Storage híbrido local + S3/CDN, sobre la configuración `MediaStorageConfig` (admin).

La fuente de verdad es `archivos.MediaStorageConfig` (Admin → Almacenamiento de media / CDN):
modo, bucket, credenciales y URL de la CDN. Los cambios aplican sin reiniciar.

Con modo «local» todo vive en `MEDIA_ROOT` (igual que `ConfigurableMediaStorage`).
Con modo «s3» las ESCRITURAS nuevas van al bucket, pero las LECTURAS (`open`, `exists`,
`url`, `size`) siguen encontrando los archivos viejos que aún están en disco. Así se puede
activar el CDN sin migrar nada y mover los archivos después con `manage.py media_a_cdn`.

Dos storages:
- `HybridMediaStorage`   (STORAGES['default']) → público; URL directa (CDN si hay dominio).
- `HybridPrivateStorage` (STORAGES['privado']) → URLs firmadas y de corta vida en S3; en
  disco vive en `MEDIA_ROOT/privado/` (nginx NO lo sirve) y se entrega por la vista
  `archivos:privado`, que exige sesión y membresía de la empresa dueña del archivo.

Convención de rutas privadas: `<empresa_id>/<modulo>/...` (la vista de descarga valida
el primer segmento).
"""
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.files.storage import FileSystemStorage, Storage
from django.urls import reverse
from django.utils.deconstruct import deconstructible

from .models import get_media_config


def s3_activo():
    return get_media_config()['mode'] == 's3'


@deconstructible
class HybridStorage(Storage):
    privado = False

    def __init__(self):
        self._remote = None
        self._remote_para = None

    # ── Backends ────────────────────────────────────────────────────────────────
    @property
    def local(self):
        """Disco local. En modo local, URLs como las de `ConfigurableMediaStorage` (incluye CDN pull); en modo S3
        los archivos viejos se sirven desde el propio VPS (`MEDIA_URL`)."""
        cfg = get_media_config()
        raiz = Path(settings.MEDIA_ROOT)
        if self.privado:
            return FileSystemStorage(location=str(raiz / 'privado'), base_url=None)
        if cfg['mode'] == 'local':
            return build_backend(cfg)
        return FileSystemStorage(location=str(raiz), base_url=settings.MEDIA_URL)

    def _crear_remoto(self, cfg):
        return build_backend(cfg, privado=self.privado)

    @property
    def remote(self):
        """Storage S3 con la config vigente (None en modo local). Se reconstruye si cambia."""
        cfg = get_media_config()
        if cfg['mode'] != 's3':
            return None
        clave = tuple(sorted(cfg.items()))
        if clave != self._remote_para:
            self._remote = self._crear_remoto(cfg)
            self._remote_para = clave
        return self._remote

    # ── API de Storage ──────────────────────────────────────────────────────────
    def _save(self, name, content):
        destino = self.remote or self.local
        return destino._save(name, content)

    def exists(self, name):
        if self.local.exists(name):
            return True
        remote = self.remote
        return bool(remote and remote.exists(name))

    def _donde(self, name):
        """Backend que tiene el archivo: local primero, luego remoto."""
        local = self.local
        if local.exists(name):
            return local
        return self.remote or local

    def open(self, name, mode='rb'):
        return self._donde(name).open(name, mode)

    def delete(self, name):
        self.local.delete(name)
        remote = self.remote
        if remote is not None:
            remote.delete(name)

    def size(self, name):
        return self._donde(name).size(name)

    def get_modified_time(self, name):
        return self._donde(name).get_modified_time(name)

    def get_accessed_time(self, name):
        return self._donde(name).get_accessed_time(name)

    def get_created_time(self, name):
        return self._donde(name).get_created_time(name)

    def listdir(self, path):
        return self._donde(path).listdir(path)

    def path(self, name):
        """Solo existe para archivos en disco. El código que lo use está atado a disco
        local y debe migrar a `open()`; fallar acá es deliberado."""
        local = self.local
        if local.exists(name):
            return local.path(name)
        raise NotImplementedError(f'«{name}» no está en disco local; usa storage.open().')

    def url(self, name):
        if name is None:
            raise ValueError('El archivo no tiene nombre.')
        local = self.local
        if local.exists(name):
            return self._url_local(name, local)
        remote = self.remote
        if remote is not None:
            return remote.url(name)
        return self._url_local(name, local)

    def _url_local(self, name, local):
        return local.url(name)


@deconstructible
class HybridMediaStorage(HybridStorage):
    privado = False


@deconstructible
class HybridPrivateStorage(HybridStorage):
    privado = True

    def _url_local(self, name, local):
        return reverse('archivos:privado', kwargs={'ruta': name})

_DELEGATED = (
    'open', 'save', 'path', 'delete', 'exists', 'listdir', 'size', 'url',
    'get_accessed_time', 'get_created_time', 'get_modified_time',
    'get_available_name', 'get_alternative_name', 'get_valid_name', 'generate_filename',
    'is_name_available',
)


def _origin(url):
    p = urlparse(url)
    return f'{p.scheme}://{p.netloc}'


def bucket_origin(cfg, bucket=None):
    """Origen (scheme://host) de un bucket S3 (por defecto el público), o None en modo local."""
    if cfg['mode'] != 's3':
        return None
    bucket = bucket or cfg['s3_bucket']
    endpoint, region = cfg['s3_endpoint_url'], cfg['s3_region']
    if endpoint:
        ep = urlparse(endpoint)
        return f'{ep.scheme}://{ep.netloc}' if cfg['s3_path_style'] else f'{ep.scheme}://{bucket}.{ep.netloc}'
    return f'https://{bucket}.s3.{region}.amazonaws.com' if region else f'https://{bucket}.s3.amazonaws.com'


def media_origin(cfg):
    """Origen (scheme://host) desde el que el navegador cargará los archivos, o None si es el propio sitio."""
    if cfg['cdn_url']:
        return _origin(cfg['cdn_url'])
    return bucket_origin(cfg)


def build_backend(cfg, privado=False):
    """Backend de la config. `privado=True` (solo S3): URLs firmadas de corta vida, prefijo
    `privado/` y sin dominio CDN (los archivos privados no pasan por la caché pública)."""
    if cfg['mode'] == 's3':
        from storages.backends.s3 import S3Storage

        opts = {
            'bucket_name': cfg['s3_bucket'],
            'access_key': cfg['s3_access_key'],
            'secret_key': cfg['s3_secret_key'],
            'endpoint_url': cfg['s3_endpoint_url'] or None,
            'region_name': cfg['s3_region'] or None,
            'location': cfg['s3_location'].strip('/'),
            'querystring_auth': False,   # archivos públicos (URLs sin firma, cacheables por la CDN)
            'default_acl': None,
            'file_overwrite': False,
        }
        if cfg['s3_path_style']:
            opts['addressing_style'] = 'path'
        if privado:
            opts['querystring_auth'] = True
            opts['querystring_expire'] = getattr(settings, 'S3_URL_EXPIRE', 300)
            if cfg.get('s3_private_bucket'):
                # Bucket propio, sin acceso público ni CDN: solo se lee con URLs firmadas.
                opts['bucket_name'] = cfg['s3_private_bucket']
            else:
                # Mismo bucket que lo público: la política debe denegar lectura anónima de privado/*.
                opts['location'] = '/'.join(p for p in (opts['location'], 'privado') if p)
        elif cfg['cdn_url']:
            parsed = urlparse(cfg['cdn_url'])
            opts['custom_domain'] = parsed.netloc
            opts['url_protocol'] = f'{parsed.scheme}:'
        return S3Storage(**opts)

    base_url = settings.MEDIA_URL
    if cfg['cdn_url']:
        base_url = cfg['cdn_url'].rstrip('/') + settings.MEDIA_URL
    return FileSystemStorage(location=settings.MEDIA_ROOT, base_url=base_url)


class ConfigurableMediaStorage(Storage):
    """Storage por defecto: delega en disco local o en S3 según lo configurado en el admin.
    La configuración se relee (con caché) en cada operación: los cambios aplican sin reiniciar."""

    def __init__(self):
        self._built_for = None
        self._built = None

    def _backend(self):
        cfg = get_media_config()
        key = tuple(sorted(cfg.items()))
        if key != self._built_for:
            self._built = build_backend(cfg)
            self._built_for = key
        return self._built


def _delegate(name):
    def method(self, *args, **kwargs):
        return getattr(self._backend(), name)(*args, **kwargs)
    method.__name__ = name
    return method


for _name in _DELEGATED:
    setattr(ConfigurableMediaStorage, _name, _delegate(_name))
