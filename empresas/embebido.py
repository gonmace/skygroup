"""Permite mostrar la aplicación DENTRO de un iframe, solo desde orígenes de confianza.

Por defecto skygroup se prohíbe a sí mismo en marcos (`X-Frame-Options: DENY`, contra el clickjacking). La app
«External sites» de Nextcloud abre skygroup en un iframe, así que se autoriza ese origen y ningún otro:
  · el servidor de Nextcloud configurado en la empresa de la petición (Panel → Nextcloud), y
  · los orígenes de `settings.FRAME_ANCESTORS` (variable FRAME_ANCESTORS del .env, separados por comas).
Se añade `frame-ancestors` al CSP y se omite `X-Frame-Options` (que no admite listas de orígenes)."""
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache

CACHE_KEY = 'embebido:empresa:{}'
CACHE_TTL = 120


_HOST = re.compile(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$')


def origen(url):
    """`https://host[:puerto]` de una URL, o '' si no es http(s) válida.

    Se reconstruye desde el host (solo letras, números, guiones y puntos) y el puerto (número): nunca se copia texto
    de la URL tal cual, porque este valor va dentro de una cabecera CSP y un `;`, un espacio o un `*` añadirían
    directivas o abrirían la política a cualquier sitio."""
    try:
        partes = urlsplit((url or '').strip())
        host, puerto = (partes.hostname or '').rstrip('.').lower(), partes.port
    except ValueError:
        return ''
    if partes.scheme not in ('http', 'https') or not host or not _HOST.match(host):
        return ''
    return f'{partes.scheme}://{host}' + (f':{puerto}' if puerto else '')


def invalidar(empresa_id):
    try:
        cache.delete(CACHE_KEY.format(empresa_id))
    except Exception:
        pass


def _de_nextcloud(empresa):
    """Origen del Nextcloud de la empresa (cacheado: se consulta en cada respuesta)."""
    clave = CACHE_KEY.format(empresa.pk)
    try:
        valor = cache.get(clave)
    except Exception:
        valor = None
    if valor is None:
        from cuentas.models import NextcloudConfig
        cfg = NextcloudConfig.objects.filter(empresa=empresa).first()
        valor = origen(cfg.servidor_url) if cfg else ''
        try:
            cache.set(clave, valor, CACHE_TTL)
        except Exception:
            pass
    return valor


def origenes_permitidos(empresa=None):
    lista = [o for o in (origen(x) for x in getattr(settings, 'FRAME_ANCESTORS', [])) if o]
    if empresa is not None:
        lista.append(_de_nextcloud(empresa))
    return list(dict.fromkeys(o for o in lista if o))


class EmbebidoMiddleware:
    """Debe ir DESPUÉS de `XFrameOptionsMiddleware` en MIDDLEWARE (su respuesta se procesa antes) y la petición ya trae
    `request.empresa` cuando se procesa la respuesta."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        origenes = origenes_permitidos(getattr(request, 'empresa', None))
        if origenes:
            actualizar = dict(getattr(response, '_csp_update', None) or {})
            actualizar['frame-ancestors'] = ["'self'", *origenes]
            response._csp_update = actualizar
            response.xframe_options_exempt = True
        return response
