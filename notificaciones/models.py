from django.conf import settings
from django.db import models


class Notificacion(models.Model):
    """Aviso para un usuario dentro de una empresa (la campana de la cabecera)."""

    destinatario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notificaciones')
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='notificaciones')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        help_text='Quien originó el aviso (vacío = el sistema).',
    )
    mensaje = models.CharField(max_length=240)
    url = models.CharField(
        max_length=300, blank=True,
        help_text='Ruta relativa a la que lleva el aviso, SIN el prefijo de empresa (ej. /tareas/12/).',
    )
    leida = models.BooleanField(default=False)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creada', '-id']
        verbose_name = 'Notificación'
        verbose_name_plural = 'Notificaciones'
        indexes = [models.Index(fields=['destinatario', 'empresa', 'leida'], name='notif_destino_idx')]

    def __str__(self):
        return f'{self.destinatario}: {self.mensaje}'
