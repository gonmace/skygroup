"""Lleva al estándar actual a las empresas que aún tienen la primera versión de la plantilla (la que traía los pasos
«Seguridad» y «Cierre»). Las demás empresas no se tocan: su plantilla es una copia editable."""
from django.db import migrations

CLAVE = 'construccion-base'
OBSOLETOS = ('cb_seguridad', 'cb_cierre')


def actualizar(apps, schema_editor):
    from reg_construccion_base.estandar import sembrar_estandar
    PasoAsignado = apps.get_model('reg_actividades', 'PasoAsignado')
    modelos = {n: apps.get_model('reg_actividades', n) for n in ('Paso', 'PasoWidget', 'Plantilla', 'PasoAsignado')}
    Empresa = apps.get_model('empresas', 'Empresa')
    ids = set(PasoAsignado.objects.filter(plantilla__tipo_registro=CLAVE, paso__nombre__in=OBSOLETOS)
              .values_list('plantilla__empresa_id', flat=True))
    for empresa in Empresa.objects.filter(pk__in=ids):
        sembrar_estandar(empresa, restaurar=True, modelos=modelos)


class Migration(migrations.Migration):

    dependencies = [
        ('reg_construccion_base', '0003_hallazgo_sin_contratista'),
        ('reg_actividades', '0002_imagenmapa'),
        ('empresas', '0009_reporte_de_personal'),
    ]

    operations = [
        migrations.RunPython(actualizar, migrations.RunPython.noop),
    ]
