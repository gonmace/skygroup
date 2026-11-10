from django.apps import AppConfig


class JorDiarioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'jor_diario'
    verbose_name = 'Asistencia'

    def ready(self):
        from cuentas.capacidades import registrar
        from cuentas.roles import RolBase as R

        # Mapeo skylog → RACI: Empleado→Ejecutor/Especialista, Supervisor/PM→Coordinador, Ejecutivo y
        # Visita→(ya no existe). Los flags can_* de skylog pasan a ser capacidades (excepciones por persona).
        gestion = {R.COORDINADOR}
        registrar('jor', {
            'jor.dashboard.view': ('Ver el resumen de jornadas de la empresa', {R.COORDINADOR, R.OBSERVADOR}, {'empresa': True}),
            'jor.fichar': ('Iniciar y finalizar su propia jornada', {R.COORDINADOR, R.ESPECIALISTA, R.MIEMBRO}),
            'jor.equipo.ver': ('Ver las jornadas y reportes del equipo', gestion, {'empresa': True}),
            'jor.ausencias.solicitar': ('Solicitar ausencias propias', {R.COORDINADOR, R.ESPECIALISTA, R.MIEMBRO}),
            'jor.ausencias.gestionar': ('Registrar y aprobar ausencias del equipo', gestion),
            'jor.excepciones.gestionar': ('Aprobar o rechazar jornadas iniciadas fuera de la sede', gestion, {'empresa': True}),
            'jor.calendario.manage': ('Gestionar notas del calendario (feriados, eventos)', gestion),
            'jor.perfiles.manage': ('Editar el perfil de jornadas de cada persona', gestion, {'empresa': True}),
            'jor.stats.view': ('Ver estadísticas globales', gestion),
            'jor.reportes.ver': ('Ver el reporte de asistencia y exportarlo', gestion, {'empresa': True}),
            'jor.certificado.generar': ('Generar el reporte de personal (xlsx)', gestion, {'empresa': True}),
            'jor.etiquetas.manage': ('Gestionar las etiquetas de actividad (proyectos, sedes, entregables)', gestion),
            'jor.config.manage': ('Configurar jornadas y categorías de actividad', gestion, {'empresa': True}),
        })

        from panel.menu import registrar_item

        def lleva(request):     # superusuarios y administradores no llevan jornada propia
            from .servicios import lleva_jornada
            return lleva_jornada(request.user, request.empresa)

        registrar_item('jor', 'Resumen', 'jor_diario:resumen', 'chart', capacidad='jor.dashboard.view', orden=5)
        registrar_item('jor', 'Mi jornada', 'jor_diario:inicio', 'clock', capacidad='jor.fichar', orden=10, exacto=True, seccion='Mi trabajo', condicion=lleva)
        registrar_item('jor', 'Mis reportes', 'jor_diario:historial', 'file-text', capacidad='jor.fichar', orden=20, seccion='Mi trabajo', condicion=lleva)
        registrar_item('jor', 'Ausencias', 'jor_diario:ausencias', 'calendar-off', capacidad='jor.fichar', orden=30, seccion='Mi trabajo', condicion=lleva)
        # El calendario es del equipo (feriados y eventos de la empresa): lo ve todo miembro, en la sección Equipo.
        registrar_item('jor', 'Calendario', 'jor_diario:calendario', 'calendar', orden=45, seccion='Equipo')
        registrar_item('jor', 'Equipo', 'jor_diario:equipo', 'users', capacidad='jor.equipo.ver', orden=40, seccion='Equipo')
        registrar_item('jor', 'Reporte de asistencia', 'jor_reportes:asistencia', 'user-check', capacidad='jor.reportes.ver', orden=60, seccion='Equipo')
        registrar_item('jor', 'Excepciones', 'jor_diario:excepciones', 'user-check', capacidad='jor.excepciones.gestionar', orden=50, seccion='Equipo')
        registrar_item('jor', 'Estadísticas', 'jor_reportes:estadisticas', 'chart', capacidad='jor.stats.view', orden=65, seccion='Equipo')
        registrar_item('jor', '{certificado}', 'jor_reportes:certificado', 'file-text', capacidad='jor.certificado.generar', orden=70, seccion='Reportes')
        # Categorías y Etiquetas son pestañas de Configuración (jor_empleados.views.pestanas_config).
        registrar_item('jor', 'Configuración', 'jor_empleados:config', 'settings',
                       capacidad=('jor.config.manage', 'jor.etiquetas.manage'), orden=90, seccion='Ajustes',
                       activo_en=('jor_actividades:categorias', 'jor_actividades:etiquetas'))
