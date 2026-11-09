"""El hallazgo ya no lleva «Ubicación exacta». Se elimina el campo y se actualiza el texto del paso en las empresas
donde sigue siendo el del estándar."""
from django.db import migrations

ANTES = 'Lo encontrado en esta visita: código, ubicación, descripción, tipo, severidad, responsable y plazo.'
AHORA = 'Lo encontrado en esta visita: código, descripción, tipo, severidad, responsable y plazo.'


def actualizar_texto(apps, schema_editor):
    Paso = apps.get_model('reg_actividades', 'Paso')
    Paso.objects.filter(nombre='cb_hallazgos', descripcion=ANTES).update(descripcion=AHORA)


class Migration(migrations.Migration):

    dependencies = [
        ('reg_construccion_base', '0005_ajustes_de_contenido'),
        ('reg_actividades', '0002_imagenmapa'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='hallazgo',
            name='ubicacion',
        ),
        migrations.RunPython(actualizar_texto, migrations.RunPython.noop),
    ]
