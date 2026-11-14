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
CALIDAD_DEFECTO, CALIDAD_MIN, CALIDAD_MAX = 85, 10, 95
CALIDAD_PNG = 85         # al convertir una PNG a JPEG nunca se baja de aquí: ya ahorra ~88 % y menos solo añade artefactos
AHORRO_MINIMO = 0.10     # si no se ahorra al menos esto, la foto no se reescribe (solo añadiría pérdida)
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


class MetadataNoConservable(Exception):
    """La foto lleva algo (EXIF, ICC, XMP, comentario, mapa HDR…) que el nuevo archivo no podría mantener."""


_XMP_PNG = 'XML:com.adobe.xmp'
_IFDS = (0x8769, 0x8825, 0xA005)                     # Exif, GPS, Interoperabilidad
_DESPLAZAMIENTOS = {0x8769, 0x8825, 0xA005, 0x0201, 0x0202}   # punteros internos: cambian al reescribir, no son datos


def calidad_estimada(img):
    """Calidad JPEG aproximada (1-100) con la que se guardó la imagen, según su tabla de cuantización; None si no se sabe.
    La tabla estándar de luminancia promedia 57,7: media = 57,7·escala/100 (34,5 ↔ calidad 70, 7,2 ↔ ~94)."""
    tablas = getattr(img, 'quantization', None)
    if not tablas or 0 not in tablas:
        return None
    escala = (sum(tablas[0]) / len(tablas[0])) / 57.6875 * 100
    return (200 - escala) / 2 if escala <= 100 else 5000 / escala


def _exif_valores(img):
    """Todas las etiquetas EXIF (incluidos Exif, GPS e Interoperabilidad) como {(ifd, etiqueta): valor}."""
    ex = img.getexif()
    valores = {('base', k): v for k, v in ex.items() if k not in _DESPLAZAMIENTOS}
    for ifd in _IFDS:
        try:
            sub = ex.get_ifd(ifd)
        except Exception:
            sub = {}
        valores.update({(ifd, k): v for k, v in sub.items() if k not in _DESPLAZAMIENTOS})
    return valores


def _metadatos(img):
    """Lo que la foto lleva además de los píxeles, como argumentos de `Image.save(…, 'JPEG')`, más su «firma» para
    comprobar después que no se perdió nada. Las PNG aportan su eXIf, ICC, XMP y sus textos (pasan al comentario)."""
    img.load()
    info = img.info
    es_jpeg = img.format in ('JPEG', 'MPO')
    kw = {}
    exif = info.get('exif') if es_jpeg else None
    if exif:
        kw['exif'] = exif                                  # bytes originales: conserva hasta las notas del fabricante
    elif len(img.getexif()):
        kw['exif'] = img.getexif()
    if info.get('icc_profile'):
        kw['icc_profile'] = info['icc_profile']
    xmp = info.get('xmp') or (info.get(_XMP_PNG) or '').encode() or None
    if xmp:
        kw['xmp'] = xmp if isinstance(xmp, bytes) else xmp.encode()
    dpi = info.get('dpi')
    if dpi and all(d and d > 0 for d in dpi):
        kw['dpi'] = dpi
    if es_jpeg:
        comentario = info.get('comment')
    else:
        textos = [f'{k}: {v}' for k, v in info.items() if isinstance(v, str) and k != _XMP_PNG]
        comentario = '\n'.join(textos).encode('utf-8', 'replace') if textos else None
    if comentario:
        kw['comment'] = comentario
    firma = {'exif': _exif_valores(img), 'icc': kw.get('icc_profile'), 'xmp': kw.get('xmp'), 'comment': kw.get('comment')}
    if img.format == 'MPO' and xmp and (b'hdrgm' in xmp or b'GainMap' in xmp):
        raise MetadataNoConservable('mapa de ganancia HDR')   # el fotograma secundario es imagen, no un adorno: no se descarta
    return kw, firma


def _verificar(firma, datos):
    """Reabre el JPEG nuevo y comprueba que conserva TODO lo que traía el original; si falta algo, no se reemplaza."""
    from PIL import Image
    with Image.open(io.BytesIO(datos)) as nuevo:
        nuevo.load()
        exif = _exif_valores(nuevo)
        # repr: hay fotos con racionales 0/0 (NaN, p. ej. GPS vacío) y NaN != NaN aunque los bytes sean idénticos
        faltan = [k for k, v in firma['exif'].items() if k not in exif or repr(exif[k]) != repr(v)]
        if faltan:
            raise MetadataNoConservable(f'EXIF {faltan[:3]}')
        for clave, valor in (('icc', nuevo.info.get('icc_profile')), ('xmp', nuevo.info.get('xmp')),
                             ('comment', nuevo.info.get('comment'))):
            if firma[clave] and firma[clave] != valor:
                raise MetadataNoConservable(clave)


def comprimir_foto(foto, calidad):
    """Vuelve a guardar la foto como JPEG con la calidad pedida, misma resolución y SIN perder metadata.

    - Las JPEG se recomprimen; las PNG (capturas, panorámicas) se CONVIERTEN a JPEG (calidad mínima `CALIDAD_PNG`, el alfa
      se compone sobre blanco y el archivo pasa a `.jpg`).
    - Se conserva el EXIF completo (GPS y fecha incluidos), el perfil ICC, el XMP (dron), el comentario y los DPI, y se
      VERIFICA en el archivo nuevo antes de reemplazar; si algo no se pudiera mantener lanza `MetadataNoConservable` y la
      foto queda intacta.
    - No se recomprime lo que ya está en esa calidad o menos (solo añadiría pérdida) ni si no ahorra `AHORRO_MINIMO`.
    Devuelve los bytes ahorrados (0 si no se tocó). La versión nueva se escribe PRIMERO y solo después se borra la anterior."""
    from PIL import Image
    campo = foto.imagen
    viejo = campo.name
    with campo.open('rb') as f:
        original = f.read()
    with Image.open(io.BytesIO(original)) as img:
        es_jpeg = img.format in ('JPEG', 'MPO')
        if es_jpeg:
            previa = calidad_estimada(img)
            if previa is not None and previa <= calidad + 1:
                return 0                                   # ya está en esa calidad o menos
        else:
            calidad = max(calidad, CALIDAD_PNG)
        kw, firma = _metadatos(img)
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            rgba = img.convert('RGBA')
            img = Image.new('RGB', rgba.size, (255, 255, 255))
            img.paste(rgba, mask=rgba.split()[3])
        elif img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        salida = io.BytesIO()
        img.save(salida, 'JPEG', quality=calidad, optimize=True, **kw)
    datos = salida.getvalue()
    if len(datos) > len(original) * (1 - AHORRO_MINIMO):
        return 0
    _verificar(firma, datos)
    nombre = re.sub(r'^[0-9a-f]{12}-', '', os.path.basename(viejo))   # quita el sufijo aleatorio anterior
    if not nombre.lower().endswith(('.jpg', '.jpeg')) or not es_jpeg:
        nombre = os.path.splitext(nombre)[0] + '.jpg'                # PNG (o JPEG con extensión falsa) → .jpg
    campo.save(nombre, ContentFile(datos), save=False)
    foto.tamano = len(datos)
    foto.save(update_fields=['imagen', 'tamano'])                    # exif_lat/lon/fecha de la base no se tocan
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
    hechas = omitidas = ahorro = sin_ahorro = conservadas = 0
    for foto in _fotos_de_la_empresa(request, ids):
        try:
            ahorrado = comprimir_foto(foto, calidad)
        except MetadataNoConservable as exc:
            logger.warning('Foto %s intacta: no se podía conservar su metadata (%s)', foto.pk, exc)
            conservadas += 1
            continue
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
                         'sin_ahorro': sin_ahorro, 'conservadas': conservadas,
                         'message': mensaje_compresion(hechas, ahorro, sin_ahorro, omitidas, calidad, conservadas)})


def mensaje_compresion(hechas, ahorro, sin_ahorro, con_error, calidad, conservadas=0):
    """Resumen legible: dice POR QUÉ las fotos que no se comprimieron se dejaron como estaban."""
    partes = [f'{hechas} foto(s) comprimida(s), ahorro {ahorro // 1024} KB.']
    if sin_ahorro:
        partes.append(f'{sin_ahorro} ya estaban optimizadas: recomprimir al {calidad} % no las reduce lo suficiente '
                      '(prueba una calidad menor).')
    if conservadas:
        partes.append(f'{conservadas} se dejaron intactas porque no se podía conservar toda su metadata.')
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
