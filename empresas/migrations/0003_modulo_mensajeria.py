"""Mensajería pasa a ser un módulo (`msj`): las empresas que ya existen lo reciben activado para no perder el chat."""
from django.core.cache import cache
from django.db import migrations, models

import empresas.models


def activar_en_existentes(apps, schema_editor):
    Empresa = apps.get_model('empresas', 'Empresa')
    for e in Empresa.objects.all():
        if 'msj' not in (e.modulos or []):
            e.modulos = [*(e.modulos or []), 'msj']
            e.save(update_fields=['modulos'])
        try:   # la empresa se cachea por slug (5 min): sin esto la lista vieja seguiría vigente
            cache.delete(f'empresa:slug:{e.slug}')
        except Exception:
            pass


class Migration(migrations.Migration):
    dependencies = [('empresas', '0002_contratista')]

    operations = [
        migrations.AlterField(
            model_name='empresa', name='modulos',
            field=models.JSONField(blank=True, default=empresas.models.modulos_default, help_text='Lista de códigos: reg (Registros), tar (Tareas), jor (Jornadas), msj (Mensajería).', verbose_name='Módulos habilitados'),
        ),
        migrations.RunPython(activar_en_existentes, migrations.RunPython.noop),
    ]
