"""Endpoint interno para n8n/cron: cierra las jornadas que quedaron abiertas de días anteriores."""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.interno import cuerpo_json, token_interno
from empresas.models import Empresa

from . import servicios


@csrf_exempt
@require_POST
@token_interno
def cerrar_vencidas(request):
    """POST {"empresa": "<slug>"?} → {"ok": true, "cerradas": n}. Sin empresa, cierra en todas."""
    slug = cuerpo_json(request).get('empresa')
    empresa = None
    if slug:
        empresa = Empresa.objects.filter(slug=slug).first()
        if empresa is None:
            return JsonResponse({'ok': False, 'error': 'Empresa inexistente.'}, status=404)
    return JsonResponse({'ok': True, 'cerradas': servicios.cerrar_vencidas(empresa=empresa)})
