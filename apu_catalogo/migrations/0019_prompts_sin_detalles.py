from django.db import migrations


def adaptar(apps, schema_editor):
    """Los pasos de insumos ya no reciben los «Detalles»: solo el alcance aprobado. Los prompts de la carga inicial sin editar
    pasan a hablar del «Alcance del ítem» y suman la regla «lo ya definido no se pregunta». Los editados en la web no se tocan."""
    from apu_catalogo.prompts_semilla import REGLAS_ALCANCE, adaptar_a_alcance
    Prompt = apps.get_model('apu_catalogo', 'PromptAPU')
    for p in Prompt.objects.filter(version=1, comentario='Carga inicial', paso__in=list(REGLAS_ALCANCE)):
        rol, criterios, reglas = adaptar_a_alcance(p.paso, p.rol, p.criterios, p.reglas)
        if (rol, criterios, reglas) != (p.rol, p.criterios, p.reglas):
            p.rol, p.criterios, p.reglas = rol, criterios, reglas
            p.save(update_fields=['rol', 'criterios', 'reglas'])


class Migration(migrations.Migration):
    dependencies = [('apu_catalogo', '0018_item_resumen_alcance')]
    operations = [migrations.RunPython(adaptar, migrations.RunPython.noop)]
