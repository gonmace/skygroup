from django.db import migrations


def asignar(apps, schema_editor):
    """Los borradores y APU anteriores se generaron con los prompts genéricos, que pasaron a ser los de «Obras civiles»."""
    Plantilla = apps.get_model('apu_catalogo', 'PlantillaAPU')
    base = Plantilla.objects.filter(activo=True).order_by('orden').first()
    if base is None:
        return
    apps.get_model('apu_generador', 'APUBorrador').objects.filter(plantilla__isnull=True).update(plantilla=base)
    apps.get_model('apu_catalogo', 'ItemModelo').objects.filter(plantilla__isnull=True).update(plantilla=base)


class Migration(migrations.Migration):
    dependencies = [('apu_generador', '0002_plantillas_de_apu'), ('apu_catalogo', '0012_plantillas_de_apu_datos')]
    operations = [migrations.RunPython(asignar, migrations.RunPython.noop)]
