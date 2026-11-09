"""Endpoint interno para n8n/cron. Antes marcaba los avisos sin confirmar al cerrar el día; con el chat ya no
hay confirmación, pero se conserva para no romper los cron/n8n ya configurados: responde OK sin hacer nada."""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.interno import token_interno


@csrf_exempt
@require_POST
@token_interno
def cerrar_dia(request):
    return JsonResponse({'ok': True, 'marcados': 0})
