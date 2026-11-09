import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('proyectos', '0001_initial'),
        ('reg_base', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(model_name='configregistros', name='tipo_poste'),
        # «Torre» pasa a ser «el tipo con Construcción» (se conserva el valor ya configurado).
        migrations.RenameField(model_name='configregistros', old_name='tipo_torre', new_name='tipo_construccion'),
        migrations.AlterField(
            model_name='configregistros',
            name='tipo_construccion',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+',
                to='proyectos.tipoproyecto', verbose_name='Tipo con Construcción',
                help_text='Opcional. Si lo dejas vacío, Construcción aplica a todos los proyectos.'),
        ),
    ]
