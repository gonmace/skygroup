from django.apps import AppConfig


class ApuGeneradorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apu_generador'
    verbose_name = 'APU · Generador con IA'

    def ready(self):
        from panel.menu import registrar_item

        registrar_item('apu', 'Nuevo APU', 'apu_generador:nuevo', 'sparkles', capacidad='apu.catalogo.manage', orden=20)
        registrar_item('apu', 'Pendientes', 'apu_generador:pendientes', 'clock', capacidad='apu.catalogo.manage', orden=25)
        registrar_item('apu', 'Usuarios', 'apu_generador:usuarios', 'users', capacidad='apu.ver', orden=70,
                       solo_admin=True)
        registrar_item('apu', 'Plantillas', 'apu_generador:plantillas', 'layers', solo_superusuario=True, orden=75)
        registrar_item('apu', 'Consumo IA', 'apu_generador:consumo_ia', 'chart', solo_superusuario=True, orden=80)
