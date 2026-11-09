"""Pasos configurables por empresa: una Plantilla agrupa Pasos; cada Paso tiene Widgets que capturan datos."""
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import Lower


class Plantilla(models.Model):
    """Conjunto ordenado de pasos que se aplica a un tipo de registro (y, opcionalmente, a un tipo de proyecto).
    Un registro usa la plantilla de su tipo cuyo tipo de proyecto coincide; si no, la general (sin tipo de proyecto)."""

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='plantillas_registro')
    nombre = models.CharField('Nombre', max_length=100)
    descripcion = models.TextField('Descripción', blank=True)
    tipo_registro = models.CharField('Tipo de registro', max_length=30, help_text='txtss, construccion…')
    tipo_proyecto = models.ForeignKey(
        'proyectos.TipoProyecto', null=True, blank=True, on_delete=models.CASCADE, related_name='+',
        verbose_name='Aplica a proyectos de tipo', help_text='Vacío = a cualquier proyecto.',
    )
    activa = models.BooleanField('Activa', default=True)

    class Meta:
        ordering = ['tipo_registro', 'nombre']
        verbose_name = 'Plantilla de pasos'
        verbose_name_plural = 'Plantillas de pasos'
        constraints = [
            # Una sola plantilla ACTIVA por (tipo de registro, tipo de proyecto) en cada empresa.
            models.UniqueConstraint(
                fields=['empresa', 'tipo_registro', 'tipo_proyecto'], condition=Q(activa=True, tipo_proyecto__isnull=False),
                name='reg_plantilla_activa_unica_con_tipo',
            ),
            models.UniqueConstraint(
                fields=['empresa', 'tipo_registro'], condition=Q(activa=True, tipo_proyecto__isnull=True),
                name='reg_plantilla_activa_unica_general',
            ),
        ]

    def __str__(self):
        return self.nombre

    def clean(self):
        if self.tipo_proyecto_id and self.empresa_id and self.tipo_proyecto.empresa_id != self.empresa_id:
            raise ValidationError({'tipo_proyecto': 'El tipo pertenece a otra empresa.'})


class Paso(models.Model):
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='pasos_registro')
    nombre = models.SlugField('Nombre (slug)', max_length=50, help_text='Identificador estable: va en la URL y en la etapa de las fotos.')
    titulo = models.CharField('Título', max_length=100)
    descripcion = models.TextField('Descripción', blank=True)

    class Meta:
        ordering = ['titulo']
        verbose_name = 'Paso'
        verbose_name_plural = 'Pasos'
        constraints = [models.UniqueConstraint(fields=['empresa', 'nombre'], name='reg_paso_nombre_unico')]

    def __str__(self):
        return self.titulo


class PasoWidget(models.Model):
    paso = models.ForeignKey(Paso, on_delete=models.CASCADE, related_name='widgets')
    widget_slug = models.CharField('Widget', max_length=100)
    orden = models.PositiveIntegerField('Orden', default=0)
    config = models.JSONField('Configuración', default=dict, blank=True)

    class Meta:
        ordering = ['orden', 'id']
        verbose_name = 'Widget de paso'
        verbose_name_plural = 'Widgets de paso'
        constraints = [models.UniqueConstraint(fields=['paso', 'widget_slug'], name='reg_pasowidget_unico')]

    def __str__(self):
        return f'{self.paso} → {self.widget_slug}'

    @property
    def config_json(self):
        import json
        return json.dumps(self.config, ensure_ascii=False, indent=2)

    def clean(self):
        from .widgets import obtener
        widget = obtener(self.widget_slug)
        if widget is None:
            raise ValidationError({'widget_slug': 'Tipo de widget desconocido.'})
        if not isinstance(self.config, dict):
            raise ValidationError({'config': 'La configuración debe ser un objeto JSON.'})
        errores = widget.validar_config(self.config)
        if errores:
            raise ValidationError({'config': errores})


class PasoAsignado(models.Model):
    plantilla = models.ForeignKey(Plantilla, on_delete=models.CASCADE, related_name='asignados')
    paso = models.ForeignKey(Paso, on_delete=models.PROTECT, related_name='asignaciones')
    orden = models.PositiveIntegerField('Orden', default=0)

    class Meta:
        ordering = ['orden', 'id']
        verbose_name = 'Paso asignado'
        verbose_name_plural = 'Pasos asignados'
        constraints = [models.UniqueConstraint(fields=['plantilla', 'paso'], name='reg_pasoasignado_unico')]

    def clean(self):
        if self.plantilla_id and self.paso_id and self.plantilla.empresa_id != self.paso.empresa_id:
            raise ValidationError({'paso': 'El paso pertenece a otra empresa.'})


class DatoPaso(models.Model):
    """Datos capturados de un paso de un registro: {widget_slug: {…}}."""

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='+')
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    registro = GenericForeignKey('content_type', 'object_id')
    paso_nombre = models.CharField('Paso', max_length=50)
    datos = models.JSONField(default=dict)
    # Denormalizado: alguno de los widgets tiene un valor no vacío. Permite calcular el estado del registro en SQL
    # sin recorrer JSON (portable entre PostgreSQL y SQLite).
    tiene_datos = models.BooleanField(default=False, db_index=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Dato de paso'
        verbose_name_plural = 'Datos de pasos'
        constraints = [
            models.UniqueConstraint(fields=['content_type', 'object_id', 'paso_nombre'], name='reg_datopaso_unico'),
        ]

    def __str__(self):
        return f'{self.paso_nombre} · {self.object_id}'


def fuente_estado(modelo):
    """Fuente de «tiene datos» para el estado del registro (ver reg_base.estado): algún paso con datos, salvo los
    pasos opcionales del modelo."""
    ct = ContentType.objects.get_for_model(modelo)
    datos = DatoPaso.objects.filter(content_type=ct, object_id=OuterRef('pk'), tiene_datos=True).exclude(
        paso_nombre__in=getattr(modelo, 'ETAPAS_OPCIONALES', ()))
    return Exists(datos)


def ruta_imagen_mapa(instance, nombre):
    # Convención del storage privado (igual que reg_fotos): <empresa_id>/reg/…; el sufijo hace la ruta impredecible.
    import uuid
    return f'{instance.empresa_id}/reg/{instance.content_type_id}/{instance.object_id}/mapas/{uuid.uuid4().hex[:12]}-{nombre}'


def _almacenamiento_privado():
    from reg_fotos.models import almacenamiento_privado
    return almacenamiento_privado()


class ImagenMapa(models.Model):
    """Imagen estática (Google Static Maps) de los widgets de mapa de un paso: una por registro y paso (`etapa`).
    Equivale al `GoogleMapsImage` de reg.tekon-rl.cl (`legacy_source`/`legacy_id` para migrarlo)."""

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='+')
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    registro = GenericForeignKey('content_type', 'object_id')
    etapa = models.CharField('Paso', max_length=100)
    imagen = models.ImageField(upload_to=ruta_imagen_mapa, storage=_almacenamiento_privado, max_length=500)
    zoom = models.PositiveSmallIntegerField('Zoom')
    maptype = models.CharField('Tipo de mapa', max_length=50, default='hybrid')
    scale = models.PositiveSmallIntegerField('Escala', default=2)
    tamano = models.CharField('Tamaño', max_length=20, default='640x640')
    # Puntos usados para generarla: [{lat, lon, label, color}]. Permite saber si hay que regenerarla.
    coordenadas = models.JSONField(default=list)
    distancia_total_metros = models.FloatField('Distancia total (m)', null=True, blank=True)
    desfase_metros = models.FloatField('Desfase (m)', null=True, blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)
    legacy_source = models.CharField(max_length=20, blank=True, editable=False)
    legacy_id = models.PositiveIntegerField(null=True, blank=True, editable=False, db_index=True)

    class Meta:
        verbose_name = 'Imagen de mapa'
        verbose_name_plural = 'Imágenes de mapa'
        constraints = [
            models.UniqueConstraint(fields=['content_type', 'object_id', 'etapa'], name='reg_imagenmapa_unica'),
        ]

    def __str__(self):
        return f'Mapa {self.etapa} · {self.object_id}'

    def delete(self, *args, **kwargs):
        archivo = self.imagen
        super().delete(*args, **kwargs)
        if archivo:
            archivo.delete(save=False)
