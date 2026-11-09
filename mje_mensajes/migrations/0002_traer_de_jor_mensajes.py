"""Traslada los mensajes del app anterior `jor_mensajes` (que apuntaban a un Perfil de jornadas) a este
(que apunta a la Membresía), renombra el permiso `jor.mensajes.enviar` → `mensajes.enviar` y elimina la tabla
vieja. En una base nueva no hay nada que trasladar."""
from django.db import migrations

VIEJA = 'jor_mje_mensajes_mensaje'


def trasladar(apps, schema_editor):
    conexion = schema_editor.connection
    if VIEJA not in conexion.introspection.table_names():
        return
    with conexion.cursor() as c:
        c.execute(
            'INSERT INTO mje_mensajes_mensaje (id, empresa_id, destinatario_id, remitente_id, cuerpo, enviado, confirmado, '
            'descartado, dia_cerrado, legacy_source, legacy_id) '
            'SELECT m.id, m.empresa_id, p.membresia_id, m.remitente_id, m.cuerpo, m.enviado, m.confirmado, '
            'm.descartado, m.dia_cerrado, m.legacy_source, m.legacy_id '
            f'FROM {VIEJA} m JOIN jor_empleados_perfil p ON p.id = m.destinatario_id')
        if conexion.vendor == 'postgresql':   # los ids se copiaron: la secuencia debe seguir después del mayor
            c.execute("SELECT setval(pg_get_serial_sequence('mje_mensajes_mensaje', 'id'), "
                      "COALESCE((SELECT MAX(id) FROM mje_mensajes_mensaje), 1), (SELECT COUNT(*) > 0 FROM mje_mensajes_mensaje))")
        c.execute(f'DROP TABLE {VIEJA}')
        c.execute("DELETE FROM django_migrations WHERE app = 'jor_mensajes'")
    for modelo in ('RolPermiso', 'UsuarioPermiso'):
        M = apps.get_model('cuentas', modelo)
        M.objects.filter(capacidad='jor.mensajes.enviar').update(capacidad='mensajes.enviar')


class Migration(migrations.Migration):
    dependencies = [
        ('mje_mensajes', '0001_inicial'),
        ('cuentas', '0005_alter_user_legacy_id'),
        ('jor_empleados', '0001_initial'),
    ]
    operations = [migrations.RunPython(trasladar, migrations.RunPython.noop)]
