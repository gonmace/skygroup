"""Revisiones de un registro: copia de la anterior + comentario, y elección de la vigente.

Crear una revisión copia el registro y TODO lo cargado (datos de pasos, imágenes de mapa y fotos, con sus
archivos: cada revisión es dueña de los suyos, así borrar una foto en una no afecta a la otra). La revisión
anterior queda intacta. La nueva pasa a ser la vigente; cualquiera puede volver a elegirse después.
"""
import copy
import os
import re

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max

from cuentas.capacidades import tiene_capacidad

COMENTARIO_MAX = 1000
_PREFIJO_UUID = re.compile(r'^[0-9a-f]{12}-')


def _copiar_archivo(origen, destino_campo):
    """Copia el contenido de un FileField a otro (nombre sin el sufijo aleatorio previo)."""
    if not origen:
        return
    nombre = _PREFIJO_UUID.sub('', os.path.basename(origen.name))
    with origen.open('rb') as f:
        destino_campo.save(nombre, ContentFile(f.read()), save=False)


def _copiar_datos_pasos(origen, nuevo):
    from reg_actividades.models import DatoPaso
    ct = ContentType.objects.get_for_model(type(origen))
    DatoPaso.objects.bulk_create([
        DatoPaso(empresa_id=d.empresa_id, content_type=ct, object_id=nuevo.pk, paso_nombre=d.paso_nombre,
                 datos=copy.deepcopy(d.datos), tiene_datos=d.tiene_datos)
        for d in DatoPaso.objects.filter(content_type=ct, object_id=origen.pk)])


def _copiar_mapas(origen, nuevo):
    from reg_actividades.models import ImagenMapa
    ct = ContentType.objects.get_for_model(type(origen))
    for m in ImagenMapa.objects.filter(content_type=ct, object_id=origen.pk):
        copia = ImagenMapa(empresa_id=m.empresa_id, content_type=ct, object_id=nuevo.pk, etapa=m.etapa, zoom=m.zoom,
                           maptype=m.maptype, scale=m.scale, tamano=m.tamano,
                           coordenadas=copy.deepcopy(m.coordenadas),
                           distancia_total_metros=m.distancia_total_metros, desfase_metros=m.desfase_metros)
        _copiar_archivo(m.imagen, copia.imagen)
        copia.save()


def _copiar_fotos(origen, nuevo):
    from reg_fotos.models import Foto
    ct = ContentType.objects.get_for_model(type(origen))
    for f in Foto.objects.filter(content_type=ct, object_id=origen.pk):
        copia = Foto(empresa_id=f.empresa_id, content_type=ct, object_id=nuevo.pk, etapa=f.etapa,
                     descripcion=f.descripcion, orden=f.orden, tamano=f.tamano, exif_lat=f.exif_lat,
                     exif_lon=f.exif_lon, exif_fecha=f.exif_fecha, subida_por_id=f.subida_por_id)
        _copiar_archivo(f.imagen, copia.imagen)
        _copiar_archivo(f.miniatura, copia.miniatura)
        copia.save()


@transaction.atomic
def crear_revision(origen, user, comentario):
    """Revisión nueva de `origen` (copia con todo lo cargado), vigente y abierta. Devuelve la nueva.
    El comentario es obligatorio: explica por qué se revisa."""
    comentario = (comentario or '').strip()
    if not comentario:
        raise ValidationError('Escribe un comentario: explica qué cambia en esta revisión.')
    if len(comentario) > COMENTARIO_MAX:
        raise ValidationError(f'El comentario admite hasta {COMENTARIO_MAX} caracteres.')
    modelo = type(origen)
    familia = modelo.objects.filter(empresa_id=origen.empresa_id, serie=origen.serie)
    ultima = familia.aggregate(m=Max('rev_numero'))['m'] or 0

    nuevo = modelo.objects.get(pk=origen.pk)
    nuevo.pk = nuevo.id = None
    nuevo._state.adding = True
    nuevo.rev_numero = ultima + 1
    nuevo.rev_comentario = comentario
    nuevo.rev_origen_id = origen.pk
    nuevo.rev_vigente = False   # se promueve abajo, después de bajar la anterior (una sola vigente por serie)
    nuevo.legacy_source, nuevo.legacy_id = '', None
    nuevo.preparar_revision(origen)
    nuevo.save()

    _copiar_datos_pasos(origen, nuevo)
    _copiar_mapas(origen, nuevo)
    _copiar_fotos(origen, nuevo)
    nuevo.copiar_revision_extras(origen)
    elegir_vigente(nuevo)
    return nuevo


@transaction.atomic
def elegir_vigente(registro):
    """Marca `registro` como la revisión vigente de su serie (las demás dejan de serlo)."""
    modelo = type(registro)
    modelo.objects.filter(empresa_id=registro.empresa_id, serie=registro.serie).exclude(pk=registro.pk).update(
        rev_vigente=False)
    modelo.objects.filter(pk=registro.pk).update(rev_vigente=True)
    registro.rev_vigente = True


def exigir_crear(user, registro):
    if not tiene_capacidad(user, 'reg.cargar_datos', registro.empresa):
        raise PermissionDenied


def exigir_elegir(user, registro):
    if not tiene_capacidad(user, 'reg.reabrir', registro.empresa):
        raise PermissionDenied


def contexto(user, registro, tipo):
    """Contexto del panel de revisiones (`reg_base/_revisiones.html`) para el detalle de un registro."""
    if not tipo.con_revisiones:
        return {}
    revisiones = list(registro.revisiones().select_related('user', 'rev_origen'))
    return {'revisiones': revisiones, 'tipo_rev': tipo,
            'puede_revisar': tiene_capacidad(user, 'reg.cargar_datos', registro.empresa),
            'puede_elegir': tiene_capacidad(user, 'reg.reabrir', registro.empresa)}
