import re
import unicodedata

from django.db import migrations


def _clave(texto):
    sin = unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', sin).strip().lower()


def texto_a_categorias(apps, schema_editor):
    """2/3 · una categoría por cada texto distinto de la empresa (sin duplicar por mayúsculas, tildes ni espacios)."""
    Item, Cat = apps.get_model('apu_catalogo', 'ItemModelo'), apps.get_model('apu_catalogo', 'CategoriaAPU')
    por_empresa = {}
    for it in Item.objects.exclude(categoria='').order_by('pk'):
        cats = por_empresa.setdefault(it.empresa_id, {})
        clave = _clave(it.categoria)
        if not clave:
            continue
        if clave not in cats:
            cats[clave] = Cat.objects.create(empresa_id=it.empresa_id, nombre=' '.join(it.categoria.split())[:80],
                                             orden=len(cats) + 1)
        Item.objects.filter(pk=it.pk).update(categoria_nueva=cats[clave])


class Migration(migrations.Migration):

    dependencies = [('apu_catalogo', '0007_categoria_apu')]

    operations = [migrations.RunPython(texto_a_categorias, migrations.RunPython.noop)]
