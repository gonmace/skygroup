from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('cuentas', '0007_dominios_correos_bloqueados'), ('empresas', '0003_modulo_mensajeria')]

    operations = [
        migrations.AlterField(
            model_name='accesomodulo', name='modulo',
            field=models.CharField(choices=[('reg', 'Registros'), ('tar', 'Tareas'), ('jor', 'Jornadas'), ('msj', 'Mensajería')], max_length=3),
        ),
    ]
