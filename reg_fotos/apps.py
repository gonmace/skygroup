from django.apps import AppConfig


class RegFotosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reg_fotos'
    verbose_name = 'Fotos de Registros'

    def ready(self):
        from archivos.registro import proteger_modulo
        from reg_base.estado import registrar_fuente

        from . import signals  # noqa: F401
        from .models import fuente_estado

        # Las fotos se sirven SOLO por las vistas de este módulo (validan el alcance del registro).
        proteger_modulo('reg')
        registrar_fuente(fuente_estado)
