from django.db import migrations


def cargar(apps, schema_editor):
    from apu_catalogo import prompts_semilla
    prompts_semilla.cargar(apps.get_model('apu_catalogo', 'PlantillaAPU'), apps.get_model('apu_catalogo', 'PromptAPU'))


class Migration(migrations.Migration):
    dependencies = [('apu_catalogo', '0011_plantillas_de_apu')]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
