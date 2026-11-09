import logging

from django.db import transaction
from django.db.models import Count

from . import clasificador
from .models import OTROS, CategoriaActividad, Etiqueta, ItemActividad
from .texto import normalizar

log = logging.getLogger(__name__)


def sembrar_categorias(empresa):
    """Crea las categorías base que falten (idempotente). Nunca pisa lo que la empresa editó."""
    filas = [(c, e, col) for c, e, col, _ in clasificador.BASE] + [clasificador.CATEGORIA_OTROS]
    for orden, (codigo, etiqueta, color) in enumerate(filas):
        CategoriaActividad.objects.get_or_create(
            empresa=empresa, codigo=codigo,
            defaults={'etiqueta': etiqueta, 'color': color, 'orden': orden, 'protegida': True})


def categorias(empresa, solo_activas=False):
    if not CategoriaActividad.objects.filter(empresa=empresa).exists():
        sembrar_categorias(empresa)
    qs = CategoriaActividad.objects.filter(empresa=empresa)
    return qs.filter(activa=True) if solo_activas else qs


@transaction.atomic
def sincronizar_items(reporte):
    """Reemplaza los ítems automáticos del reporte (los asignados a mano se conservan). Idempotente.
    Devuelve {'creados', 'conservados'}."""
    empresa_id = reporte.jornada.empresa_id
    campos = {ItemActividad.Tipo.HECHO: reporte.realizado, ItemActividad.Tipo.PLANIFICADO: reporte.planificado}
    activas = set(categorias(reporte.jornada.empresa, solo_activas=True).values_list('codigo', flat=True))
    creados = conservados = 0
    for tipo, texto in campos.items():
        manuales = list(reporte.items.filter(tipo=tipo, manual=True))
        conservados += len(manuales)
        reporte.items.filter(tipo=tipo, manual=False).delete()
        ocupadas = {i.posicion for i in manuales}
        textos_manuales = {normalizar(i.texto) for i in manuales}
        nuevos, pos = [], 0
        for fragmento in clasificador.dividir(texto):
            if normalizar(fragmento) in textos_manuales:
                continue
            while pos in ocupadas:
                pos += 1
            codigo, palabra = clasificador.clasificar(fragmento)
            if codigo not in activas:               # categoría desactivada por la empresa
                codigo, palabra = OTROS, ''
            nuevos.append(ItemActividad(empresa_id=empresa_id, reporte=reporte, tipo=tipo, posicion=pos, texto=fragmento,
                                        categoria=codigo, palabra=palabra))
            pos += 1
        ItemActividad.objects.bulk_create(nuevos)
        creados += len(nuevos)
    return {'creados': creados, 'conservados': conservados}


def sincronizar_sin_fallar(reporte):
    """Para usar al cerrar la jornada: clasificar nunca debe impedir finalizarla."""
    try:
        sincronizar_items(reporte)
    except Exception:
        log.exception('Fallo clasificando el reporte %s', reporte.pk)


def recategorizar(item, codigo):
    if not categorias(item.empresa).filter(codigo=codigo).exists():
        raise ValueError('Esa categoría no existe.')
    item.categoria, item.manual, item.fuente, item.palabra = codigo, True, ItemActividad.Fuente.MANUAL, ''
    item.save(update_fields=['categoria', 'manual', 'fuente', 'palabra', 'clasificado'])


# ── Etiquetas ────────────────────────────────────────────────────────────────────────────────────
def resolver_etiqueta(empresa, tipo, nombre):
    """get_or_create por (tipo, nombre normalizado) y devuelve la etiqueta canónica; None si está ignorada."""
    nombre = (nombre or '').strip()
    clave = normalizar(nombre)[:120]
    if not clave:
        return None
    etiqueta, _ = Etiqueta.objects.get_or_create(empresa=empresa, tipo=tipo, clave=clave, defaults={'nombre': nombre[:120]})
    raiz = etiqueta.raiz
    return None if etiqueta.ignorada or raiz.ignorada else raiz


class ErrorEtiqueta(ValueError):
    pass


@transaction.atomic
def fusionar(origen, destino):
    """Las variantes de `origen` (y él mismo) pasan a ser alias de `destino`. No se pierde nada."""
    if origen.empresa_id != destino.empresa_id or origen.tipo != destino.tipo:
        raise ErrorEtiqueta('Solo se fusionan etiquetas del mismo tipo.')
    destino = destino.raiz
    if origen.pk == destino.pk:
        raise ErrorEtiqueta('No se puede fusionar una etiqueta consigo misma.')
    Etiqueta.objects.filter(canonica=origen).update(canonica=destino)
    origen.canonica = destino
    origen.save(update_fields=['canonica'])


def separar(etiqueta):
    etiqueta.canonica = None
    etiqueta.save(update_fields=['canonica'])


def renombrar(etiqueta, nombre, codigo=None, color=None):
    nombre = (nombre or '').strip()
    clave = normalizar(nombre)[:120]
    if not clave:
        raise ErrorEtiqueta('El nombre es obligatorio.')
    if Etiqueta.objects.filter(empresa=etiqueta.empresa, tipo=etiqueta.tipo, clave=clave).exclude(pk=etiqueta.pk).exists():
        raise ErrorEtiqueta('Ya existe una etiqueta con ese nombre.')
    etiqueta.nombre, etiqueta.clave = nombre[:120], clave
    campos = ['nombre', 'clave']
    if codigo is not None:
        etiqueta.codigo = codigo.strip()[:40]
        campos.append('codigo')
    if color is not None:
        etiqueta.color = color.strip()[:20]
        campos.append('color')
    etiqueta.save(update_fields=campos)


# ── Etiquetas de proyecto → modelo Proyecto ──────────────────────────────────────────────────────
def etiquetas_pendientes_de_proyecto(empresa):
    """Etiquetas raíz de proyecto que los reportes mencionan y aún no están en el modelo Proyecto."""
    return (Etiqueta.objects.filter(empresa=empresa, tipo=Etiqueta.Tipo.PROYECTO, canonica__isnull=True,
                                    ignorada=False, proyecto__isnull=True)
            .annotate(usos=Count('items', distinct=True)).order_by('nombre'))


@transaction.atomic
def agregar_a_proyectos(empresa, ids):
    """Agrega las etiquetas elegidas al modelo Proyecto. Si ya hay un proyecto activo con el mismo nombre solo
    se vincula (sin duplicar); si no, se crea. Devuelve (creados, vinculados). Idempotente."""
    from proyectos.models import Proyecto
    existentes = {normalizar(p.nombre): p for p in Proyecto.objects.de_empresa(empresa).activos()}
    codigos = {c.lower() for c in Proyecto.objects.de_empresa(empresa).activos().exclude(codigo='')
               .values_list('codigo', flat=True)}
    creados = vinculados = 0
    elegidas = (Etiqueta.objects.select_for_update()       # sin el annotate: FOR UPDATE no admite agregados
                .filter(empresa=empresa, tipo=Etiqueta.Tipo.PROYECTO, canonica__isnull=True, ignorada=False,
                        proyecto__isnull=True, pk__in=ids).order_by('nombre'))
    for e in elegidas:
        clave = normalizar(e.nombre)
        proyecto = existentes.get(clave)
        if proyecto is None:
            codigo = e.codigo if e.codigo and e.codigo.lower() not in codigos else ''
            proyecto = Proyecto.objects.create(empresa=empresa, nombre=e.nombre, codigo=codigo)
            existentes[clave] = proyecto
            if codigo:
                codigos.add(codigo.lower())
            creados += 1
        else:
            vinculados += 1
        e.proyecto = proyecto
        e.save(update_fields=['proyecto'])
    return creados, vinculados
