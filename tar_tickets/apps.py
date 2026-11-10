from django.apps import AppConfig


class TarTicketsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tar_tickets'
    verbose_name = 'Tareas'

    def ready(self):
        from . import signals  # noqa: F401
        from cuentas.capacidades import registrar
        from cuentas.roles import RolBase as R

        # Mapeo skydesk → RACI: Coordinador→Coordinador, Experto→Especialista, Ejecutor→Ejecutor (MIEMBRO),
        # Seguimiento y Administrador (observador)→Observador.
        todo = {R.COORDINADOR}
        registrar('tar', {
            'tar.tickets.view_all': ('Ver todos los tickets', todo | {R.OBSERVADOR}, {'empresa': True, 'admin_lectura': True}),
            'tar.tickets.create': ('Crear tickets', todo),
            'tar.tickets.edit_any': ('Editar cualquier ticket', todo),
            'tar.tickets.assign': ('Asignar tickets', todo),
            'tar.tickets.close': ('Cerrar y aprobar tickets', todo),
            'tar.tickets.move': ('Mover tickets (arrastrar)', todo | {R.MIEMBRO}),
            'tar.tickets.unarchive': ('Desarchivar tickets', todo),
            'tar.tickets.view_waiting': ('Ver la columna Suspendido/Cancelado', todo | {R.OBSERVADOR}, {'admin_lectura': True}),
            'tar.tickets.view_backlog': ('Ver la columna Entrada', todo, {'admin_lectura': True}),
            'tar.tickets.board_by_ticket': (
                'Tablero por ticket completo (no por subticket propio)',
                todo | {R.ESPECIALISTA, R.OBSERVADOR}, {'admin_lectura': True},
            ),
            'tar.chat.view_all': ('Ver el chat de cualquier tarea', todo | {R.OBSERVADOR}, {'admin_lectura': True}),
            'tar.chat.write': ('Escribir en el chat de seguimiento', todo | {R.ESPECIALISTA, R.MIEMBRO}),
            'tar.dashboard.view': (
                'Ver el dashboard de métricas', todo | {R.ESPECIALISTA, R.OBSERVADOR}, {'admin_lectura': True},
            ),
            'tar.etiquetas.manage': ('Gestionar tipos de actividad', todo),
        })

        from panel.menu import registrar_item
        registrar_item('tar', 'Tablero', 'tar_tickets:tablero', 'kanban', orden=10, exacto=True)
        registrar_item('tar', 'Mis tickets', 'tar_tickets:mis_tickets', 'check', orden=20)
        registrar_item('tar', 'Seguimiento', 'tar_tickets:seguimiento', 'clipboard',
                       capacidad='tar.chat.view_all', orden=30)
        registrar_item('tar', 'Resumen', 'tar_tickets:dashboard', 'chart', capacidad='tar.dashboard.view', orden=5)
        registrar_item('tar', 'Archivados', 'tar_tickets:archivados', 'archive', orden=50)
        registrar_item('tar', 'Tipos de actividad', 'tar_tickets:etiquetas', 'palette',
                       capacidad='tar.etiquetas.manage', orden=60)
