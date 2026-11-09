"""Validación, EXIF, miniaturas y persistencia de las fotos de un registro (sobre el storage privado)."""
import datetime
import io
import logging
import os

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db.models import Max
from django.utils import timezone

from .models import Foto

logger = logging.getLogger(__name__)

EXTENSIONES = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff'}
TAMANO_MINIATURA = (400, 400)
# Etiquetas EXIF (Pillow ≥ 9.4: IFDs vía getexif().get_ifd)
_IFD_EXIF, _IFD_GPS = 0x8769, 0x8825


def _max_tamano():
    return getattr(settings, 'FOTO_MAX_SIZE', 25 * 1024 * 1024)


def validar_imagen(archivo):
    """No confía en el content-type (lo fija el cliente): comprueba extensión, tamaño y que los bytes sean
    realmente una imagen decodificable."""
    ext = os.path.splitext(archivo.name or '')[1].lower()
    if ext not in EXTENSIONES:
        raise ValidationError(f'Extensión no permitida: {ext or "sin extensión"}.')
    if archivo.size and archivo.size > _max_tamano():
        raise ValidationError(f'El archivo supera el máximo de {_max_tamano() // (1024 * 1024)} MB.')
    from PIL import Image, UnidentifiedImageError
    try:
        archivo.seek(0)
        with Image.open(archivo) as img:
            img.verify()
    except Image.DecompressionBombError as exc:
        raise ValidationError('La imagen es demasiado grande (demasiados píxeles).') from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise ValidationError('El archivo no es una imagen válida.') from exc
    finally:
        archivo.seek(0)


def _a_decimal(dms, ref):
    d, m, s = (float(x) for x in dms)
    valor = d + m / 60 + s / 3600
    return -valor if ref in ('S', 'W') else valor


def leer_exif(img):
    """GPS y fecha/hora del EXIF de una imagen PIL ya abierta ({} si no hay nada útil). Es opcional: nunca
    debe impedir guardar la foto."""
    resultado = {}
    try:
        exif = img.getexif()
        if not exif:
            return resultado
        sub = exif.get_ifd(_IFD_EXIF)
        for crudo in (sub.get(0x9003), sub.get(0x9004), exif.get(0x0132)):   # Original, Digitalizada, Modificación
            if crudo:
                try:
                    naive = datetime.datetime.strptime(str(crudo).strip(), '%Y:%m:%d %H:%M:%S')
                    # El EXIF guarda hora local sin zona: se interpreta en la zona horaria del proyecto.
                    resultado['exif_fecha'] = timezone.make_aware(naive) if settings.USE_TZ else naive
                    break
                except (ValueError, TypeError):
                    continue
        gps = exif.get_ifd(_IFD_GPS)
        if gps.get(2) and gps.get(1) and gps.get(4) and gps.get(3):
            lat, lon = _a_decimal(gps[2], gps[1]), _a_decimal(gps[4], gps[3])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                resultado['exif_lat'], resultado['exif_lon'] = lat, lon
    except Exception:
        logger.debug('EXIF ilegible', exc_info=True)
    return resultado


def _miniatura(img):
    from PIL import Image, ImageOps
    miniatura = ImageOps.exif_transpose(img)       # corrige la rotación del EXIF
    miniatura.thumbnail(TAMANO_MINIATURA, Image.LANCZOS)
    salida = io.BytesIO()
    miniatura.convert('RGB').save(salida, format='JPEG', quality=82, optimize=True)
    return salida.getvalue()


MENSAJE_SIN_METADATOS = ('La foto no trae fecha ni ubicación. Toma la foto con la cámara del celular con la ubicación '
                         'activada; las fotos reenviadas por WhatsApp pierden esos datos.')


def guardar_foto(archivo, *, autor, registro, etapa, descripcion='', exigir_metadatos=False):
    """Valida y guarda una foto del registro: original + miniatura JPEG + EXIF, abriendo la imagen una vez.
    Con `exigir_metadatos` se rechaza (antes de escribir nada) la foto sin fecha de captura o sin coordenadas."""
    validar_imagen(archivo)
    from PIL import Image
    ct = ContentType.objects.get_for_model(type(registro))
    siguiente = (Foto.objects.filter(content_type=ct, object_id=registro.pk, etapa=etapa)
                 .aggregate(m=Max('orden'))['m'] or 0) + 1
    datos = archivo.read()
    archivo.seek(0)
    foto = Foto(empresa_id=registro.empresa_id, content_type=ct, object_id=registro.pk, etapa=etapa,
                descripcion=(descripcion or '')[:128], orden=siguiente, tamano=len(datos), subida_por=autor)
    with Image.open(io.BytesIO(datos)) as img:
        exif = leer_exif(img)
        if exigir_metadatos and not all(k in exif for k in ('exif_fecha', 'exif_lat', 'exif_lon')):
            raise ValidationError(MENSAJE_SIN_METADATOS)
        for campo, valor in exif.items():
            setattr(foto, campo, valor)
        miniatura = _miniatura(img)
    nombre = os.path.splitext(os.path.basename(archivo.name))[0][:80] or 'foto'
    ext = os.path.splitext(archivo.name)[1].lower()
    foto.imagen.save(f'{nombre}{ext}', ContentFile(datos), save=False)
    foto.miniatura.save(f'{nombre}.jpg', ContentFile(miniatura), save=False)
    foto.save()
    return foto


def reordenar(registro, etapa, ids):
    """Fija el orden de las fotos de la etapa según `ids` (los ajenos a esa etapa/registro se ignoran)."""
    ct = ContentType.objects.get_for_model(type(registro))
    propias = Foto.objects.filter(content_type=ct, object_id=registro.pk, etapa=etapa)
    existentes = {f.pk: f for f in propias}
    n = 0
    for pk in ids:
        f = existentes.get(pk)
        if f is not None:
            n += 1
            if f.orden != n:
                Foto.objects.filter(pk=pk).update(orden=n)
    return n


def fotos_de(registro):
    """Todas las fotos del registro (de cualquier etapa), en su orden."""
    ct = ContentType.objects.get_for_model(type(registro))
    return Foto.objects.filter(content_type=ct, object_id=registro.pk)
