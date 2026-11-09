"""Migración de media local → S3/CDN y estado del almacenamiento."""
import os
import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import storages
from django.utils import timezone



from .models import TareaMigracionMedia, get_media_config
from .storage import s3_activo

LOCK_HORAS = 6
OMITIR = {'.gitkeep', '.DS_Store'}


class MigracionError(Exception):
    """Precondición no cumplida (mensaje apto para mostrar)."""


def _raiz_publica():
    return Path(settings.MEDIA_ROOT)


def _archivos(raiz, excluir=None):
    """Itera (nombre_relativo, ruta_absoluta) bajo `raiz`, con separador '/'."""
    if not raiz.is_dir():
        return
    for base, dirs, files in os.walk(raiz):
        base = Path(base)
        if excluir is not None:
            dirs[:] = [d for d in dirs if base / d != excluir]
        for f in files:
            if f in OMITIR:
                continue
            ruta = base / f
            yield ruta.relative_to(raiz).as_posix(), ruta


def _candidatos(prefijo='', antiguedad_dias=0):
    """[(alias_storage, nombre, ruta)] de los archivos locales a mover."""
    limite = None
    if antiguedad_dias:
        limite = (timezone.now() - timedelta(days=antiguedad_dias)).timestamp()
    privada = _raiz_publica() / 'privado'
    origenes = [('default', _raiz_publica(), privada), ('privado', privada, None)]
    for alias, raiz, excluir in origenes:
        for nombre, ruta in _archivos(raiz, excluir):
            if prefijo and not nombre.startswith(prefijo):
                continue
            if limite is not None and ruta.stat().st_mtime > limite:
                continue
            yield alias, nombre, ruta


def tamano_local():
    """(cantidad, bytes) de archivos que siguen en disco."""
    n = total = 0
    for _alias, _nombre, ruta in _candidatos():
        n += 1
        total += ruta.stat().st_size
    return n, total


def estado_almacenamiento():
    """Datos para el panel de almacenamiento."""
    cfg = get_media_config()
    raiz = _raiz_publica()
    ref = raiz if raiz.exists() else Path(settings.BASE_DIR)
    uso = shutil.disk_usage(ref)
    archivos_locales, bytes_locales = tamano_local()
    ultima = TareaMigracionMedia.objects.first()
    return {
        'backend': 's3' if s3_activo() else 'local',
        'cdn_domain': cfg['cdn_url'],
        'bucket': cfg['s3_bucket'] if s3_activo() else '',
        'bucket_privado': cfg['s3_private_bucket'] if s3_activo() else '',
        'disco_total': uso.total,
        'disco_usado': uso.used,
        'disco_libre': uso.free,
        'disco_pct': round(100 * uso.used / uso.total, 1) if uso.total else 0,
        'umbral_pct': settings.DISK_ALERT_PERCENT,
        'alerta': bool(uso.total) and 100 * uso.used / uso.total >= settings.DISK_ALERT_PERCENT,
        'archivos_locales': archivos_locales,
        'bytes_locales': bytes_locales,
        'ultima_tarea': ultima,
    }


def _verificado(remote, nombre, ruta):
    """El objeto remoto existe y coincide en tamaño (y en MD5 si el ETag es simple)."""
    if not remote.exists(nombre) or remote.size(nombre) != ruta.stat().st_size:
        return False
    bucket = getattr(remote, 'bucket', None)
    if bucket is not None:
        import hashlib
        etag = bucket.Object(remote._normalize_name(nombre) if hasattr(remote, '_normalize_name') else nombre).e_tag.strip('"')
        if '-' not in etag:  # sin multipart: ETag == MD5
            md5 = hashlib.md5()
            with open(ruta, 'rb') as fh:
                for bloque in iter(lambda: fh.read(1024 * 1024), b''):
                    md5.update(bloque)
            return md5.hexdigest() == etag
    return True


def migrar_a_cdn(*, dry_run=False, prefijo='', borrar_local=False, antiguedad_dias=0,
                 usuario=None, log=lambda msg: None):
    """Sube a S3 lo que sigue en disco. Idempotente y reanudable: lo ya subido (mismo
    tamaño) se omite, y con `borrar_local` solo se borra lo verificado en el bucket."""
    if not s3_activo():
        raise MigracionError('El almacenamiento no está en modo S3: configúralo en Admin → Almacenamiento de media / CDN.')
    desde = timezone.now() - timedelta(hours=LOCK_HORAS)
    if TareaMigracionMedia.objects.filter(estado='EN_CURSO', iniciada__gte=desde).exists():
        raise MigracionError('Ya hay una migración en curso.')

    archivos = list(_candidatos(prefijo, antiguedad_dias))
    tarea = TareaMigracionMedia.objects.create(
        usuario=usuario, dry_run=dry_run, prefijo=prefijo, borrar_local=borrar_local,
        antiguedad_dias=antiguedad_dias, archivos_total=len(archivos),
        bytes_total=sum(r.stat().st_size for _a, _n, r in archivos),
    )
    errores = []
    try:
        for i, (alias, nombre, ruta) in enumerate(archivos, 1):
            remote = storages[alias].remote
            try:
                if dry_run:
                    log(f'[dry-run] {alias}:{nombre} ({ruta.stat().st_size} B)')
                    tarea.archivos_subidos += 1
                    tarea.bytes_subidos += ruta.stat().st_size
                    continue
                if _verificado(remote, nombre, ruta):
                    tarea.archivos_omitidos += 1
                else:
                    with open(ruta, 'rb') as fh:
                        remote._save(nombre, File(fh))
                    if not _verificado(remote, nombre, ruta):
                        raise MigracionError('el objeto subido no coincide con el original')
                    tarea.archivos_subidos += 1
                    tarea.bytes_subidos += ruta.stat().st_size
                    log(f'subido {alias}:{nombre}')
                if borrar_local:
                    ruta.unlink()
                    tarea.archivos_borrados += 1
            except Exception as exc:  # un archivo malo no frena el resto
                errores.append(f'{alias}:{nombre}: {exc}')
                log(f'ERROR {alias}:{nombre}: {exc}')
            if i % 25 == 0:
                tarea.save()
        tarea.estado = 'PARCIAL' if errores else 'OK'
    except Exception as exc:
        errores.append(f'fatal: {exc}')
        tarea.estado = 'ERROR'
    finally:
        tarea.errores = '\n'.join(errores)[:20000]
        tarea.terminada = timezone.now()
        if tarea.estado == 'EN_CURSO':
            tarea.estado = 'ERROR'
        tarea.save()
    return tarea
