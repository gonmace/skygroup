from django.apps import AppConfig


class RegConstruccionBaseConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reg_construccion_base'
    verbose_name = 'Supervisión Campo'

    def ready(self):
        from django.db.models.signals import post_save

        from empresas.models import Empresa
        from panel.menu import registrar_item
        from reg_base.tipos import esta_habilitado, registrar_tipo

        from . import dashboard, widgets  # noqa: F401  (widgets: registra hallazgos_widget y seguimiento_widget)
        from .estandar import sembrar_estandar

        registrar_tipo(
            'construccion-base', self.get_model('RegConstruccionBase'), 'reg.construccion_base.ver',
            'reg_construccion_base:detalle', 'Supervisión Campo',
            descripcion='Reporte de visita de supervisión de obra: actividades, recursos, hallazgos con seguimiento, '
                        'seguridad y revisiones. Plantilla estándar para cualquier empresa.',
            al_habilitar=sembrar_estandar, restaurar=lambda empresa: sembrar_estandar(empresa, restaurar=True),
            panel=dashboard.contexto_inicio, plantilla_panel='reg_construccion_base/_panel.html', con_revisiones=True)

        def activo(request):
            return esta_habilitado(getattr(request, 'empresa', None), 'construccion-base')

        # Grupo «Supervisión» de la barra lateral (las entradas sin sección, como TX/TSS, van antes, sin encabezado).
        registrar_item('reg', 'Supervisión Campo', 'reg_construccion_base:lista', 'building',
                       capacidad='reg.construccion_base.ver', orden=15, condicion=activo, seccion='Supervisión')
        registrar_item('reg', 'Hallazgos', 'reg_construccion_base:hallazgos', 'eye',
                       capacidad='reg.construccion_base.ver', orden=16, condicion=activo, seccion='Supervisión')

        def sembrar_en_empresa_nueva(sender, instance, created, **kwargs):
            """Toda empresa nueva parte con «Construcción» activa y su plantilla estándar."""
            if created:
                from reg_base.tipos import habilitar
                habilitar(instance, 'construccion-base')

        post_save.connect(sembrar_en_empresa_nueva, sender=Empresa, dispatch_uid='reg_construccion_base.empresa_nueva')
