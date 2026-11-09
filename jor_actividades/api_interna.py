"""Endpoints internos para n8n: clasificar con un LLM las actividades que las palabras clave dejaron en «otros».

Flujo: GET pendientes → n8n pide la categoría al LLM → POST clasificar con las asignaciones."""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.interno import cuerpo_json, token_interno
from empresas.models import Empresa

from .models import OTROS, ItemActividad
from .servicios import categorias

LIMITE_MAXIMO = 200


def _empresa(slug):
    return Empresa.objects.filter(slug=slug).first() if slug else None


@require_GET
@token_interno
def pendientes(request):
    """GET ?empresa=<slug>&limite=50 → ítems en «otros», sin asignar a mano ni por LLM, con las categorías válidas."""
    empresa = _empresa(request.GET.get('empresa'))
    if empresa is None:
        return JsonResponse({'ok': False, 'error': 'Empresa inexistente.'}, status=404)
    try:
        limite = max(1, min(int(request.GET.get('limite', 50)), LIMITE_MAXIMO))
    except ValueError:
        limite = 50
    items = ItemActividad.objects.filter(empresa=empresa, categoria=OTROS, manual=False,
                                         fuente=ItemActividad.Fuente.PALABRAS).order_by('id')[:limite]
    cats = categorias(empresa, solo_activas=True).exclude(codigo=OTROS)
    return JsonResponse({
        'ok': True,
        'categorias': [{'codigo': c.codigo, 'nombre': c.etiqueta} for c in cats],
        'items': [{'id': i.pk, 'texto': i.texto} for i in items],
    })


@csrf_exempt
@require_POST
@token_interno
def clasificar(request):
    """POST {"empresa": slug, "asignaciones": [{"id": 1, "categoria": "riesgos"}, …]}.
    Ignora lo asignado a mano y las categorías inexistentes o inactivas. Marca la fuente como LLM."""
    datos = cuerpo_json(request)
    empresa = _empresa(datos.get('empresa'))
    if empresa is None:
        return JsonResponse({'ok': False, 'error': 'Empresa inexistente.'}, status=404)
    validas = set(categorias(empresa, solo_activas=True).values_list('codigo', flat=True))
    asignaciones = datos.get('asignaciones')
    if not isinstance(asignaciones, list):
        return JsonResponse({'ok': False, 'error': 'Falta «asignaciones».'}, status=400)
    actualizados = omitidos = 0
    for a in asignaciones[:LIMITE_MAXIMO * 5]:
        if not isinstance(a, dict) or a.get('categoria') not in validas:
            omitidos += 1
            continue
        n = ItemActividad.objects.filter(pk=a.get('id') if isinstance(a.get('id'), int) else 0, empresa=empresa,
                                         manual=False).update(categoria=a['categoria'], fuente=ItemActividad.Fuente.LLM)
        actualizados += n
        omitidos += 1 - n
    return JsonResponse({'ok': True, 'actualizados': actualizados, 'omitidos': omitidos})
