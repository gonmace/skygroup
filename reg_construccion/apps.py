from django.apps import AppConfig


class RegConstruccionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reg_construccion'
    verbose_name = 'Construcción'

    def ready(self):
        from . import signals  # noqa: F401
        from reg_base.tipos import registrar_tipo

        from . import dashboard
        registrar_tipo('construccion', self.get_model('RegConstruccion'), 'reg.construccion.ver',
                       'reg_construccion:detalle', 'Construcción',
                       descripcion='Reporte de avance de obra con tabla de ítems y porcentaje acumulado.',
                       panel=dashboard.contexto_inicio, plantilla_panel='reg_construccion/_panel.html')
