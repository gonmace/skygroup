"""Imagen estática de los widgets de mapa: generarla (POST) y servirla (GET, con el permiso del registro)."""
import mimetypes

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponseNotModified, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from empresas.acceso import acceso_modulo
from reg_base import acciones, tipos

from . import mapas, servicios
from .models import ImagenMapa
from .widgets import obtener

_acceso = acceso_modulo('reg')
_SLUGS_MAPA = ('mapa_1p', 'mapa_2_puntos')


def _registro(request, clave, pk):
    t = tipos.tipo_de_request(request, clave)
    if not tiene_capacidad(request.user, t.capacidad_ver, request.empresa):
        raise PermissionDenied
    return t, acciones.obtener_registro(request, t.modelo, pk)


def _asignado(registro, clave, nombre):
    for a in servicios.asignados_de(registro, clave):
        if a.paso.nombre == nombre:
            return a
    raise Http404('Ese paso no pertenece a la plantilla del registro.')


@require_POST
@_acceso
def guardar(request, clave, pk, nombre):
    """Genera la imagen del mapa del paso con las coordenadas YA guardadas del registro (el cuerpo no se usa)."""
    _t, registro = _registro(request, clave, pk)
    acciones.exigir_escritura(request.user, registro)
    a = _asignado(registro, clave, nombre)
    pw = next((p for p in a.paso.widgets.all() if p.widget_slug in _SLUGS_MAPA), None)
    if pw is None or obtener(pw.widget_slug) is None:
        return JsonResponse({'success': False, 'error': 'Este paso no tiene un widget de mapa.'}, status=400)
    if not mapas.hay_clave():
        return JsonResponse({'success': False, 'error': 'No hay una clave de Google Maps configurada en el servidor.'},
                            status=503)
    puntos = mapas.puntos_de_widget(pw.widget_slug, pw.config, registro, a.paso)
    if not puntos:
        return JsonResponse({'success': False, 'error': 'Todavía no hay coordenadas para dibujar el mapa.'}, status=400)
    imagen = mapas.guardar_imagen(registro, a.paso.nombre, puntos)
    if imagen is None:
        return JsonResponse({'success': False, 'error': 'No se pudo generar la imagen con Google Maps. Inténtalo de nuevo.'},
                            status=502)
    return JsonResponse({
        'success': True,
        'image_url': reverse('reg_actividades:mapa_imagen', kwargs={'clave': clave, 'pk': pk, 'nombre': nombre})
                     + f'?v={int(imagen.actualizada.timestamp())}',
        'distancia_total_metros': imagen.distancia_total_metros, 'desfase_metros': imagen.desfase_metros,
    })


@_acceso
def imagen(request, clave, pk, nombre):
    _t, registro = _registro(request, clave, pk)
    ct = ContentType.objects.get_for_model(type(registro))
    obj = ImagenMapa.objects.filter(content_type=ct, object_id=registro.pk, etapa=nombre).first()
    if obj is None or not obj.imagen:
        raise Http404
    etag = f'"{obj.pk}-{int(obj.actualizada.timestamp())}"'
    if request.headers.get('If-None-Match') == etag:
        return HttpResponseNotModified()
    try:
        archivo = obj.imagen.open('rb')
    except Exception:
        raise Http404('No se pudo recuperar el archivo del almacenamiento.')
    mime = mimetypes.guess_type(obj.imagen.name)[0] or 'image/png'
    respuesta = FileResponse(archivo, content_type=mime if mime.startswith('image/') else 'image/png')
    respuesta['Content-Security-Policy'] = 'sandbox'
    respuesta['X-Content-Type-Options'] = 'nosniff'
    respuesta['Cache-Control'] = 'private, max-age=86400'
    respuesta['ETag'] = etag
    return respuesta
