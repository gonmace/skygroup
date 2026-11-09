import uuid

from django.conf import settings
from django.core.files.storage import storages
from django.db import models


def almacenamiento_privado():
    """Storage privado (disco local o bucket privado, según la config de `cdn`)."""
    return storages['privado']


def ruta_adjunto(instance, filename):
    # Convención del storage privado: <empresa_id>/<módulo>/… ; el sufijo aleatorio hace la ruta
    # impredecible y evita colisiones entre archivos con el mismo nombre.
    return f'{instance.empresa_id}/tar/{instance.ticket_id}/{uuid.uuid4().hex[:12]}-{filename}'


class Adjunto(models.Model):
    """Archivo adjunto a un ticket o a un mensaje de su seguimiento (imagen, PDF u ofimática)."""

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='adjuntos_tareas')
    ticket = models.ForeignKey('tar_tickets.Ticket', on_delete=models.CASCADE, related_name='adjuntos')
    comentario = models.ForeignKey(
        'tar_tickets.Comentario', null=True, blank=True, on_delete=models.CASCADE, related_name='adjuntos',
    )
    archivo = models.FileField(upload_to=ruta_adjunto, storage=almacenamiento_privado, max_length=500)
    nombre = models.CharField('Nombre', max_length=255)
    mime_type = models.CharField('Tipo MIME', max_length=100)
    tamano = models.PositiveBigIntegerField('Tamaño (bytes)', default=0)
    sha256 = models.CharField('Hash', max_length=64, blank=True, default='', db_index=True)
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    # Versionado de anotaciones: la anotación guarda el PNG resultante de dibujar sobre la imagen.
    version_de = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='versiones')
    version_numero = models.PositiveIntegerField('Versión', default=1)

    class Meta:
        ordering = ['-creado', '-id']
        indexes = [models.Index(fields=['ticket', 'comentario'])]
        verbose_name = 'Adjunto'
        verbose_name_plural = 'Adjuntos'

    def __str__(self):
        return self.nombre

    @property
    def es_imagen(self):
        return self.mime_type.startswith('image/')

    @property
    def es_pdf(self):
        return self.mime_type == 'application/pdf'

    @property
    def tiene_miniatura(self):
        return self.es_imagen or self.es_pdf

    @property
    def extension(self):
        return self.nombre.rsplit('.', 1)[-1].lower() if '.' in self.nombre else ''
