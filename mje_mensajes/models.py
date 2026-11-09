import os
import uuid

from django.conf import settings
from django.core.files.storage import storages
from django.db import models
from django.db.models import Q


class Conversacion(models.Model):
    """Un hilo de chat de la empresa: el canal General, el de un proyecto, o un mensaje directo entre dos
    personas (`directo_a` < `directo_b` por id, para que el par sea único)."""

    class Tipo(models.TextChoices):
        GENERAL = 'general', 'General'
        PROYECTO = 'proyecto', 'Proyecto'
        DIRECTO = 'directo', 'Directo'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='conversaciones')
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    proyecto = models.ForeignKey('proyectos.Proyecto', null=True, blank=True, on_delete=models.CASCADE,
                                 related_name='conversaciones')
    directo_a = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
                                  related_name='+')
    directo_b = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
                                  related_name='+')
    creada = models.DateTimeField(auto_now_add=True)
    ultimo_mensaje_en = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = 'Conversación'
        verbose_name_plural = 'Conversaciones'
        constraints = [
            models.UniqueConstraint(fields=['empresa'], condition=Q(tipo='general'), name='msj_un_general'),
            models.UniqueConstraint(fields=['proyecto'], condition=Q(tipo='proyecto'), name='msj_un_proyecto'),
            models.UniqueConstraint(fields=['empresa', 'directo_a', 'directo_b'], condition=Q(tipo='directo'),
                                    name='msj_un_directo'),
        ]

    def __str__(self):
        return self.titulo()

    def titulo(self, para=None):
        """Nombre visible. En un directo depende de quién mira (`para`): se muestra al OTRO."""
        if self.tipo == self.Tipo.GENERAL:
            return 'General'
        if self.tipo == self.Tipo.PROYECTO:
            return self.proyecto.nombre if self.proyecto_id else 'Proyecto'
        otro = self.otro(para) if para is not None else self.directo_a
        return str(otro) if otro else 'Conversación'

    def otro(self, user):
        """El otro usuario de un directo (None si no es directo o `user` no participa)."""
        if self.tipo != self.Tipo.DIRECTO:
            return None
        if user.pk == self.directo_a_id:
            return self.directo_b
        if user.pk == self.directo_b_id:
            return self.directo_a
        return None


class Participacion(models.Model):
    """Hasta qué mensaje leyó cada persona una conversación (para los no leídos)."""
    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='participaciones')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    ultimo_leido = models.PositiveBigIntegerField(default=0, help_text='Id del último mensaje leído.')

    class Meta:
        verbose_name = 'Participación'
        verbose_name_plural = 'Participaciones'
        constraints = [models.UniqueConstraint(fields=['conversacion', 'user'], name='msj_participacion_unica')]


class Mensaje(models.Model):
    """Un mensaje del chat. `autor` nulo = aviso del sistema (skyBot)."""
    conversacion = models.ForeignKey(Conversacion, on_delete=models.CASCADE, related_name='mensajes')
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='+')
    texto = models.TextField('Mensaje', blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    editado = models.DateTimeField(null=True, blank=True)
    menciones = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='+')
    legacy_source = models.CharField(max_length=20, blank=True, editable=False)
    legacy_id = models.PositiveIntegerField(null=True, blank=True, editable=False, db_index=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'Mensaje'
        verbose_name_plural = 'Mensajes'
        indexes = [models.Index(fields=['conversacion', 'id'], name='msj_conv_id_idx')]

    @property
    def nombre_autor(self):
        return str(self.autor) if self.autor_id else 'skyBot'


def almacenamiento_privado():
    return storages['privado']


def ruta_adjunto(instancia, nombre):
    conv = instancia.mensaje.conversacion
    return f'{conv.empresa_id}/msj/{conv.pk}/{uuid.uuid4().hex[:12]}-{os.path.basename(nombre)}'


class AdjuntoMensaje(models.Model):
    """Archivo (imagen, PDF…) adjunto a un mensaje, en el almacenamiento privado (local o S3)."""
    mensaje = models.ForeignKey(Mensaje, on_delete=models.CASCADE, related_name='adjuntos')
    archivo = models.FileField(upload_to=ruta_adjunto, storage=almacenamiento_privado, max_length=300)
    nombre = models.CharField(max_length=200)
    mime_type = models.CharField(max_length=100, blank=True)
    tamano = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        verbose_name = 'Adjunto de mensaje'
        verbose_name_plural = 'Adjuntos de mensajes'
        ordering = ['id']

    @property
    def es_imagen(self):
        return (self.mime_type or '').startswith('image/')

    @property
    def es_pdf(self):
        return self.mime_type == 'application/pdf'

    @property
    def tiene_miniatura(self):
        return self.es_imagen or self.es_pdf
