"""Multi-empresa por prefijo de ruta: `/<slug>/...`.

Una sola URLconf sin prefijos. `EmpresaMiddleware` detecta el primer segmento de
`request.path_info`, lo resuelve a una `Empresa` (con cache), lo RECORTA de `path_info`
y lo agrega al *script prefix* de Django, de modo que `reverse()`, `{% url %}`,
`LOGIN_URL`, etc. generan URLs prefijadas sin tocar vistas ni templates.

El prefijo de script vive en un `asgiref.Local`: es por request tanto en WSGI como en
ASGI. Se restaura en `finally` porque el `Client` de tests no lo resetea entre llamadas.

Reglas de acceso:
- Superusuario: entra a cualquier empresa; en `/` va al panel global.
- Usuario con membresía activa en Y, o administrador de sistema de Y: entra a `/Y/...`; en otra empresa → 403.
- Sin prefijo, usuario autenticado: GET se redirige a su primera empresa activa.
- Empresa inactiva → 404 (anónimo) / 403 (logueado, salvo superusuario).

NUNCA llamar a `reverse()` desde un thread: el hilo nuevo no tiene prefijo. Para links
fuera de un request usar `empresa_path`/`empresa_url`.
"""
import re

from asgiref.local import Local
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import get_script_prefix, reverse, set_script_prefix

from .models import EMPRESA_CACHE_KEY, RESERVED_SLUGS, Empresa

_SLUG_RE = re.compile(r'^[a-z][a-z0-9-]{1,30}$')
EMPRESA_CACHE_TTL = 300

# Prefijo de script ORIGINAL del request (antes de agregar el slug).
_state = Local()


def _admin_first_segment():
    return getattr(settings, 'ADMIN_URL', 'admin/').strip('/').split('/')[0]


def segmentos_excluidos():
    """Primeros segmentos que nunca se interpretan como slug de empresa."""
    return RESERVED_SLUGS | {_admin_first_segment()}


def empresa_por_slug(slug):
    """Empresa por slug, cacheada (también los fallos: `None`)."""
    if not slug or not _SLUG_RE.match(slug):
        return None
    key = EMPRESA_CACHE_KEY.format(slug)
    sentinel = object()
    try:
        empresa = cache.get(key, sentinel)
    except Exception:  # Redis caído no debe tumbar la app
        return Empresa.objects.filter(slug=slug).first()
    if empresa is sentinel:
        empresa = Empresa.objects.filter(slug=slug).first()
        try:
            cache.set(key, empresa, EMPRESA_CACHE_TTL)
        except Exception:
            pass
    return empresa


def empresas_de(user):
    """Empresas ACTIVAS donde el usuario tiene membresía activa (la más antigua primero).
    Superusuario: todas las activas. Administrador de sistema: además las que administra."""
    if user is None or not user.is_authenticated:
        return []
    if user.is_superuser:
        return list(Empresa.objects.filter(activa=True))
    ids = list(user.membresias.filter(activa=True, empresa__activa=True).order_by('creada').values_list('empresa_id', flat=True))
    ids += [i for i in user.empresas_administradas.filter(activa=True).order_by('nombre').values_list('pk', flat=True)
            if i not in ids]   # administrador de sistema: también las que administra sin ser miembro
    por_id = {e.pk: e for e in Empresa.objects.filter(pk__in=ids)}
    return [por_id[i] for i in ids if i in por_id]


def es_admin_de(user, empresa):
    """Administrador de sistema de la empresa activa (definido en Plataforma; ver `cuentas.capacidades.administra`)."""
    if user is None or not user.is_authenticated or empresa is None:
        return False
    return user.empresas_administradas.filter(pk=empresa.pk, activa=True).exists()


def es_miembro(user, empresa):
    if user is None or not user.is_authenticated or empresa is None:
        return False
    return user.membresias.filter(empresa=empresa, activa=True, empresa__activa=True).exists()


def empresa_path(empresa, viewname, *args, **kwargs):
    """`reverse()` con el prefijo `/<slug>/`, dentro o fuera de un request."""
    root = getattr(_state, 'root_prefix', None) or '/'
    old = get_script_prefix()
    set_script_prefix(f'{root}{empresa.slug}/')
    try:
        return reverse(viewname, args=args or None, kwargs=kwargs or None)
    finally:
        set_script_prefix(old)


def site_url():
    return (getattr(settings, 'SITE_URL', '') or '').rstrip('/')


def empresa_url(empresa, viewname, *args, **kwargs):
    """URL absoluta (para correos) de una vista dentro de la empresa."""
    return site_url() + empresa_path(empresa, viewname, *args, **kwargs)


class EmpresaMiddleware:
    """Debe ir al FINAL de MIDDLEWARE: necesita `request.user` y `messages`."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.empresa = None
        _state.root_prefix = get_script_prefix()
        primero, _, resto = request.path_info.lstrip('/').partition('/')
        if primero and primero not in segmentos_excluidos() and not primero.isdigit():
            empresa = empresa_por_slug(primero)
            if empresa is not None:
                return self._con_empresa(request, empresa, primero, resto)
        return self._sin_empresa(request, primero)

    def _con_empresa(self, request, empresa, slug, resto):
        user = request.user
        es_super = user.is_authenticated and user.is_superuser
        if not empresa.activa and not es_super:
            if user.is_authenticated:
                return render(request, 'empresas/empresa_inactiva.html', {'empresa': empresa}, status=403)
            raise Http404
        if user.is_authenticated and not es_super:
            if not es_miembro(user, empresa) and not es_admin_de(user, empresa):
                raise PermissionDenied('Tu cuenta no pertenece a esta empresa.')
        if user.is_authenticated:
            user.__dict__['_empresa_activa_id'] = empresa.pk
        request.empresa = empresa
        request.path_info = '/' + resto
        request.META['PATH_INFO'] = request.path_info
        old = get_script_prefix()
        set_script_prefix(f'{old}{slug}/')
        try:
            return self.get_response(request)
        finally:
            set_script_prefix(old)

    def _sin_empresa(self, request, primero):
        user = request.user
        if not user.is_authenticated:
            return self.get_response(request)
        if user.is_superuser:
            if request.path_info == '/':
                empresas = empresas_de(user)  # «Inicio» = la primera empresa; el panel queda en el menú Plataforma
                destino = f'{empresas[0].slug}/' if empresas else 'panel/'
                return redirect(f'{_state.root_prefix}{destino}')
            return self.get_response(request)
        if primero in segmentos_excluidos():
            return self.get_response(request)  # rutas del servidor: que la vista decida
        empresas = empresas_de(user)
        if empresas:
            if request.method in ('GET', 'HEAD'):
                return redirect(f'{_state.root_prefix}{empresas[0].slug}{request.get_full_path()}')
            raise PermissionDenied
        raise PermissionDenied('Tu cuenta no está asociada a ninguna empresa activa.')
