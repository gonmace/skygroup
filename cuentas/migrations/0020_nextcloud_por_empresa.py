import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def vincular_uids_existentes(apps, schema_editor):
    """El `nextcloud_uid` global pasa a ser un vínculo por cada empresa en la que la persona es miembro activa."""
    User, Membresia, Vinculo = (apps.get_model('cuentas', n) for n in ('User', 'Membresia', 'NextcloudVinculo'))
    for user in User.objects.exclude(nextcloud_uid=''):
        for m in Membresia.objects.filter(user=user, activa=True):
            if not Vinculo.objects.filter(empresa_id=m.empresa_id, uid=user.nextcloud_uid).exists():
                Vinculo.objects.get_or_create(empresa_id=m.empresa_id, user=user, defaults={'uid': user.nextcloud_uid})


class Migration(migrations.Migration):

    dependencies = [
        ('cuentas', '0019_nextcloud_alta_automatica'),
        ('empresas', '0010_alter_empresa_modulos_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='NextcloudVinculo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uid', models.CharField(max_length=150, verbose_name='Usuario Nextcloud')),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='nextcloud_vinculos', to='empresas.empresa')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='nextcloud_vinculos', to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': 'vínculo de Nextcloud', 'verbose_name_plural': 'vínculos de Nextcloud'},
        ),
        migrations.AddConstraint(
            model_name='nextcloudvinculo',
            constraint=models.UniqueConstraint(fields=('empresa', 'uid'), name='cuentas_ncvinculo_uid_unico'),
        ),
        migrations.AddConstraint(
            model_name='nextcloudvinculo',
            constraint=models.UniqueConstraint(fields=('empresa', 'user'), name='cuentas_ncvinculo_user_unico'),
        ),
        migrations.RunPython(vincular_uids_existentes, migrations.RunPython.noop),
        migrations.RemoveField(model_name='user', name='nextcloud_uid'),
        # La configuración global no se puede asignar a una empresa: se reemplaza por una por empresa.
        migrations.DeleteModel(name='NextcloudConfig'),
        migrations.CreateModel(
            name='NextcloudConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('activo', models.BooleanField(default=False, verbose_name='Activo')),
                ('servidor_url', models.URLField(blank=True, help_text='Ej. https://sky.redlinegs.com', verbose_name='URL de Nextcloud')),
                ('client_id', models.CharField(blank=True, max_length=200, verbose_name='Client ID')),
                ('client_secret', models.CharField(blank=True, max_length=200, verbose_name='Client secret')),
                ('texto_boton', models.CharField(default='Entrar con Nextcloud', max_length=60, verbose_name='Texto del botón')),
                ('crear_cuentas', models.BooleanField(default=False, help_text='APAGADO por defecto: solo entran con Nextcloud las cuentas que un administrador ya dio de alta (se vinculan solas al primer ingreso). Si lo activas, quien tenga un correo de un dominio permitido (Alta por dominio) se crea sola.', verbose_name='Crear cuentas al primer ingreso')),
                ('grupo_admin', models.CharField(blank=True, default='', help_text='Quien pertenezca a este grupo de Nextcloud entra como Coordinador (administrador) de la empresa. Vacío (por defecto) = todos reciben el cargo del dominio.', max_length=100, verbose_name='Grupo de Nextcloud administrador')),
                ('empresa', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='nextcloud', to='empresas.empresa')),
            ],
            options={'verbose_name': 'configuración de Nextcloud', 'verbose_name_plural': 'configuraciones de Nextcloud'},
        ),
    ]
