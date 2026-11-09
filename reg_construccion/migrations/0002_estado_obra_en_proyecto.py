from django.db import migrations, models

A_PROYECTO = {'construccion': 'CONSTRUCCION', 'paralizado': 'PARALIZADO',
              'cancelado': 'CANCELADO', 'concluido': 'CONCLUIDO'}


def al_proyecto(apps, schema_editor):
    """El estado de la última visita de cada proyecto pasa a ser el estado del proyecto."""
    Reg = apps.get_model('reg_construccion', 'RegConstruccion')
    Proyecto = apps.get_model('proyectos', 'Proyecto')
    vistos = set()
    for pid, estado in (Reg.objects.filter(proyecto__isnull=False, is_deleted=False)
                        .order_by('-fecha', '-id').values_list('proyecto_id', 'estado_obra')):
        if pid in vistos:
            continue
        vistos.add(pid)
        if estado in A_PROYECTO:
            Proyecto.objects.filter(pk=pid).update(estado=A_PROYECTO[estado])


def a_la_visita(apps, schema_editor):
    Reg = apps.get_model('reg_construccion', 'RegConstruccion')
    inverso = {v: k for k, v in A_PROYECTO.items()}
    for nuevo, viejo in inverso.items():
        Reg.objects.filter(proyecto__estado=nuevo).update(estado_obra=viejo)


class Migration(migrations.Migration):
    dependencies = [
        ('reg_construccion', '0001_initial'),
        ('proyectos', '0004_estados_unificados'),
    ]
    operations = [
        migrations.RunPython(al_proyecto, a_la_visita),
        migrations.RemoveField(model_name='regconstruccion', name='estado_obra'),
    ]
