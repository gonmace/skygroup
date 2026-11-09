"""La capacidad `mensajes.ver_todos_proyectos` pasa a `msj.ver_todos_proyectos` (el prefijo es el código del módulo)."""
from django.db import migrations

VIEJA, NUEVA = 'mensajes.ver_todos_proyectos', 'msj.ver_todos_proyectos'


def renombrar(apps, schema_editor):
    for modelo in ('RolPermiso', 'UsuarioPermiso'):
        apps.get_model('cuentas', modelo).objects.filter(capacidad=VIEJA).update(capacidad=NUEVA)


def deshacer(apps, schema_editor):
    for modelo in ('RolPermiso', 'UsuarioPermiso'):
        apps.get_model('cuentas', modelo).objects.filter(capacidad=NUEVA).update(capacidad=VIEJA)


class Migration(migrations.Migration):
    dependencies = [('mje_mensajes', '0003_chat'), ('cuentas', '0008_modulo_msj')]
    operations = [migrations.RunPython(renombrar, deshacer)]
