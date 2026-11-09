from django.db import migrations, models

MAPA = {'PLANIFICADO': 'INGENIERIA', 'ACTIVO': 'CONSTRUCCION', 'PAUSADO': 'PARALIZADO', 'CERRADO': 'CONCLUIDO'}


def adelante(apps, schema_editor):
    Proyecto = apps.get_model('proyectos', 'Proyecto')
    for viejo, nuevo in MAPA.items():
        Proyecto.objects.filter(estado=viejo).update(estado=nuevo)


def atras(apps, schema_editor):
    Proyecto = apps.get_model('proyectos', 'Proyecto')
    inverso = {'INGENIERIA': 'PLANIFICADO', 'CONSTRUCCION': 'ACTIVO', 'PARALIZADO': 'PAUSADO',
               'CONCLUIDO': 'CERRADO', 'CANCELADO': 'CERRADO'}
    for nuevo, viejo in inverso.items():
        Proyecto.objects.filter(estado=nuevo).update(estado=viejo)


class Migration(migrations.Migration):
    dependencies = [('proyectos', '0003_codigo_opcional_sin_coordenadas')]
    operations = [
        migrations.AlterField(
            model_name='proyecto', name='estado',
            field=models.CharField(max_length=12, default='CONSTRUCCION', choices=[
                ('INGENIERIA', 'Ingeniería'), ('CONSTRUCCION', 'Construcción'), ('PARALIZADO', 'Paralizado'),
                ('CONCLUIDO', 'Concluido'), ('CANCELADO', 'Cancelado')]),
        ),
        migrations.RunPython(adelante, atras),
    ]
