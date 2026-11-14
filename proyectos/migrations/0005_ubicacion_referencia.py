from django.db import migrations


def a_referencia(apps, schema_editor):
    U = apps.get_model('proyectos', 'ProyectoUbicacion')
    con_ref = set(U.objects.filter(etiqueta='Referencia').values_list('proyecto_id', flat=True))
    for u in U.objects.filter(etiqueta__in=['Mandato', 'Principal']).order_by('id'):
        if u.proyecto_id in con_ref:
            continue
        u.etiqueta = 'Referencia'
        u.save(update_fields=['etiqueta'])
        con_ref.add(u.proyecto_id)


class Migration(migrations.Migration):

    dependencies = [
        ('proyectos', '0004_estados_unificados'),
    ]

    operations = [
        migrations.RunPython(a_referencia, migrations.RunPython.noop),
    ]
