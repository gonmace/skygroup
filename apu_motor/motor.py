"""Motor: aplica un perfil validado a los totales por grupo de insumos. Solo Decimal, sin Django."""
from dataclasses import dataclass
from decimal import Decimal

from .perfil import GRUPOS, MODOS_REDONDEO, PerfilInvalido, dec

UNO = Decimal(1)


@dataclass(frozen=True)
class Resultado:
    lineas: dict   # {codigo: Decimal} en el orden del perfil
    total: Decimal  # valor de la línea marcada total del nivel pedido, redondeado (redondeo.total)


def _redondear(valor, decimales, modo):
    if decimales is None:
        return valor
    return valor.quantize(Decimal(1).scaleb(-decimales), rounding=MODOS_REDONDEO[modo])


def calcular(perfil, grupos, nivel='apu'):
    """Calcula las líneas del perfil.

    `perfil`: resultado de `validar_perfil`. `grupos`: totales por grupo de insumos, ``{'MAT','MO','EQ'}``
    (los faltantes valen 0): Σ cantidad × precio de cada tipo de insumo.

    `nivel='apu'` calcula las líneas de cada APU y devuelve su precio unitario. `nivel='presupuesto'` recibe los
    grupos AGREGADOS de todo el presupuesto (Σ partida × cantidad), recalcula las líneas de apu sobre ellos y
    luego las de presupuesto (GG, utilidad, IVA…); `total` es el total del presupuesto. Si el perfil no tiene
    línea total de presupuesto, se devuelve la de apu.
    """
    if 'lineas' not in perfil or 'totales' not in perfil:
        raise PerfilInvalido('El perfil no está validado: use validar_perfil().')
    if nivel not in ('apu', 'presupuesto'):
        raise ValueError(f'Nivel desconocido: {nivel}')
    for g in grupos:
        if g not in GRUPOS:
            raise ValueError(f'Grupo desconocido: {g}')
    sumas = {g: dec(grupos.get(g, 0), f'grupo {g}') for g in GRUPOS}
    modo = perfil['redondeo']['modo']
    dec_linea = perfil['redondeo']['linea']

    valores = {}
    for linea in perfil['lineas']:
        if nivel == 'apu' and linea['nivel'] != 'apu':
            continue
        if linea['tipo'] == 'suma':
            v = sumas[linea['grupo']] * linea['factor']
        else:
            base = sum((valores[b] for b in linea['base']), Decimal(0))
            if linea['tipo'] == 'subtotal':
                v = base
            elif linea['modo'] == 'sobre_precio':
                v = base * linea['pct'] / (UNO - linea['pct'])
            else:
                v = base * linea['pct']
        valores[linea['cod']] = _redondear(v, dec_linea, modo)

    cod_total = perfil['totales'].get(nivel) or perfil['totales']['apu']
    total = _redondear(valores[cod_total], perfil['redondeo']['total'], modo)
    return Resultado(lineas=valores, total=total)
