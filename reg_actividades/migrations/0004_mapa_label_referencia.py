from django.db import migrations


def label_referencia(apps, schema_editor):
    # En los mapas de 2 puntos, la «M» (Mandato) del primer punto pasa a «R» (Referencia).
    PasoWidget = apps.get_model('reg_actividades', 'PasoWidget')
    for w in PasoWidget.objects.filter(widget_slug='mapa_2_puntos'):
        cfg = w.config or {}
        if str(cfg.get('paso1', '')).lower() == 'mandato' and cfg.get('label1') == 'M':
            cfg['label1'] = 'R'
            w.config = cfg
            w.save(update_fields=['config'])
    # Mapa de 1 punto del paso «Mandato»: su letra por defecto era «M».
    for w in PasoWidget.objects.filter(widget_slug='mapa_1p', paso__nombre='mandato'):
        cfg = w.config or {}
        if not cfg.get('label'):
            cfg['label'] = 'R'
            w.config = cfg
            w.save(update_fields=['config'])


class Migration(migrations.Migration):

    dependencies = [
        ('reg_actividades', '0003_paso_mandato_referencia'),
    ]

    operations = [
        migrations.RunPython(label_referencia, migrations.RunPython.noop),
    ]
