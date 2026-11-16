from django.db import migrations, models
import django.db.models.deletion


def copiar_a_cada_empresa(apps, schema_editor):
    """Lo que hoy está en las credenciales de la plataforma pasa a cada empresa existente (nada deja de funcionar);
    después cada empresa puede tener las suyas."""
    Plataforma = apps.get_model('cuentas', 'CredencialesPlataforma')
    Empresa = apps.get_model('empresas', 'Empresa')
    Nueva = apps.get_model('cuentas', 'CredencialesEmpresa')
    p = Plataforma.objects.first()
    if p is None or not (p.google_maps_api_key or p.n8n_api_url or p.n8n_api_key):
        return
    for e in Empresa.objects.all():
        Nueva.objects.get_or_create(empresa=e, defaults={
            'google_maps_api_key': p.google_maps_api_key, 'n8n_api_url': p.n8n_api_url, 'n8n_api_key': p.n8n_api_key})


class Migration(migrations.Migration):

    dependencies = [
        ('cuentas', '0025_clave_n8n_larga'),
        ('empresas', '0011_empresa_logo_proveedor'),
    ]

    operations = [
        migrations.CreateModel(
            name='CredencialesEmpresa',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('google_maps_api_key', models.CharField(blank=True, help_text='Se guarda en la base de datos. Debe tener habilitada la «Maps Static API» en Google Cloud.', max_length=255, verbose_name='Clave de Google Maps (Static Maps API)')),
                ('n8n_api_url', models.CharField(blank=True, help_text='Base de la instancia de n8n, sin /api/v1. Ej.: https://n8n.tuempresa.com', max_length=255, verbose_name='URL de n8n (para medir el consumo de IA)')),
                ('n8n_api_key', models.CharField(blank=True, help_text='Se crea en n8n → Settings → n8n API. Con ella se leen los tokens de cada ejecución de APU.', max_length=1024, verbose_name='API key de n8n')),
                ('actualizada', models.DateTimeField(auto_now=True)),
                ('empresa', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='credenciales', to='empresas.empresa')),
            ],
            options={'verbose_name': 'credenciales de la empresa', 'verbose_name_plural': 'credenciales de las empresas'},
        ),
        migrations.RunPython(copiar_a_cada_empresa, migrations.RunPython.noop),
        migrations.DeleteModel(name='CredencialesPlataforma'),
    ]
