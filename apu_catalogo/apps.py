from django.apps import AppConfig


class ApuCatalogoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apu_catalogo'
    verbose_name = 'APU · Catálogo'

    def ready(self):
        from cuentas.capacidades import registrar
        from cuentas.roles import RolBase as R

        registrar('apu', {
            'apu.ver': ('Ver el catálogo de insumos, ítems y perfiles de cálculo',
                        {R.COORDINADOR, R.ESPECIALISTA, R.MIEMBRO, R.OBSERVADOR}),
            'apu.catalogo.manage': ('Gestionar insumos, precios e ítems', {R.COORDINADOR, R.ESPECIALISTA, R.MIEMBRO}),
            'apu.perfiles.manage': ('Gestionar los perfiles de cálculo de la empresa', {R.COORDINADOR}, {'empresa': True}),
        })

        from panel.menu import registrar_item
        registrar_item('apu', 'Inicio', 'apu_catalogo:inicio', 'calculator', capacidad='apu.ver', orden=10, exacto=True)
