from django.db import migrations


def titulo_referencia(apps, schema_editor):
    # Solo el título visible (botón); `nombre` sigue siendo «mandato» porque es la clave que usa el código.
    apps.get_model('reg_actividades', 'Paso').objects.filter(nombre='mandato', titulo='Mandato').update(titulo='Referencia')


class Migration(migrations.Migration):

    dependencies = [
        ('reg_actividades', '0002_imagenmapa'),
    ]

    operations = [
        migrations.RunPython(titulo_referencia, migrations.RunPython.noop),
    ]
