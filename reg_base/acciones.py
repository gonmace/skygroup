"""Acciones comunes a todos los registros (TX/TSS, Construcción…)."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404

from cuentas.capacidades import tiene_capacidad

from .alcance import puede_escribir, registros_visibles


def obtener_registro(request, modelo, pk, *select):
    """Registro de la empresa del request y dentro del alcance del usuario, o 404 (no se revela que existe)."""
    qs = registros_visibles(request.user, request.empresa, modelo.objects.select_related('proyecto', 'user', *select))
    return get_object_or_404(qs, pk=pk)


def alternar_concluido(user, registro):
    """Concluye o reabre. Devuelve el nuevo valor de `concluido`. Concluir exige `reg.concluir` y reabrir
    `reg.reabrir`; ambos dentro del alcance (lo garantiza `obtener_registro`)."""
    capacidad = 'reg.reabrir' if registro.concluido else 'reg.concluir'
    if not tiene_capacidad(user, capacidad, registro.empresa):
        raise PermissionDenied
    registro.concluido = not registro.concluido
    registro.save(update_fields=['concluido', 'updated_at'])
    return registro.concluido


def formatear_registro(registro):
    """Borra todo lo cargado en el registro (fotos, imágenes de mapa y datos de pasos) y lo deja abierto.
    Devuelve `{'fotos': n, 'mapas': n, 'pasos': n}`. Es destructivo: solo el superusuario."""
    from django.contrib.contenttypes.models import ContentType

    from reg_actividades.models import DatoPaso, ImagenMapa

    ct = ContentType.objects.get_for_model(type(registro))
    with transaction.atomic():
        fotos = list(registro.fotos.all())
        for foto in fotos:
            foto.delete()   # uno a uno: la señal de Foto elimina también los archivos del storage
        mapas = list(ImagenMapa.objects.filter(content_type=ct, object_id=registro.pk))
        for mapa in mapas:
            if mapa.imagen:
                mapa.imagen.delete(save=False)
            mapa.delete()
        pasos, _ = DatoPaso.objects.filter(content_type=ct, object_id=registro.pk).delete()
        registro.concluido = False
        registro.save(update_fields=['concluido', 'updated_at'])
    return {'fotos': len(fotos), 'mapas': len(mapas), 'pasos': pasos}


def exigir_escritura(user, registro):
    """Lanza PermissionDenied si no puede cargar datos en el registro (sin permiso, fuera de alcance o concluido)."""
    if not puede_escribir(user, registro):
        raise PermissionDenied


def exigir_superusuario(user):
    if not user.is_superuser:
        raise PermissionDenied


def contexto_imagenes(registro, recientes=6, por_etapa=False):
    """Contexto de `reg_base/_imagenes.html`: total y últimas imágenes; con `por_etapa`, también el total por etapa.
    La estructura de la tarjeta es la misma en todos los registros; lo que muestra lo decide cada tipo."""
    from django.db.models import Count
    from reg_fotos.servicios import fotos_de
    fotos = fotos_de(registro)
    ctx = {'fotos_total': fotos.count(), 'fotos_recientes': list(fotos.order_by('-id')[:recientes])}
    if por_etapa:
        ctx['fotos_etapas'] = [{'etapa': e['etapa'], 'nombre': e['etapa'].replace('_', ' ').capitalize(), 'n': e['n']}
                               for e in fotos.order_by().values('etapa').annotate(n=Count('id')).order_by('etapa')]
    return ctx
