"""«Construcción» es la plantilla base estándar: se activa en TODAS las empresas existentes y se les siembra su
plantilla de pasos editable. (Las empresas nuevas la reciben al crearse; ver `RegConstruccionBaseConfig.ready`.)"""
from django.db import migrations

CLAVE = 'construccion-base'


def activar(apps, schema_editor):
    from reg_construccion_base.estandar import sembrar_estandar
    Empresa = apps.get_model('empresas', 'Empresa')
    TipoHabilitado = apps.get_model('reg_base', 'TipoHabilitado')
    modelos = {n: apps.get_model('reg_actividades', n) for n in ('Paso', 'PasoWidget', 'Plantilla', 'PasoAsignado')}
    for empresa in Empresa.objects.all():
        _, creado = TipoHabilitado.objects.get_or_create(empresa=empresa, clave=CLAVE)
        if creado:
            sembrar_estandar(empresa, modelos=modelos)


class Migration(migrations.Migration):

    dependencies = [
        ('reg_construccion_base', '0001_initial'),
        ('reg_base', '0005_activar_tipos_en_uso'),
        ('reg_actividades', '0002_imagenmapa'),
        ('empresas', '0009_reporte_de_personal'),
    ]

    operations = [
        migrations.RunPython(activar, migrations.RunPython.noop),
    ]
