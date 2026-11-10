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

        # «Imágenes»: solo superusuario y administradores de sistema (ver `imagenes.puede_gestionar_imagenes`).
        from panel.menu import registrar_item

        from .imagenes import puede_gestionar_imagenes
        registrar_item('reg', 'Imágenes', 'reg_fotos:imagenes', 'camera', orden=80,
                       condicion=lambda request: puede_gestionar_imagenes(request.user, getattr(request, 'empresa', None)))
