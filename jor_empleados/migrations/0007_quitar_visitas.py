"""El app `jor_visitas` (bitácora de ingresos de observadores) dejó de existir: se elimina su tabla."""
from django.db import migrations

TABLA = 'jor_visitas_ingresovisita'


def quitar(apps, schema_editor):
    c = schema_editor.connection
    if TABLA in c.introspection.table_names():
        with c.cursor() as cur:
            cur.execute(f'DROP TABLE {TABLA}')
            cur.execute("DELETE FROM django_migrations WHERE app = 'jor_visitas'")


class Migration(migrations.Migration):
    dependencies = [('jor_empleados', '0006_remove_configjornadas_exigir_agente_and_more')]
    operations = [migrations.RunPython(quitar, migrations.RunPython.noop)]
