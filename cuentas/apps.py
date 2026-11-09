from django.apps import AppConfig


class CuentasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cuentas'
    verbose_name = 'Cuentas'

    def ready(self):
        from . import signals  # noqa: F401
        from .capacidades import registrar
        from .roles import RolBase

        registrar('cuentas', {
            'cuentas.usuarios.manage': ('Gestionar miembros de la empresa', {RolBase.COORDINADOR}, {'empresa': True}),
            'cuentas.roles.manage': ('Gestionar roles y permisos de la empresa', {RolBase.COORDINADOR}, {'empresa': True}),
        })
        registrar('empresas', {
            'empresas.marca.manage': ('Editar la marca de la empresa', {RolBase.COORDINADOR}, {'empresa': True}),
            'empresas.contratistas.manage': (
                'Gestionar los contratistas de la empresa', {RolBase.COORDINADOR}, {'empresa': True}),
        })
        registrar('proyectos', {
            'proyectos.view': (
                'Ver proyectos',
                set(RolBase),
            ),
            'proyectos.manage': ('Crear y editar proyectos', {RolBase.COORDINADOR}, {'empresa': True}),
        })
