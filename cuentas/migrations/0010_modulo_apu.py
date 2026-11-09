from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('cuentas', '0009_sedes'), ('empresas', '0005_modulo_apu')]

    operations = [
        migrations.AlterField(
            model_name='accesomodulo', name='modulo',
            field=models.CharField(choices=[('reg', 'Registros'), ('tar', 'Tareas'), ('jor', 'Jornadas'), ('msj', 'Mensajería'), ('apu', 'Análisis de Precios Unitarios')], max_length=3),
        ),
    ]
