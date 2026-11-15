"""Edición de las líneas de la composición de un APU desde su ficha: cantidad, desperdicio y precio del insumo, o quitarla."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from .acceso import acceso_apu
from .models import ItemModelo, LineaComposicion, PrecioInsumo, ProyectoAPU


def _json(ok, message='', status=200, **extra):
    return JsonResponse({'success': ok, 'message': message, **extra}, status=status)


def _datos(request):
    try:
        datos = json.loads(request.body or b'{}')
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _num(valor):
    """A Decimal aceptando coma decimal; None si está vacío o no es un número."""
    if isinstance(valor, bool) or valor in (None, ''):
        return None
    try:
        return Decimal(str(valor).strip().replace(',', '.'))
    except (InvalidOperation, ValueError):
        return None


def _linea(request, item_pk, pk):
    item = get_object_or_404(ItemModelo, pk=item_pk, empresa=request.empresa)
    return item, get_object_or_404(LineaComposicion.objects.select_related('insumo', 'subitem'), pk=pk, item=item)


@acceso_apu('apu.catalogo.manage')
@require_POST
def linea_editar(request, item_pk, pk):
    """Guarda la cantidad y el desperdicio de la línea y, si se indica, el precio del insumo en la región del proyecto
    (un precio nuevo desde hoy; lo ven todos los APU que usan ese insumo)."""
    item, linea = _linea(request, item_pk, pk)
    d = _datos(request)
    cantidad = _num(d.get('cantidad'))
    if cantidad is None or cantidad <= 0:
        return _json(False, 'Indica una cantidad mayor que cero.', 400)
    desperdicio = _num(d.get('desperdicio_pct'))
    desperdicio = Decimal(0) if desperdicio is None else desperdicio
    if not 0 <= desperdicio <= 100:
        return _json(False, 'El desperdicio debe estar entre 0 y 100 %.', 400)
    precio = _num(d.get('precio'))
    moneda = str(d.get('moneda') or '').strip().upper()
    if linea.insumo_id and str(d.get('precio') or '').strip():
        if precio is None or precio < 0:
            return _json(False, 'Indica un precio válido (cero o más).', 400)
        if len(moneda) != 3:
            return _json(False, 'Indica la moneda con su código de 3 letras (p. ej. BOB).', 400)
    else:
        precio = None
    with transaction.atomic():
        if cantidad != linea.cantidad and linea.insumo_id and linea.insumo.tipo == 'MO':
            linea.ayuda = {}      # las horas ya no salen de «personas × jornada ÷ rendimiento»: se editaron a mano
        linea.cantidad, linea.desperdicio_pct = cantidad, desperdicio
        linea.save()
        if precio is not None:
            pa = ProyectoAPU.objects.filter(proyecto=item.proyecto).first() if item.proyecto_id else None
            PrecioInsumo.objects.update_or_create(
                insumo=linea.insumo, region=pa.region if pa else '', fecha=date.today(),
                defaults={'precio': precio, 'moneda': moneda, 'estimado': False, 'fuente': ''})
    nombre = linea.insumo.descripcion if linea.insumo_id else str(linea.subitem)
    return _json(True, f'Se guardaron los cambios de «{nombre}».' + (' El precio se actualizó en todos los APU que usan este insumo.' if precio is not None else ''))


@acceso_apu('apu.catalogo.manage')
@require_POST
def linea_quitar(request, item_pk, pk):
    item, linea = _linea(request, item_pk, pk)
    nombre = linea.insumo.descripcion if linea.insumo_id else str(linea.subitem)
    linea.delete()
    return _json(True, f'Se quitó «{nombre}» de {item.codigo}.')
