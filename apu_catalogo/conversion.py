"""Cambio de unidad de un insumo con su conversión: las cantidades de todas sus líneas y sus precios se recalculan para que el
costo de cada APU no cambie (p. ej. la madera de m² a pie²)."""
from decimal import ROUND_HALF_UP, Decimal

from django.apps import apps
from django.db import transaction

from .models import LineaComposicion, PrecioInsumo

CANTIDAD = Decimal('0.000001')
PRECIO = Decimal('0.0001')


@transaction.atomic
def cambiar_unidad(insumo, nueva, factor):
    """Pasa `insumo` a la unidad `nueva`. `factor` = cuántas `nueva` hay en 1 de la unidad actual: la cantidad de cada línea se
    multiplica por él y cada precio se divide (el costo queda igual). Devuelve (líneas, precios) recalculados."""
    factor = Decimal(factor)
    if factor <= 0:
        raise ValueError('El factor debe ser mayor que cero.')
    lineas = list(LineaComposicion.objects.select_for_update().filter(insumo=insumo))
    for linea in lineas:
        linea.cantidad = (linea.cantidad * factor).quantize(CANTIDAD, ROUND_HALF_UP)
        linea.save(update_fields=['cantidad'])
    precios = list(PrecioInsumo.objects.filter(insumo=insumo))
    for precio in precios:
        precio.precio = (precio.precio / factor).quantize(PRECIO, ROUND_HALF_UP)
        precio.save(update_fields=['precio'])
    insumo.unidad = nueva
    insumo.save(update_fields=['unidad'])
    _convertir_borradores(insumo, nueva, factor)
    return len(lineas), len(precios)


def _convertir_borradores(insumo, nueva, factor):
    """Los APU a medio generar (borradores pendientes) guardan la unidad y la cantidad de cada fila: se actualizan igual."""
    Borrador = apps.get_model('apu_generador', 'APUBorrador')
    for b in Borrador.objects.filter(empresa=insumo.empresa, eliminado=False, guardado=False):
        cambio = False
        for tipo in ('materiales', 'mano_obra', 'equipos'):
            paso = getattr(b, tipo) or {}
            for fila in paso.get('filas') or []:
                if fila.get('insumo_id') != insumo.pk:
                    continue
                try:
                    fila['cantidad'] = str((Decimal(str(fila.get('cantidad'))) * factor).quantize(CANTIDAD, ROUND_HALF_UP))
                except Exception:   # cantidad vacía o no numérica: solo cambia la unidad
                    pass
                fila['unidad'] = nueva
                cambio = True
        if cambio:
            b.save(update_fields=['materiales', 'mano_obra', 'equipos'])
