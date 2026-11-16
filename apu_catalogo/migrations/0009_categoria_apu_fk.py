from django.db import migrations


class Migration(migrations.Migration):
    """3/3 · el texto `categoria` se reemplaza por la FK."""

    dependencies = [('apu_catalogo', '0008_categoria_apu_datos')]

    operations = [
        migrations.RemoveField(model_name='itemmodelo', name='categoria'),
        migrations.RenameField(model_name='itemmodelo', old_name='categoria_nueva', new_name='categoria'),
    ]
