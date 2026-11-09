import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import storages
from django.db import models
from django.db.models import Exists, OuterRef


def almacenamiento_privado():
    return storages['privado']


def _ruta(instance, nombre, carpeta=''):
    # Convención del storage privado: <empresa_id>/<módulo>/… ; el sufijo aleatorio hace la ruta impredecible.
    return f'{instance.empresa_id}/reg/{instance.content_type_id}/{instance.object_id}/{carpeta}{uuid.uuid4().hex[:12]}-{nombre}'


def ruta_imagen(instance, nombre):
    return _ruta(instance, nombre)


def ruta_miniatura(instance, nombre):
    return _ruta(instance, nombre, 'miniaturas/')


class Foto(models.Model):
    """Foto de un registro (TX/TSS, Construcción…) dentro de una etapa (paso)."""

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='+')
    # Referencia genérica al registro (de cualquier tipo).
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    registro = GenericForeignKey('content_type', 'object_id')
    etapa = models.CharField('Etapa', max_length=100)
    imagen = models.ImageField(upload_to=ruta_imagen, storage=almacenamiento_privado, max_length=500)
    miniatura = models.ImageField(upload_to=ruta_miniatura, storage=almacenamiento_privado, max_length=500,
                                  null=True, blank=True)
    descripcion = models.CharField('Descripción', max_length=128, blank=True)
    orden = models.IntegerField(default=0)
    tamano = models.PositiveIntegerField('Tamaño (bytes)', null=True, blank=True)
    # Metadatos EXIF extraídos al subir.
    exif_lat = models.FloatField('Latitud EXIF', null=True, blank=True)
    exif_lon = models.FloatField('Longitud EXIF', null=True, blank=True)
    exif_fecha = models.DateTimeField('Fecha/hora EXIF', null=True, blank=True)
    subida_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creada = models.DateTimeField(auto_now_add=True)
    legacy_source = models.CharField(max_length=20, blank=True, editable=False)
    legacy_id = models.PositiveIntegerField(null=True, blank=True, editable=False, db_index=True)

    class Meta:
        verbose_name = 'Foto'
        verbose_name_plural = 'Fotos'
        ordering = ['orden', 'id']
        indexes = [models.Index(fields=['content_type', 'object_id', 'etapa'], name='regfotos_ct_obj_etapa_idx')]

    def __str__(self):
        return f'Foto {self.pk} · {self.etapa}'


def fuente_estado(modelo):
    """Fuente de «tiene datos» para el estado del registro (ver reg_base.estado): tiene al menos una foto en
    una etapa que cuente (las etapas opcionales del modelo no cuentan)."""
    ct = ContentType.objects.get_for_model(modelo)
    fotos = Foto.objects.filter(content_type=ct, object_id=OuterRef('pk')).exclude(
        etapa__in=getattr(modelo, 'ETAPAS_OPCIONALES', ()))
    return Exists(fotos)
