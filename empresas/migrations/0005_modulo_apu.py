"""Nuevo módulo `apu` (Análisis de Precios Unitarios), por ahora «Próximamente»: las empresas existentes lo reciben
activado para que vean el aviso en el lanzador."""
from django.core.cache import cache
from django.db import migrations, models

import empresas.models


def activar_en_existentes(apps, schema_editor):
    for e in apps.get_model('empresas', 'Empresa').objects.all():
        if 'apu' not in (e.modulos or []):
            e.modulos = [*(e.modulos or []), 'apu']
            e.save(update_fields=['modulos'])
        try:   # la empresa se cachea por slug (5 min)
            cache.delete(f'empresa:slug:{e.slug}')
        except Exception:
            pass


class Migration(migrations.Migration):
    dependencies = [('empresas', '0004_sedes')]

    operations = [
        migrations.AlterField(
            model_name='empresa', name='modulos',
            field=models.JSONField(blank=True, default=empresas.models.modulos_default, help_text='Lista de códigos: reg (Registros), tar (Tareas), jor (Jornadas), msj (Mensajería), apu (Análisis de Precios Unitarios).', verbose_name='Módulos habilitados'),
        ),
        migrations.RunPython(activar_en_existentes, migrations.RunPython.noop),
    ]
