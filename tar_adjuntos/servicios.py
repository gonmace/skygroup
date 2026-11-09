"""Validación, persistencia y miniaturas de adjuntos (sobre el storage privado)."""
import hashlib
import io
import logging
import os
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import storages

from .models import Adjunto

logger = logging.getLogger(__name__)

# SVG es XML: servido inline ejecutaría cualquier <script> embebido con las cookies de sesión.
_BLOQUEADOS = {'image/svg+xml'}
# Tipos que se pueden servir `inline` con seguridad (rasters y PDF); el resto se descarga.
INLINE_SEGUROS = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp', 'application/pdf'}
_NOMBRE_SEGURO = re.compile(r'[^A-Za-z0-9._() \-]+')
TAMANO_MINIATURA = 256
MAX_ORIGEN_MINIATURA = 8 * 1024 * 1024  # no renderizar archivos enormes dentro de la request


class AdjuntoDuplicado(Exception):
    """El archivo (mismo sha256) ya estaba adjunto al mismo mensaje/ticket."""

    def __init__(self, existente):
        self.existente = existente
        super().__init__('Ese adjunto ya estaba.')


def _max_tamano():
    return getattr(settings, 'ATTACHMENT_MAX_SIZE', 20 * 1024 * 1024)


def _prefijos_permitidos():
    return tuple(getattr(settings, 'ATTACHMENT_ALLOWED_TYPES', ('image/', 'application/pdf')))


def validar_subida(archivo):
    """Tipo permitido, tamaño y —para imágenes— que los bytes sean realmente una imagen decodificable
    (un archivo cualquiera renombrado con content_type='image/png' no pasa)."""
    mime = (archivo.content_type or '').lower()
    if mime in _BLOQUEADOS:
        raise ValidationError('No se permiten archivos SVG.')
    if not mime.startswith(_prefijos_permitidos()):
        raise ValidationError('Tipo de archivo no permitido (imágenes, PDF, Word, Excel, PowerPoint, texto o CSV).')
    if archivo.size and archivo.size > _max_tamano():
        raise ValidationError(f'El archivo supera el máximo de {_max_tamano() // (1024 * 1024)} MB.')
    if mime.startswith('image/'):
        _verificar_imagen(archivo)


def _verificar_imagen(archivo):
    from PIL import Image, UnidentifiedImageError
    try:
        archivo.seek(0)
        with Image.open(archivo) as img:
            img.verify()
    except Image.DecompressionBombError as exc:
        raise ValidationError('La imagen es demasiado grande (demasiados píxeles).') from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError('El archivo no es una imagen válida.') from exc
    finally:
        archivo.seek(0)


def nombre_seguro(nombre):
    base = os.path.basename(nombre or 'archivo')
    base = _NOMBRE_SEGURO.sub('_', base).strip() or 'archivo'
    if not base.strip('.'):  # '.' o '..' escaparían un nivel de carpeta
        base = 'archivo'
    return base[:200]


def _hash(archivo):
    h = hashlib.sha256()
    for bloque in archivo.chunks():
        h.update(bloque)
    archivo.seek(0)
    return h.hexdigest()


def guardar(archivo, *, autor, ticket, comentario=None):
    """Valida y guarda `archivo` como adjunto del ticket (o de un mensaje). Mismo sha256 en el mismo
    destino → AdjuntoDuplicado."""
    validar_subida(archivo)
    digest = _hash(archivo)
    existente = Adjunto.objects.filter(ticket=ticket, comentario=comentario, sha256=digest).first()
    if existente:
        raise AdjuntoDuplicado(existente)
    nombre = nombre_seguro(archivo.name)
    adjunto = Adjunto(
        empresa_id=ticket.empresa_id, ticket=ticket, comentario=comentario, nombre=nombre,
        mime_type=(archivo.content_type or 'application/octet-stream')[:100],
        tamano=archivo.size or 0, sha256=digest, subido_por=autor,
    )
    adjunto.archivo.save(nombre, archivo, save=False)
    adjunto.save()
    return adjunto


def guardar_version(padre, *, png, autor, comentario):
    """Nueva versión anotada de la imagen `padre` (PNG), publicada en `comentario`. Mismo ticket y
    misma carpeta lógica para que el historial de versiones quede junto."""
    if len(png) > _max_tamano():
        raise ValidationError(f'La imagen supera el máximo de {_max_tamano() // (1024 * 1024)} MB.')
    digest = hashlib.sha256(png).hexdigest()
    existente = Adjunto.objects.filter(ticket=padre.ticket, comentario=comentario, sha256=digest).first()
    if existente:
        raise AdjuntoDuplicado(existente)
    base = os.path.splitext(padre.nombre or 'imagen')[0]
    nombre = f'{base}-v{padre.version_numero + 1}.png'
    adjunto = Adjunto(
        empresa_id=padre.empresa_id, ticket=padre.ticket, comentario=comentario, nombre=nombre,
        mime_type='image/png', tamano=len(png), sha256=digest, subido_por=autor,
        version_de=padre, version_numero=padre.version_numero + 1,
    )
    adjunto.archivo.save(nombre, ContentFile(png), save=False)
    adjunto.save()
    return adjunto


# ── Miniaturas (se guardan en el mismo storage privado, indexadas por sha256) ─────────────────────

def _ruta_miniatura(adjunto, tamano):
    return f'{adjunto.empresa_id}/tar/miniaturas/{adjunto.sha256[:2]}/{adjunto.sha256}_{tamano}.png'


def miniatura(adjunto, tamano=TAMANO_MINIATURA):
    """PNG (bytes) de la miniatura, o None si no aplica o falla. Los aciertos se persisten: se generan
    una sola vez, también con el almacenamiento en un bucket."""
    return miniatura_en(adjunto, _ruta_miniatura(adjunto, tamano), tamano)


def miniatura_en(adjunto, ruta, tamano=TAMANO_MINIATURA):
    """Como `miniatura`, para cualquier adjunto con `tiene_miniatura`, `es_imagen`, `sha256`, `tamano` y
    `archivo` (p. ej. el del chat), cacheando el PNG en `ruta` del storage privado."""
    if not adjunto.tiene_miniatura or not adjunto.sha256 or (adjunto.tamano or 0) > MAX_ORIGEN_MINIATURA:
        return None
    storage = storages['privado']
    if storage.exists(ruta):
        with storage.open(ruta, 'rb') as f:
            return f.read()
    try:
        with adjunto.archivo.open('rb') as f:
            datos = f.read()
        png = _miniatura_imagen(datos, tamano) if adjunto.es_imagen else _miniatura_pdf(datos, tamano)
    except Exception:
        logger.warning('No se pudo generar la miniatura del adjunto %s', adjunto.pk, exc_info=True)
        return None
    if png:
        storage.save(ruta, ContentFile(png))
    return png


def _miniatura_imagen(datos, tamano):
    from PIL import Image
    im = Image.open(io.BytesIO(datos)).convert('RGBA')
    im.thumbnail((tamano, tamano))
    salida = io.BytesIO()
    im.save(salida, 'PNG')
    return salida.getvalue()


def _miniatura_pdf(datos, tamano):
    import pymupdf  # PyMuPDF
    doc = pymupdf.open(stream=datos, filetype='pdf')
    try:
        pagina = doc.load_page(0)
        zoom = tamano / max(pagina.rect.width, pagina.rect.height, 1)
        return pagina.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes('png')
    finally:
        doc.close()
