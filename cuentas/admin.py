from django.apps import apps
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class UsuarioAdmin(UserAdmin):
    """Usuario identificado por correo (sin `username`)."""
    ordering = ('email',)
    list_display = ('email', 'first_name', 'last_name', 'is_active', 'is_staff', 'is_superuser', 'is_deleted')
    list_filter = ('is_active', 'is_staff', 'is_superuser', 'is_deleted')
    search_fields = ('email', 'first_name', 'last_name')
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Datos', {'fields': ('first_name', 'last_name', 'telefono')}),
        ('Permisos', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Estado', {'fields': ('is_deleted', 'eliminado_en', 'last_login', 'date_joined')}),
    )
    add_fieldsets = ((None, {'classes': ('wide',), 'fields': ('email', 'password1', 'password2')}),)


# Resto de modelos del proyecto: registro genérico para verlos y editarlos en el admin. Los que ya tienen su
# propio admin (archivos, axes, auth) se omiten; el usuario va arriba con su ModelAdmin.
for _app in ('cuentas', 'empresas', 'proyectos', 'notificaciones', 'mje_mensajes', 'tar_tickets', 'tar_adjuntos',
             'reg_txtss', 'reg_construccion', 'reg_fotos', 'reg_actividades', 'jor_empleados', 'jor_diario',
             'jor_actividades'):
    for _modelo in apps.get_app_config(_app).get_models():
        if not admin.site.is_registered(_modelo):
            admin.site.register(_modelo)


# Índice del admin agrupado por módulo (en vez de una sección por app de Django).
GRUPOS_ADMIN = [
    ('Plataforma', ('cuentas', 'empresas', 'proyectos', 'archivos', 'notificaciones')),
    ('Registros', ('reg_txtss', 'reg_construccion', 'reg_fotos', 'reg_actividades')),
    ('Tareas', ('tar_tickets', 'tar_adjuntos')),
    ('Asistencia', ('jor_empleados', 'jor_diario', 'jor_actividades')),
    ('Mensajería', ('mje_mensajes',)),
    ('Sistema', ('auth', 'axes', 'admin', 'sessions', 'contenttypes')),
]
_original_get_app_list = admin.site.get_app_list


def _app_list_por_modulo(request, app_label=None):
    if app_label:   # la página de una app concreta no se agrupa
        return _original_get_app_list(request, app_label)
    por_app = {a['app_label']: a for a in _original_get_app_list(request)}
    grupos = []
    for titulo, labels in GRUPOS_ADMIN:
        modelos = []
        for label in labels:
            for m in por_app.pop(label, {}).get('models', []):
                modelos.append(m)
        if modelos:
            grupos.append({'name': titulo, 'app_label': labels[0], 'app_url': '', 'has_module_perms': True,
                           'models': sorted(modelos, key=lambda m: m['name'].lower())})
    grupos.extend(por_app.values())   # apps nuevas aún sin grupo: no se pierden
    return grupos


admin.site.get_app_list = _app_list_por_modulo
