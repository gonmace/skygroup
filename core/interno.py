"""Autenticación de los endpoints internos (n8n, cron): cabecera `X-Internal-Token` contra `INTERNAL_API_TOKEN`.
Sin token configurado, los endpoints quedan deshabilitados (404)."""
import hmac
import json
from functools import wraps

from django.conf import settings
from django.http import Http404, JsonResponse


def token_interno(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        esperado = getattr(settings, 'INTERNAL_API_TOKEN', '')
        if not esperado:
            raise Http404
        recibido = request.headers.get('X-Internal-Token', '')
        if not hmac.compare_digest(recibido.encode(), esperado.encode()):
            return JsonResponse({'ok': False, 'error': 'Token inválido.'}, status=401)
        return vista(request, *args, **kwargs)
    return envoltura


def cuerpo_json(request):
    try:
        datos = json.loads(request.body or b'{}')
        return datos if isinstance(datos, dict) else {}
    except ValueError:
        return {}
