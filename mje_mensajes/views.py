"""Vistas del chat. Devuelven fragmentos HTML (o JSON) que `static/js/mensajeria.js` pinta en el panel
lateral; la página `mensajes/` solo abre ese panel (destino de las notificaciones)."""
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotModified, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_GET, require_POST

from empresas.acceso import acceso_modulo

from . import servicios
from .models import AdjuntoMensaje, Conversacion, Mensaje

# Tipos que se sirven inline con seguridad (rasters y PDF); el resto se descarga.
INLINE_SEGUROS = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp', 'application/pdf'}


def _conv(request, pk):
    """La conversación si existe en la empresa Y la persona puede verla; si no, 404 (sin revelar que existe)."""
    conv = get_object_or_404(
        Conversacion.objects.select_related('proyecto', 'directo_a', 'directo_b', 'empresa'),
        pk=pk, empresa=request.empresa)
    if not servicios.puede_ver(request.user, conv):
        raise Http404
    return conv


def _mensajes_qs(conv):
    return conv.mensajes.select_related('autor').prefetch_related('adjuntos', 'menciones')


def _fragmento_mensajes(request, conv, mensajes):
    return render_to_string('mje_mensajes/_mensajes.html', {'mensajes': mensajes, 'conv': conv}, request=request)


@acceso_modulo('msj', 'msj.usar')
def bandeja(request):
    """La mensajería no tiene página propia: es una ventana flotante. Este enlace (destino de las notificaciones,
    `/mensajes/?c=<id>`) lleva al inicio con la ventana abierta en esa conversación."""
    c = request.GET.get('c', '')
    return redirect(f"{reverse('home')}?{urlencode({'c': c} if c.isdigit() else {'msj': 1})}")


@acceso_modulo('msj', 'msj.usar')
@require_GET
def panel(request):
    datos = servicios.conversaciones_visibles(request.user, request.empresa)
    return render(request, 'mje_mensajes/_lista.html', datos)


@acceso_modulo('msj', 'msj.usar')
@require_GET
def resumen(request):
    total, por_conv = servicios.no_leidos(request.user, request.empresa)
    return JsonResponse({'total': total, 'por_conv': {str(k): v for k, v in por_conv.items()}})


@acceso_modulo('msj', 'msj.usar')
@require_GET
def conversacion(request, pk):
    conv = _conv(request, pk)
    mensajes = list(_mensajes_qs(conv).order_by('-id')[:servicios.POR_PAGINA + 1])
    hay_mas = len(mensajes) > servicios.POR_PAGINA
    mensajes = mensajes[:servicios.POR_PAGINA][::-1]
    return render(request, 'mje_mensajes/_conversacion.html', {
        'conv': conv, 'titulo': conv.titulo(request.user), 'hay_mas': hay_mas, 'otro': conv.otro(request.user),
        'mensajes': mensajes, 'maximo': servicios.MAX_TEXTO, 'max_adjuntos': servicios.MAX_ADJUNTOS,
        'ultimo_id': mensajes[-1].pk if mensajes else 0, 'primero_id': mensajes[0].pk if mensajes else 0,
        'es_directo': conv.tipo == Conversacion.Tipo.DIRECTO,
    })


@acceso_modulo('msj', 'msj.usar')
@require_GET
def mas_antiguos(request, pk):
    conv = _conv(request, pk)
    antes = int(request.GET.get('antes') or 0)
    mensajes = list(_mensajes_qs(conv).filter(id__lt=antes).order_by('-id')[:servicios.POR_PAGINA + 1])
    hay_mas = len(mensajes) > servicios.POR_PAGINA
    mensajes = mensajes[:servicios.POR_PAGINA][::-1]
    respuesta = HttpResponse(_fragmento_mensajes(request, conv, mensajes))
    respuesta['X-Hay-Mas'] = '1' if hay_mas else '0'
    respuesta['X-Primero-Id'] = str(mensajes[0].pk) if mensajes else ''
    return respuesta


@acceso_modulo('msj', 'msj.usar')
@require_GET
def nuevos(request, pk):
    conv = _conv(request, pk)
    despues = int(request.GET.get('despues') or 0)
    mensajes = list(_mensajes_qs(conv).filter(id__gt=despues).order_by('id')[:100])
    respuesta = HttpResponse(_fragmento_mensajes(request, conv, mensajes))
    respuesta['X-Ultimo-Id'] = str(mensajes[-1].pk) if mensajes else ''
    return respuesta


@acceso_modulo('msj', 'msj.usar')
@require_POST
def enviar(request, pk):
    conv = _conv(request, pk)
    try:
        msg = servicios.enviar(conv, request.user, request.POST.get('texto', ''), request.FILES.getlist('files'))
    except servicios.ErrorMensaje as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    msg = _mensajes_qs(conv).get(pk=msg.pk)
    return JsonResponse({'ok': True, 'id': msg.pk, 'html': _fragmento_mensajes(request, conv, [msg])})


@acceso_modulo('msj', 'msj.usar')
@require_POST
def leido(request, pk):
    servicios.marcar_leido(_conv(request, pk), request.user)
    total, _ = servicios.no_leidos(request.user, request.empresa)
    return JsonResponse({'ok': True, 'total': total})


@acceso_modulo('msj', 'msj.usar')
@require_POST
def directo(request, user_id):
    otro = get_object_or_404(servicios._usuarios_activos(request.empresa), pk=user_id)
    try:
        conv = servicios.directo(request.empresa, request.user, otro)
    except servicios.ErrorMensaje as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'id': conv.pk})


@acceso_modulo('msj', 'msj.usar')
@require_POST
def de_proyecto(request, proyecto_id):
    """Abre (creándolo si hace falta) el canal de un proyecto al que la persona tiene acceso."""
    from proyectos.models import Proyecto
    proyecto = get_object_or_404(Proyecto.objects.de_empresa(request.empresa).activos(), pk=proyecto_id)
    conv = servicios.de_proyecto(proyecto)
    if not servicios.puede_ver(request.user, conv):
        raise Http404
    return JsonResponse({'ok': True, 'id': conv.pk})


@acceso_modulo('msj', 'msj.usar')
@require_GET
def personas(request):
    """Autocompletado de @menciones (con `?c=`) y buscador de personas para un directo (sin `c`)."""
    conv = _conv(request, request.GET['c']) if request.GET.get('c', '').isdigit() else None
    gente = servicios.personas(request.empresa, request.user, conv, request.GET.get('q', ''))
    return JsonResponse({'personas': [
        {'id': u.pk, 'nombre': str(u), 'handle': servicios.handle(u), 'iniciales': u.iniciales} for u in gente]})


def _propio(request, pk):
    msg = get_object_or_404(Mensaje.objects.select_related('conversacion__proyecto', 'conversacion__empresa'),
                            pk=pk, conversacion__empresa=request.empresa)
    if not servicios.puede_ver(request.user, msg.conversacion):
        raise Http404
    return msg


@acceso_modulo('msj', 'msj.usar')
@require_GET
def mensaje(request, pk):
    msg = _propio(request, pk)
    msg = _mensajes_qs(msg.conversacion).get(pk=msg.pk)
    return HttpResponse(_fragmento_mensajes(request, msg.conversacion, [msg]))


@acceso_modulo('msj', 'msj.usar')
@require_POST
def editar(request, pk):
    msg = _propio(request, pk)
    if not servicios.puede_moderar(request.user, msg):
        raise PermissionDenied
    try:
        servicios.editar(msg, request.POST.get('texto', ''))
    except servicios.ErrorMensaje as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    msg = _mensajes_qs(msg.conversacion).get(pk=msg.pk)
    return JsonResponse({'ok': True, 'html': _fragmento_mensajes(request, msg.conversacion, [msg])})


@acceso_modulo('msj', 'msj.usar')
@require_POST
def borrar(request, pk):
    msg = _propio(request, pk)
    if not servicios.puede_moderar(request.user, msg):
        raise PermissionDenied
    servicios.borrar(msg)
    return JsonResponse({'ok': True})


# ── Adjuntos (solo por aquí: `msj` está protegido en la ruta genérica de archivos privados) ───────

def _adjunto(request, pk):
    adj = get_object_or_404(AdjuntoMensaje.objects.select_related('mensaje__conversacion__proyecto'),
                            pk=pk, mensaje__conversacion__empresa=request.empresa)
    if not servicios.puede_ver(request.user, adj.mensaje.conversacion):
        raise Http404
    return adj


@acceso_modulo('msj', 'msj.usar')
@require_GET
def adjunto_servir(request, pk):
    adj = _adjunto(request, pk)
    etag = f'"{adj.sha256}"' if adj.sha256 else None
    if etag and request.headers.get('If-None-Match') == etag:
        return HttpResponseNotModified()
    try:
        archivo = adj.archivo.open('rb')
    except Exception:
        raise Http404('No se pudo recuperar el archivo del almacenamiento.')
    mime = (adj.mime_type or 'application/octet-stream').lower()
    respuesta = FileResponse(archivo, content_type=mime, as_attachment=mime not in INLINE_SEGUROS, filename=adj.nombre)
    respuesta['Content-Security-Policy'] = 'sandbox'
    respuesta['Cache-Control'] = 'private, max-age=86400'
    if etag:
        respuesta['ETag'] = etag
    return respuesta


@acceso_modulo('msj', 'msj.usar')
@require_GET
def adjunto_miniatura(request, pk):
    from tar_adjuntos.servicios import miniatura_en
    adj = _adjunto(request, pk)
    etag = f'"{adj.sha256}"' if adj.sha256 else None
    if etag and request.headers.get('If-None-Match') == etag:
        return HttpResponseNotModified()
    ruta = f'{adj.mensaje.conversacion.empresa_id}/msj/miniaturas/{adj.sha256[:2]}/{adj.sha256}_256.png'
    png = miniatura_en(adj, ruta)
    if not png:
        raise Http404('Sin miniatura.')
    respuesta = HttpResponse(png, content_type='image/png')
    respuesta['Cache-Control'] = 'private, max-age=86400'
    if etag:
        respuesta['ETag'] = etag
    return respuesta
