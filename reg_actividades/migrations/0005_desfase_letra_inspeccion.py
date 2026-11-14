from django.db import migrations


def letra_inspeccion(apps, schema_editor):
    # Mapa de desfase de Referencia → Poste: el segundo punto pasa de «P» a «I» (Inspección).
    PasoWidget = apps.get_model('reg_actividades', 'PasoWidget')
    for w in PasoWidget.objects.filter(widget_slug='mapa_2_puntos', paso__nombre='desfase'):
        cfg = w.config or {}
        if cfg.get('label2') == 'P':
            cfg['label2'] = 'I'
            w.config = cfg
            w.save(update_fields=['config'])


class Migration(migrations.Migration):

    dependencies = [
        ('reg_actividades', '0004_mapa_label_referencia'),
    ]

    operations = [
        migrations.RunPython(letra_inspeccion, migrations.RunPython.noop),
    ]
