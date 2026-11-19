from django.db import migrations


def agregar(apps, schema_editor):
    """Los prompts de la carga inicial sin editar (versión 1) suman la regla del alcance del ítem: la clasificación redacta
    el resumen del alcance y los pasos de insumos lo respetan. Los que el superusuario ya editó no se tocan."""
    from apu_catalogo.prompts_semilla import REGLAS_ALCANCE, con_alcance
    Prompt = apps.get_model('apu_catalogo', 'PromptAPU')
    for p in Prompt.objects.filter(version=1, comentario='Carga inicial', paso__in=list(REGLAS_ALCANCE)):
        nuevas = con_alcance(p.paso, p.reglas)
        if nuevas != p.reglas:
            p.reglas = nuevas
            p.save(update_fields=['reglas'])


class Migration(migrations.Migration):
    dependencies = [('apu_catalogo', '0015_quitar_paso_proyecto_claro')]
    operations = [migrations.RunPython(agregar, migrations.RunPython.noop)]
