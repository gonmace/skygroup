"""«Recursos presentes» pasa de dos campos fijos (trabajadores y equipo pesado) a una lista de líneas con mínimo 2.
Solo se cambia el botón donde sigue siendo el estándar antiguo (formulario con `trabajadores`); lo ya cargado se
convierte a líneas («12 trabajadores», «1 retroexcavadora») para no perderlo."""
from django.db import migrations

CONFIG = {'label': 'Recursos presentes', 'numerada': False, 'min_items': 2, 'max_items': 50,
          'placeholder': 'Ej.: 12 trabajadores · 1 retroexcavadora'}


def _texto_trabajadores(valor):
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return f'{valor} trabajadores' if str(valor).strip() else ''
    return f'{int(n) if n == int(n) else n} trabajadores'


def convertir(apps, schema_editor):
    PasoWidget = apps.get_model('reg_actividades', 'PasoWidget')
    DatoPaso = apps.get_model('reg_actividades', 'DatoPaso')
    for pw in PasoWidget.objects.filter(paso__nombre='cb_recursos', widget_slug='form_dinamico_widget'):
        if 'trabajadores' in str((pw.config or {}).get('campos', '')):
            pw.widget_slug, pw.config = 'lista_widget', dict(CONFIG)
            pw.save(update_fields=['widget_slug', 'config'])
    for d in DatoPaso.objects.filter(paso_nombre='cb_recursos'):
        antiguo = (d.datos or {}).get('form_dinamico_widget')
        if antiguo is None:
            continue
        lineas = [_texto_trabajadores(antiguo.get('trabajadores')) if antiguo.get('trabajadores') not in (None, '') else '',
                  str(antiguo.get('equipo_pesado') or '').strip()]
        datos = {k: v for k, v in d.datos.items() if k != 'form_dinamico_widget'}
        if any(lineas) and 'lista_widget' not in datos:
            datos['lista_widget'] = {'entradas': [l for l in lineas if l]}
        d.datos = datos
        d.save(update_fields=['datos'])


class Migration(migrations.Migration):

    dependencies = [
        ('reg_construccion_base', '0006_quitar_ubicacion_del_hallazgo'),
        ('reg_actividades', '0006_icono_dron_imagenes'),
    ]

    operations = [
        migrations.RunPython(convertir, migrations.RunPython.noop),
    ]
