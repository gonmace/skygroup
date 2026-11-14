"""Pantalla «Imágenes» de Registros: todas las fotos de la empresa para borrarlas, comprimirlas o descargarlas.

Solo la usan el superusuario y los administradores de sistema de la empresa (se definen en Plataforma, fuera de la
matriz de cargos). Trabaja sobre el almacenamiento privado (puede ser S3), nunca con rutas de disco."""
import gc
import io
import json
import logging
import os
import re
import tempfile
import zipfile
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from cuentas.capacidades import administra
from reg_base import tipos

from .models import Foto
from .views import _servir

logger = logging.getLogger(__name__)

POR_PAGINA = 60
MAX_ELIMINAR = 100           # por petición: el cliente envía lotes (gunicorn corta a los 60 s)
MAX_COMPRIMIR = 25
MAX_ZIP = 300
CALIDAD_DEFECTO, CALIDAD_MIN, CALIDAD_MAX = 70, 10, 95
ORDENES = {
    '': ('-creada', '-id'), 'antiguas': ('creada', 'id'),
    'mayor': ('-tamano', '-id'), 'menor': ('tamano', 'id'),
}


def puede_gestionar_imagenes(user, empresa):
    """Superusuario o administrador de sistema de la empresa. No depende de ningún cargo ni de la matriz de permisos."""
    if not user.is_authenticated or empresa is None:
        return False
    return user.is_superuser or administra(user, empresa.pk)


def solo_administracion(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        empresa = getattr(request, 'empresa', None)
        if empresa is None or not empresa.tiene_modulo('reg'):
            raise Http404
        if not puede_gestionar_imagenes(request.user, empresa):
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return envoltura


# ── Consulta ──────────────────────────────────────────────────────────────────

def _modelos():
    """{content_type_id: Tipo} de los tipos de registro que existen en la plataforma."""
    return {ContentType.objects.get_for_model(t.modelo).pk: t for t in tipos.todos()}


def _q_proyecto(empresa, proyecto_id, por_ct):
    q = Q(pk__in=[])
    for ct_id, t in por_ct.items():
        ids = t.modelo.objects.filter(empresa=empresa, proyecto_id=proyecto_id).values('pk')
        q |= Q(content_type_id=ct_id, object_id__in=ids)
    return q


def _fotos(request, por_ct):
    empresa = request.empresa
    qs = Foto.objects.filter(empresa=empresa, content_type_id__in=list(por_ct))
    g = request.GET
    tipo = g.get('tipo', '')
    ct_de = {t.clave: ct for ct, t in por_ct.items()}
    if tipo in ct_de:
        qs = qs.filter(content_type_id=ct_de[tipo])
    if g.get('proyecto', '').isdigit():
        qs = qs.filter(_q_proyecto(empresa, int(g['proyecto']), por_ct))
    if g.get('etapa'):
        qs = qs.filter(etapa=g['etapa'])
    for campo, op in (('min', 'gte'), ('max', 'lte')):
        try:
            qs = qs.filter(**{f'tamano__{op}': int(float(g.get(f'kb_{campo}', '')) * 1024)})
        except ValueError:
            pass
    return qs.order_by(*ORDENES.get(g.get('orden', ''), ORDENES['']))


def _con_registro(fotos, por_ct):
    """Adjunta a cada foto de la página su registro, proyecto y tipo (una consulta por tipo, no una por foto)."""
    ids = {}
    for f in fotos:
        ids.setdefault(f.content_type_id, set()).add(f.object_id)
    registros = {ct: por_ct[ct].modelo.objects.filter(pk__in=pks).select_related('proyecto').in_bulk()
                 for ct, pks in ids.items()}
    for f in fotos:
        f.reg = registros[f.content_type_id].get(f.object_id)
        f.tipo = por_ct[f.content_type_id]
        f.url_registro = reverse(f.tipo.url_detalle, args=[f.object_id]) if f.reg else ''
    return fotos


def _opciones(empresa, por_ct):
    """Proyectos y etapas que tienen fotos, para los filtros."""
    base = Foto.objects.filter(empresa=empresa, content_type_id__in=list(por_ct))
    etapas = list(base.order_by('etapa').values_list('etapa', flat=True).distinct())
    proyectos = {}
    for ct_id, t in por_ct.items():
        con_fotos = base.filter(content_type_id=ct_id).values('object_id')
        for p in (t.modelo.objects.filter(empresa=empresa, pk__in=con_fotos, proyecto__isnull=False)
                  .values('proyecto_id', 'proyecto__codigo', 'proyecto__nombre').distinct()):
            proyectos[p['proyecto_id']] = (p['proyecto__codigo'] or '', p['proyecto__nombre'])
    return etapas, sorted(((pk, c, n) for pk, (c, n) in proyectos.items()), key=lambda x: (x[1], x[2]))


@solo_administracion
def lista(request):
    por_ct = _modelos()
    qs = _fotos(request, por_ct)
    pagina = Paginator(qs, POR_PAGINA).get_page(request.GET.get('page'))
    _con_registro(list(pagina.object_list), por_ct)
    etapas, proyectos = _opciones(request.empresa, por_ct)
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'reg_fotos/imagenes.html', {
        'pagina': pagina, 'total': pagina.paginator.count, 'etapas': etapas, 'proyectos': proyectos,
        'tipos': [(t.clave, t.nombre) for t in por_ct.values()], 'filtros': request.GET,
        'qs_sin_pagina': params.urlencode(), 'calidad': CALIDAD_DEFECTO,
        'limites': {'eliminar': MAX_ELIMINAR, 'comprimir': MAX_COMPRIMIR, 'zip': MAX_ZIP},
    })


# ── Archivos (el almacenamiento privado solo se sirve por vistas con permiso) ─────

def _foto(request, foto_id):
    return get_object_or_404(Foto, pk=foto_id, empresa=request.empresa)


@solo_administracion
def archivo(request, foto_id):
    foto = _foto(request, foto_id)
    return _servir(request, foto, foto.imagen)


@solo_administracion
def miniatura(request, foto_id):
    foto = _foto(request, foto_id)
    return _servir(request, foto, foto.miniatura or foto.imagen)


# ── Acciones en lote ──────────────────────────────────────────────────────────

def _ids(request, maximo):
    """(ids, error): ids enteros del cuerpo JSON, sin repetir y acotados al lote máximo."""
    try:
        datos = json.loads(request.body or b'{}')
    except ValueError:
        return None, JsonResponse({'success': False, 'message': 'Petición inválida.'}, status=400)
    ids = list(dict.fromkeys(int(i) for i in datos.get('ids', []) if str(i).isdigit()))
    if not ids:
        return None, JsonResponse({'success': False, 'message': 'No se seleccionó ninguna foto.'}, status=400)
    if len(ids) > maximo:
        return None, JsonResponse({'success': False, 'message': f'Máximo {maximo} fotos por lote.'}, status=400)
    return (ids, datos), None


def _fotos_de_la_empresa(request, ids):
    return list(Foto.objects.filter(pk__in=ids, empresa=request.empresa, content_type_id__in=list(_modelos())))


def _bloqueada(foto):
    """Las fotos de un registro concluido (solo lectura) no se ELIMINAN: el reporte ya está emitido. Comprimirlas sí
    se permite: no cambia su contenido (misma resolución y EXIF) y es justo donde está casi todo el peso."""
    reg = foto.registro
    return reg is not None and bool(getattr(reg, 'concluido', False))


def _nombre_en_zip(foto, usados):
    reg = getattr(foto, 'reg', None)
    proyecto = getattr(reg, 'proyecto', None)
    carpeta = slugify(proyecto.codigo or proyecto.nombre) if proyecto else 'sin-proyecto'
    ext = os.path.splitext(foto.imagen.name)[1].lower() or '.jpg'
    fecha = reg.fecha.strftime('%Y%m%d') if reg is not None and getattr(reg, 'fecha', None) else foto.creada.strftime('%Y%m%d')
    base = f'{carpeta or "sin-proyecto"}/{fecha}_{slugify(foto.etapa) or "foto"}_{foto.pk}'
    n = usados.get(base, 0)
    usados[base] = n + 1
    return f'{base}{f"_{n}" if n else ""}{ext}'


@require_POST
@solo_administracion
def descargar(request):
    parsed, error = _ids(request, MAX_ZIP)
    if error:
        return error
    ids, _ = parsed
    fotos = _fotos_de_la_empresa(request, ids)
    _con_registro(fotos, _modelos())
    # Disco temporal (no RAM): un ZIP de cientos de fotos no debe vivir en memoria. Las fotos ya están
    # comprimidas, así que se guardan sin recomprimir.
    tmp = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    usados, escritas = {}, 0
    with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_STORED) as zf:
        for foto in fotos:
            try:
                with foto.imagen.open('rb') as f:
                    zf.writestr(_nombre_en_zip(foto, usados), f.read())
                escritas += 1
            except Exception:
                logger.exception('No se pudo leer la foto %s para el ZIP', foto.pk)
    if not escritas:
        return JsonResponse({'success': False, 'message': 'No se pudo leer ninguna de las fotos seleccionadas.'}, status=404)
    tmp.seek(0)
    logger.info('imágenes: %s descargó %s foto(s) de %s', request.user.pk, escritas, request.empresa.slug)
    return FileResponse(tmp, as_attachment=True, filename='fotos.zip', content_type='application/zip')


def comprimir_foto(foto, calidad):
    """Vuelve a guardar la foto JPEG con menos calidad (misma resolución, conserva el EXIF).

    Devuelve los bytes ahorrados; 0 si no se tocó (no es JPEG, o no se reducía). La nueva versión se escribe PRIMERO
    y solo después se borra la anterior, así un fallo a medias nunca deja la foto sin archivo."""
    from PIL import Image
    campo = foto.imagen
    viejo = campo.name
    if not viejo.lower().endswith(('.jpg', '.jpeg')):
        return 0
    with campo.open('rb') as f:
        original = f.read()
    with Image.open(io.BytesIO(original)) as img:
        exif = img.info.get('exif', b'')
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        salida = io.BytesIO()
        img.save(salida, 'JPEG', quality=calidad, optimize=True, exif=exif)
    datos = salida.getvalue()
    if len(datos) >= len(original):
        return 0
    nombre = re.sub(r'^[0-9a-f]{12}-', '', os.path.basename(viejo))   # quita el sufijo aleatorio anterior
    campo.save(nombre, ContentFile(datos), save=False)
    foto.tamano = len(datos)
    foto.save(update_fields=['imagen', 'tamano'])
    try:
        campo.storage.delete(viejo)
    except Exception:
        logger.exception('No se pudo borrar la versión anterior %s', viejo)
    return len(original) - len(datos)


@require_POST
@solo_administracion
def comprimir(request):
    parsed, error = _ids(request, MAX_COMPRIMIR)
    if error:
        return error
    ids, datos = parsed
    try:
        calidad = max(CALIDAD_MIN, min(int(datos.get('quality', CALIDAD_DEFECTO)), CALIDAD_MAX))
    except (TypeError, ValueError):
        calidad = CALIDAD_DEFECTO
    hechas = omitidas = ahorro = sin_ahorro = no_jpeg = 0
    for foto in _fotos_de_la_empresa(request, ids):
        if not foto.imagen.name.lower().endswith(('.jpg', '.jpeg')):
            no_jpeg += 1
            continue
        try:
            ahorrado = comprimir_foto(foto, calidad)
        except Exception:
            logger.exception('No se pudo comprimir la foto %s', foto.pk)
            omitidas += 1
            continue
        if ahorrado:
            hechas += 1
        else:
            sin_ahorro += 1
        ahorro += ahorrado
        gc.collect()          # libera el bitmap decodificado antes de la siguiente foto
    logger.info('imágenes: %s comprimió %s foto(s) de %s (%s bytes)', request.user.pk, hechas, request.empresa.slug, ahorro)
    return JsonResponse({'success': True, 'comprimidas': hechas, 'omitidas': omitidas, 'ahorro': ahorro,
                         'sin_ahorro': sin_ahorro, 'no_jpeg': no_jpeg,
                         'message': mensaje_compresion(hechas, ahorro, sin_ahorro, no_jpeg, omitidas, calidad)})


def mensaje_compresion(hechas, ahorro, sin_ahorro, no_jpeg, con_error, calidad):
    """Resumen legible: dice POR QUÉ las fotos que no se comprimieron se dejaron como estaban."""
    partes = [f'{hechas} foto(s) comprimida(s), ahorro {ahorro // 1024} KB.']
    if sin_ahorro:
        partes.append(f'{sin_ahorro} ya estaban optimizadas: recomprimir al {calidad} % no las hace más livianas '
                      '(prueba una calidad menor).')
    if no_jpeg:
        partes.append(f'{no_jpeg} no son JPEG (PNG u otro formato): no se tocan.')
    if con_error:
        partes.append(f'{con_error} con error.')
    return ' '.join(partes)


@require_POST
@solo_administracion
def eliminar(request):
    parsed, error = _ids(request, MAX_ELIMINAR)
    if error:
        return error
    ids, _ = parsed
    borradas = omitidas = 0
    for foto in _fotos_de_la_empresa(request, ids):
        if _bloqueada(foto):
            omitidas += 1
            continue
        try:
            foto.delete()     # la señal post_delete borra también los archivos del almacenamiento
            borradas += 1
        except Exception:
            logger.exception('No se pudo eliminar la foto %s', foto.pk)
            omitidas += 1
    logger.info('imágenes: %s eliminó %s foto(s) de %s', request.user.pk, borradas, request.empresa.slug)
    return JsonResponse({'success': True, 'eliminadas': borradas, 'omitidas': omitidas,
                         'message': f'{borradas} foto(s) eliminada(s).'
                                    + (f' {omitidas} omitida(s) (registro concluido o error de almacenamiento).' if omitidas else '')})
