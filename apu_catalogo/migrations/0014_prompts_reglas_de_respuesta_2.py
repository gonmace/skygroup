from django.db import migrations


def repartir(apps, schema_editor):
    """Los prompts de la carga inicial que quedaron sin «reglas de respuesta» (todo en criterios) se vuelven a repartir.
    Solo los que nadie ha editado (versión 1, de la carga inicial); el texto completo no cambia."""
    from apu_catalogo.prompts_semilla import partir
    Prompt = apps.get_model('apu_catalogo', 'PromptAPU')
    for p in Prompt.objects.filter(version=1, comentario='Carga inicial', reglas=''):
        texto = '\n\n'.join(t.strip() for t in (p.rol, p.criterios) if t and t.strip())
        rol, criterios, reglas = partir(texto)
        if reglas:
            p.rol, p.criterios, p.reglas = rol, criterios, reglas
            p.save(update_fields=['rol', 'criterios', 'reglas'])


class Migration(migrations.Migration):
    dependencies = [('apu_catalogo', '0013_prompts_reglas_de_respuesta')]
    operations = [migrations.RunPython(repartir, migrations.RunPython.noop)]
