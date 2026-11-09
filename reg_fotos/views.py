import json
import logging
import mimetypes

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponseBadRequest, HttpResponseNotModified, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from empresas.acceso import acceso_modulo
from reg_base import acciones, tipos
from reg_base.alcance import puede_escribir, registros_visibles

from . import servicios
from .models import Foto

logger = logging.getLogger(__name__)
_acceso = acceso_modulo('reg')


def _registro(request, clave, pk):
    """(tipo, registro) dentro del alcance del usuario y con acceso al reporte; si no, 403/404."""
    t = tipos.tipo_de_request(request, clave)
    if not tiene_capacidad(request.user, t.capacidad_ver, request.empresa):
        raise PermissionDenied
    return t, acciones.obtener_registro(request, t.modelo, pk)


def _fotos(registro, etapa):
    ct = ContentType.objects.get_for_model(type(registro))
    return Foto.objects.filter(content_type=ct, object_id=registro.pk, etapa=etapa)


def _respuesta(request, destino, ok, mensaje, status=200, **extra):
    """JSON para clientes AJAX; redirección con mensaje para el formulario normal. Si el formulario trae
    `next` con una ruta interna (p. ej. la página del paso), se vuelve allí en vez de a la galería."""
    siguiente = request.POST.get('next', '')
    if siguiente and url_has_allowed_host_and_scheme(siguiente, allowed_hosts={request.get_host()}):
        destino = siguiente
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': ok, 'message': mensaje, **extra}, status=status if not ok else 200)
    (messages.success if ok else messages.error)(request, mensaje)
    return redirect(destino)


def _exige_metadatos(registro, clave, etapa):
    """¿El botón de fotos de esta etapa exige fecha y ubicación en cada foto? (lo define su configuración)"""
    from reg_actividades.servicios import exige_metadatos
    return exige_metadatos(registro, clave, etapa)


@_acceso
def galeria(request, clave, pk, etapa):
    t, registro = _registro(request, clave, pk)
    return render(request, 'reg_fotos/galeria.html', {
        'tipo': t, 'r': registro, 'etapa': etapa, 'fotos': _fotos(registro, etapa),
        'puede_escribir': puede_escribir(request.user, registro),
        'url_detalle': t.url_detalle,
        'exigir_metadatos': _exige_metadatos(registro, t.clave, etapa),
    })


@require_POST
@_acceso
def subir(request, clave, pk, etapa):
    t, registro = _registro(request, clave, pk)
    acciones.exigir_escritura(request.user, registro)
    destino = 'reg_fotos:galeria'
    archivos = request.FILES.getlist('fotos')
    if not archivos:
        return _respuesta(request, redirect(destino, clave=clave, pk=pk, etapa=etapa).url, False, 'No se recibieron archivos.', 400)
    subidas, errores = [], []
    exigir = _exige_metadatos(registro, t.clave, etapa)
    for f in archivos:
        try:
            foto = servicios.guardar_foto(f, autor=request.user, registro=registro, etapa=etapa,
                                          descripcion=request.POST.get('descripcion', ''), exigir_metadatos=exigir)
            subidas.append({'id': foto.pk, 'exif_lat': foto.exif_lat, 'exif_lon': foto.exif_lon})
        except ValidationError as exc:
            errores.append(f'{f.name}: {exc.messages[0]}')
        except Exception:
            logger.exception('No se pudo guardar la foto %s', f.name)
            errores.append(f'{f.name}: error de almacenamiento.')
    url = redirect(destino, clave=clave, pk=pk, etapa=etapa).url
    if not subidas:
        return _respuesta(request, url, False, ' '.join(errores) or 'No se pudo subir ninguna foto.', 400, photos=[])
    mensaje = f'Se subieron {len(subidas)} foto{"s" if len(subidas) != 1 else ""}.'
    if errores:
        mensaje += ' No se pudieron subir: ' + ' '.join(errores)
    return _respuesta(request, url, True, mensaje, photos=subidas)


def _foto_editable(request, clave, pk, etapa, foto_id):
    t, registro = _registro(request, clave, pk)
    acciones.exigir_escritura(request.user, registro)
    return registro, get_object_or_404(_fotos(registro, etapa), pk=foto_id)


@require_POST
@_acceso
def descripcion(request, clave, pk, etapa, foto_id):
    registro, foto = _foto_editable(request, clave, pk, etapa, foto_id)
    foto.descripcion = request.POST.get('descripcion', '').strip()[:128]
    foto.save(update_fields=['descripcion'])
    return _respuesta(request, redirect('reg_fotos:galeria', clave=clave, pk=pk, etapa=etapa).url, True, 'Descripción guardada.')


@require_POST
@_acceso
def eliminar(request, clave, pk, etapa, foto_id):
    registro, foto = _foto_editable(request, clave, pk, etapa, foto_id)
    url = redirect('reg_fotos:galeria', clave=clave, pk=pk, etapa=etapa).url
    try:
        foto.delete()
    except Exception:
        logger.exception('No se pudo eliminar la foto %s', foto_id)
        return _respuesta(request, url, False, 'No se pudo eliminar la foto (error de almacenamiento).', 502)
    return _respuesta(request, url, True, 'Foto eliminada.')


@require_POST
@_acceso
def orden(request, clave, pk, etapa):
    t, registro = _registro(request, clave, pk)
    acciones.exigir_escritura(request.user, registro)
    try:
        ids = [int(i) for i in json.loads(request.body)['order']]
    except (ValueError, KeyError, TypeError):
        return HttpResponseBadRequest('payload inválido')
    servicios.reordenar(registro, etapa, ids)
    return JsonResponse({'success': True})


# ── Archivos: se sirven solo con acceso al REGISTRO (la ruta genérica de privados está bloqueada) ───────────

def _foto_visible(request, foto_id):
    foto = get_object_or_404(Foto, pk=foto_id, empresa=request.empresa)
    modelo = foto.content_type.model_class()
    t = tipos.tipo_de_modelo(modelo)
    if t is None or not tipos.esta_habilitado(request.empresa, t.clave):
        raise Http404
    if not tiene_capacidad(request.user, t.capacidad_ver, request.empresa):
        raise PermissionDenied
    if not registros_visibles(request.user, request.empresa, modelo.objects.filter(pk=foto.object_id)).exists():
        raise Http404
    return foto


def _servir(request, foto, campo):
    etag = f'"{foto.pk}-{foto.tamano or 0}-{campo.name[-8:]}"'
    if request.headers.get('If-None-Match') == etag:
        return HttpResponseNotModified()
    try:
        archivo = campo.open('rb')
    except Exception:
        raise Http404('No se pudo recuperar el archivo del almacenamiento.')
    mime = mimetypes.guess_type(campo.name)[0] or 'application/octet-stream'
    if not mime.startswith('image/'):
        mime = 'application/octet-stream'
    respuesta = FileResponse(archivo, content_type=mime)
    respuesta['Content-Security-Policy'] = 'sandbox'
    respuesta['X-Content-Type-Options'] = 'nosniff'
    respuesta['Cache-Control'] = 'private, max-age=86400'   # pasó por un permiso por usuario
    respuesta['ETag'] = etag
    return respuesta


@_acceso
def imagen(request, foto_id):
    foto = _foto_visible(request, foto_id)
    return _servir(request, foto, foto.imagen)


@_acceso
def miniatura(request, foto_id):
    foto = _foto_visible(request, foto_id)
    return _servir(request, foto, foto.miniatura or foto.imagen)
