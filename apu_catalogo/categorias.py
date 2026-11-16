"""Categorías de APU de la empresa: crear, renombrar, fusionar, borrar y reordenar a mano. Sin vistas."""
import re
import unicodedata

from django.db import transaction
from django.db.models import Max

from .models import CategoriaAPU, ItemModelo


def clave(texto):
    """Para comparar nombres: sin tildes, en minúsculas y con los espacios normalizados."""
    sin = unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', sin).strip().lower()


def limpiar(nombre):
    return ' '.join(str(nombre or '').split())[:80]


def existente(empresa, nombre, excluir_pk=None):
    """La categoría de la empresa con ese nombre (sin distinguir mayúsculas, tildes ni espacios), o None."""
    objetivo = clave(nombre)
    if not objetivo:
        return None
    for c in CategoriaAPU.objects.filter(empresa=empresa):
        if c.pk != excluir_pk and clave(c.nombre) == objetivo:
            return c
    return None


def _siguiente_orden(empresa):
    return (CategoriaAPU.objects.filter(empresa=empresa).aggregate(m=Max('orden'))['m'] or 0) + 1


def obtener_o_crear(empresa, nombre):
    """La categoría para un nombre propuesto (p. ej. por la IA): la existente o una nueva al final. None si está vacío."""
    nombre = limpiar(nombre)
    if not clave(nombre):
        return None
    return existente(empresa, nombre) or CategoriaAPU.objects.create(empresa=empresa, nombre=nombre,
                                                                     orden=_siguiente_orden(empresa))


def crear(empresa, nombre):
    """Crea una categoría al final. Lanza ValueError con un mensaje apto para mostrar."""
    nombre = limpiar(nombre)
    if not nombre:
        raise ValueError('Escribe el nombre de la categoría.')
    if existente(empresa, nombre):
        raise ValueError(f'Ya existe una categoría llamada «{nombre}».')
    return CategoriaAPU.objects.create(empresa=empresa, nombre=nombre, orden=_siguiente_orden(empresa))


def renombrar(categoria, nombre):
    nombre = limpiar(nombre)
    if not nombre:
        raise ValueError('Escribe el nombre de la categoría.')
    if existente(categoria.empresa, nombre, excluir_pk=categoria.pk):
        raise ValueError(f'Ya existe una categoría llamada «{nombre}». Si son la misma, usa «Fusionar».')
    categoria.nombre = nombre
    categoria.save(update_fields=['nombre'])
    return categoria


@transaction.atomic
def fusionar(origen, destino):
    """Mueve todos los APU de `origen` a `destino` y borra `origen`. Devuelve cuántos APU se movieron."""
    if origen.pk == destino.pk or origen.empresa_id != destino.empresa_id:
        raise ValueError('Elige otra categoría de la misma empresa.')
    movidos = ItemModelo.objects.filter(categoria=origen).update(categoria=destino)
    origen.delete()
    return movidos


def reordenar(empresa, pk, delta):
    """Sube (delta=-1) o baja (+1) una categoría una posición y deja el orden 1..n sin huecos."""
    cats = list(CategoriaAPU.objects.filter(empresa=empresa).order_by('orden', 'nombre', 'pk'))
    i = next((n for n, c in enumerate(cats) if c.pk == pk), None)
    if i is None:
        return False
    j = i + delta
    if 0 <= j < len(cats):
        cats[i], cats[j] = cats[j], cats[i]
    for n, c in enumerate(cats, start=1):
        if c.orden != n:
            c.orden = n
            c.save(update_fields=['orden'])
    return True


def para_ia(empresa):
    """Nombres de las categorías activas, en el orden de la empresa, como los recibe la IA."""
    return list(CategoriaAPU.objects.filter(empresa=empresa, activo=True).values_list('nombre', flat=True))
