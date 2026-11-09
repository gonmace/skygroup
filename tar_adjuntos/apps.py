from django.apps import AppConfig


class TarAdjuntosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tar_adjuntos'
    verbose_name = 'Adjuntos de Tareas'

    def ready(self):
        from archivos.registro import proteger_modulo

        from . import signals  # noqa: F401
        # Estos archivos se sirven SOLO por las vistas del módulo (que validan el acceso al ticket),
        # nunca por la ruta genérica /archivos/privado/ (que solo valida la empresa).
        proteger_modulo('tar')
