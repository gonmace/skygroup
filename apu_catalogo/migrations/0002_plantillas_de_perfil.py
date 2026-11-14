"""Siembra las plantillas de perfil de la plataforma (empresa vacía): Bolivia y Chile."""
import copy

from django.db import migrations

from apu_motor.plantillas import BOLIVIA_ESTANDAR, CHILE_ESTANDAR

PLANTILLAS = [(BOLIVIA_ESTANDAR, 'BO'), (CHILE_ESTANDAR, 'CL')]


def sembrar(apps, schema_editor):
    Perfil = apps.get_model('apu_catalogo', 'PerfilCalculo')
    for datos, pais in PLANTILLAS:
        datos = copy.deepcopy(datos)
        nombre, moneda = datos.pop('perfil'), datos.pop('moneda')
        Perfil.objects.get_or_create(empresa=None, nombre=nombre, defaults={'pais': pais, 'moneda': moneda, 'datos': datos})


class Migration(migrations.Migration):
    dependencies = [('apu_catalogo', '0001_initial')]
    operations = [migrations.RunPython(sembrar, migrations.RunPython.noop)]
