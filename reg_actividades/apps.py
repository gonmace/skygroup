from django.apps import AppConfig


class RegActividadesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reg_actividades'
    verbose_name = 'Pasos de Registros'

    def ready(self):
        from reg_base.estado import registrar_fuente

        from . import widgets  # noqa: F401  (registra los tipos de widget)
        from .models import fuente_estado
        registrar_fuente(fuente_estado)

        from panel.menu import registrar_item
        registrar_item('reg', 'Pasos', 'reg_actividades:pasos_config', 'list', capacidad='reg.config.manage', orden=91,
                       solo_superusuario=True)
        registrar_item('reg', 'Plantillas', 'reg_actividades:plantillas', 'layers', capacidad='reg.config.manage', orden=92,
                       solo_superusuario=True)
