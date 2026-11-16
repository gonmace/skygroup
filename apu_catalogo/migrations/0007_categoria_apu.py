import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """1/3 · crea `CategoriaAPU` y una FK provisional (`categoria_nueva`); el texto actual sigue en `categoria`."""

    dependencies = [
        ('apu_catalogo', '0006_precios_estimados'),
        ('empresas', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CategoriaAPU',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=80, verbose_name='Nombre')),
                ('orden', models.PositiveIntegerField(default=0, verbose_name='Orden')),
                ('activo', models.BooleanField(default=True, verbose_name='Activa')),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='apu_categorias', to='empresas.empresa')),
            ],
            options={'verbose_name': 'Categoría de APU', 'verbose_name_plural': 'Categorías de APU',
                     'ordering': ['orden', 'nombre']},
        ),
        migrations.AddConstraint(
            model_name='categoriaapu',
            constraint=models.UniqueConstraint(fields=('empresa', 'nombre'), name='apu_categoria_nombre_unico'),
        ),
        migrations.AddField(
            model_name='itemmodelo',
            name='categoria_nueva',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='items', to='apu_catalogo.categoriaapu', verbose_name='Categoría'),
        ),
    ]
