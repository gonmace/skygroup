from django.apps import AppConfig


class RegBaseConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reg_base'
    verbose_name = 'Registros'

    def ready(self):
        from cuentas.capacidades import registrar
        from cuentas.roles import RolBase as R
        from panel.menu import registrar_item

        from .tipos import esta_habilitado

        def activo(clave):
            return lambda request: esta_habilitado(getattr(request, 'empresa', None), clave)

        # Mapeo reg → RACI: ADMINISTRADOR global → Coordinador; ADMINISTRADOR de contratista → Coordinador
        # acotado (membresía con contratista); ITO/Buscador → Ejecutor; Visita → Observador.
        lector = set(R)
        registrar('reg', {
            'reg.txtss.ver': ('Ver los registros TX/TSS', lector),
            'reg.construccion.ver': ('Ver los registros de Construcción', lector),
            'reg.construccion_base.ver': ('Ver los registros de Supervisión Campo', lector),
            # Alcance de datos: qué registros ve cada rol (si no tiene ninguno, solo los propios).
            'reg.alcance.todo': ('Ver los registros de toda la empresa', {R.COORDINADOR, R.OBSERVADOR}, {'empresa': True}),
            'reg.alcance.contratista': ('Ver los registros de su contratista', {R.COORDINADOR}),
            'reg.cargar_datos': ('Cargar datos (visitas, pasos, fotos, mapas, fecha)', {R.COORDINADOR, R.MIEMBRO}),
            'reg.activar': ('Activar registros y sitios de obra', {R.COORDINADOR}),
            'reg.cambiar_responsable': ('Cambiar el responsable de un registro', {R.COORDINADOR}),
            'reg.concluir': ('Concluir registros', {R.COORDINADOR, R.MIEMBRO}),
            'reg.reabrir': ('Reabrir registros concluidos', {R.COORDINADOR}),
            'reg.items_obra': ('Definir los ítems de obra', {R.COORDINADOR}),
            'reg.config.manage': ('Configurar el módulo Registros (solo superusuario)', set(), {'empresa': True}),
        })
        registrar_item('reg', 'Resumen', 'reg_base:inicio', 'chart', orden=5, exacto=True)
        registrar_item('reg', 'TX/TSS', 'reg_txtss:lista', 'clipboard', capacidad='reg.txtss.ver', orden=10, por_tipo=True,
                       condicion=activo('txtss'))
        registrar_item('reg', 'Construcción', 'reg_construccion:lista', 'building',
                       capacidad='reg.construccion.ver', orden=12, condicion=activo('construccion'))
        registrar_item('reg', 'Configuración', 'reg_base:config', 'settings', capacidad='reg.config.manage', orden=90,
                       solo_superusuario=True, exacto=True)
        registrar_item('reg', 'Tipos de registro', 'reg_base:tipos', 'layers', capacidad='reg.config.manage', orden=89,
                       solo_superusuario=True)
