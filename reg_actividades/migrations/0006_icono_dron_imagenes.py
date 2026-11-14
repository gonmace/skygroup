from django.db import migrations


def icono_dron(apps, schema_editor):
    # Último paso de TX/TSS («imagenes»: fotos de dron): su botón lleva el icono de dron en vez de la cámara.
    PasoWidget = apps.get_model('reg_actividades', 'PasoWidget')
    for w in PasoWidget.objects.filter(widget_slug='imgs_desc_widget', paso__nombre='imagenes'):
        cfg = w.config or {}
        if not cfg.get('icono'):
            cfg['icono'] = 'drone'
            w.config = cfg
            w.save(update_fields=['config'])


class Migration(migrations.Migration):

    dependencies = [
        ('reg_actividades', '0005_desfase_letra_inspeccion'),
    ]

    operations = [
        migrations.RunPython(icono_dron, migrations.RunPython.noop),
    ]
