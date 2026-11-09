"""Las empresas que ya usan TX/TSS o Construcción conservan su acceso; las demás dejan de verlos.

Desde ahora cada empresa activa solo los tipos de registro que usa (`TipoHabilitado`). Se activa el tipo donde hay
registros (aunque estén borrados) o plantillas de pasos de ese tipo.
"""
from django.db import migrations


def activar_en_uso(apps, schema_editor):
    TipoHabilitado = apps.get_model('reg_base', 'TipoHabilitado')
    Plantilla = apps.get_model('reg_actividades', 'Plantilla')
    uso = {
        'txtss': set(apps.get_model('reg_txtss', 'RegTxtss').objects.values_list('empresa_id', flat=True)),
        'construccion': set(apps.get_model('reg_construccion', 'RegConstruccion').objects.values_list('empresa_id', flat=True)),
    }
    for clave in uso:
        uso[clave] |= set(Plantilla.objects.filter(tipo_registro=clave).values_list('empresa_id', flat=True))
        for empresa_id in uso[clave]:
            TipoHabilitado.objects.get_or_create(empresa_id=empresa_id, clave=clave)


class Migration(migrations.Migration):

    dependencies = [
        ('reg_base', '0004_initial'),
        ('reg_actividades', '0002_imagenmapa'),
        ('reg_txtss', '0001_initial'),
        ('reg_construccion', '0002_estado_obra_en_proyecto'),
    ]

    operations = [
        migrations.RunPython(activar_en_uso, migrations.RunPython.noop),
    ]
