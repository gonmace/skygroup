"""Ajustes de contenido del estándar: «Imágenes generales» deja de ser un paso (se desasigna; el paso y las fotos ya
cargadas no se borran) y «Actividades ejecutadas» pasa a llamarse «Actividades» (solo donde el título no se editó)."""
from django.db import migrations


def ajustar(apps, schema_editor):
    PasoAsignado = apps.get_model('reg_actividades', 'PasoAsignado')
    Paso = apps.get_model('reg_actividades', 'Paso')
    PasoAsignado.objects.filter(plantilla__tipo_registro='construccion-base', paso__nombre='cb_fotos').delete()
    Paso.objects.filter(nombre='cb_actividades', titulo='Actividades ejecutadas').update(titulo='Actividades')


class Migration(migrations.Migration):

    dependencies = [
        ('reg_construccion_base', '0004_actualizar_estandar'),
        ('reg_actividades', '0002_imagenmapa'),
    ]

    operations = [
        migrations.RunPython(ajustar, migrations.RunPython.noop),
    ]
