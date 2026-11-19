from django.db import migrations


def aplicar(apps, schema_editor):
    """Lleva a cualquier base (producción incluida) las plantillas y prompts tal como están en desarrollo al lanzar: ver
    `prompts_semilla.aplicar_actuales`. No pisa lo que el superusuario ya editó en la web."""
    from apu_catalogo import prompts_semilla
    prompts_semilla.aplicar_actuales(apps.get_model('apu_catalogo', 'PlantillaAPU'), apps.get_model('apu_catalogo', 'PromptAPU'))


class Migration(migrations.Migration):
    dependencies = [('apu_catalogo', '0016_prompts_resumen_alcance')]
    operations = [migrations.RunPython(aplicar, migrations.RunPython.noop)]
