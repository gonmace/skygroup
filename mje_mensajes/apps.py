from django.apps import AppConfig


class MensajesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mje_mensajes'
    verbose_name = 'Mensajería'

    def ready(self):
        from archivos.registro import proteger_modulo
        from cuentas.capacidades import registrar
        from cuentas.roles import RolBase

        from . import signals  # noqa: F401
        # Módulo `msj`: se activa por empresa (Empresa.modulos) y por persona (AccesoModulo). Se usa desde una
        # ventana flotante disponible en todas las pantallas, sin cambiar de página.
        # `msj.usar` la tienen los 4 roles: es la capacidad que se pierde al deshabilitar el módulo a una persona.
        registrar('msj', {
            'msj.usar': ('Usar la mensajería', {RolBase.COORDINADOR, RolBase.MIEMBRO, RolBase.ESPECIALISTA, RolBase.OBSERVADOR}),
            'msj.ver_todos_proyectos': (
                'Ver el chat de todos los proyectos', {RolBase.COORDINADOR}, {'empresa': True}),
        })
        # Los adjuntos del chat se sirven solo por las vistas de `mensajes` (validan acceso a la conversación).
        proteger_modulo('msj')
        # Sin entradas de barra lateral: es una ventana flotante (ver `flotante` en panel.menu.MODULOS).
