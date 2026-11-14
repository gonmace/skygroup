"""Esquema y validación del perfil de cálculo.

Un perfil es una lista ORDENADA de líneas; cada línea solo puede basarse en líneas anteriores (sin ciclos).

    {
      "perfil": "Bolivia - estándar", "moneda": "BOB",
      "redondeo": {"linea": null, "total": 2, "modo": "HALF_UP"},
      "lineas": [ ...líneas... ]
    }

Tipos de línea:
  - ``suma``       raíz: total del grupo de insumos ``grupo`` (MAT / MO / EQ), por ``factor`` (opcional, defecto 1;
                   p. ej. factor de salario real o leyes sociales sobre el costo por hora).
  - ``porcentaje`` ``pct`` × Σ(``base``). Con ``modo: "sobre_precio"`` el recargo se calcula sobre el precio de
                   venta: Σ(base) × pct / (1 − pct), es decir ``base / (1 − pct)`` menos ``base``.
  - ``subtotal``   Σ(``base``), con nombre visible (Total mano de obra, Costo directo…).

Campos comunes: ``cod`` (único), ``nombre``, ``nivel`` (``apu`` por defecto, o ``presupuesto`` = se aplica una sola
vez sobre el total del presupuesto), ``total`` (true en la línea que da el precio; una por nivel).
"""
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation

TIPOS = ('suma', 'porcentaje', 'subtotal')
GRUPOS = ('MAT', 'MO', 'EQ')
NIVELES = ('apu', 'presupuesto')
MODOS_PCT = ('normal', 'sobre_precio')
MODOS_REDONDEO = {'HALF_UP': ROUND_HALF_UP, 'HALF_EVEN': ROUND_HALF_EVEN}


class PerfilInvalido(ValueError):
    """El perfil no cumple el esquema. El mensaje está en español y es apto para mostrar."""


def dec(valor, donde='valor'):
    """A Decimal sin pasar por float (los floats de un JSON se leen por su texto)."""
    if isinstance(valor, bool):
        raise PerfilInvalido(f'{donde}: no es un número.')
    try:
        return valor if isinstance(valor, Decimal) else Decimal(str(valor))
    except (InvalidOperation, ValueError):
        raise PerfilInvalido(f'{donde}: «{valor}» no es un número.')


def validar_perfil(datos):
    """Valida `datos` y devuelve el perfil normalizado (Decimals, valores por defecto). No modifica `datos`."""
    if not isinstance(datos, dict):
        raise PerfilInvalido('El perfil debe ser un objeto.')
    crudas = datos.get('lineas')
    if not isinstance(crudas, list) or not crudas:
        raise PerfilInvalido('El perfil necesita al menos una línea.')

    red = datos.get('redondeo') or {}
    modo = red.get('modo', 'HALF_UP')
    if modo not in MODOS_REDONDEO:
        raise PerfilInvalido(f'Modo de redondeo desconocido: «{modo}».')
    redondeo = {'modo': modo}
    for clave, defecto in (('linea', None), ('total', 2)):
        n = red.get(clave, defecto)
        if n is not None and (not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 8):
            raise PerfilInvalido(f'redondeo.{clave} debe ser un entero entre 0 y 8, o nulo.')
        redondeo[clave] = n

    lineas, vistos, niveles_vistos, totales = [], {}, set(), {}
    for i, cruda in enumerate(crudas, 1):
        if not isinstance(cruda, dict):
            raise PerfilInvalido(f'Línea {i}: debe ser un objeto.')
        cod = cruda.get('cod')
        if not isinstance(cod, str) or not cod.strip():
            raise PerfilInvalido(f'Línea {i}: falta el código.')
        if cod in vistos:
            raise PerfilInvalido(f'Línea {i}: el código «{cod}» está repetido.')
        tipo = cruda.get('tipo')
        if tipo not in TIPOS:
            raise PerfilInvalido(f'Línea «{cod}»: tipo «{tipo}» inválido (use {", ".join(TIPOS)}).')
        nivel = cruda.get('nivel', 'apu')
        if nivel not in NIVELES:
            raise PerfilInvalido(f'Línea «{cod}»: nivel «{nivel}» inválido.')
        if nivel == 'apu' and 'presupuesto' in niveles_vistos:
            raise PerfilInvalido(f'Línea «{cod}»: las líneas de nivel apu van antes que las de presupuesto.')
        niveles_vistos.add(nivel)

        linea = {'cod': cod, 'nombre': cruda.get('nombre', cod), 'tipo': tipo, 'nivel': nivel,
                 'total': bool(cruda.get('total', False))}
        if tipo == 'suma':
            if nivel != 'apu':
                raise PerfilInvalido(f'Línea «{cod}»: una suma de insumos solo puede ser de nivel apu.')
            if cruda.get('grupo') not in GRUPOS:
                raise PerfilInvalido(f'Línea «{cod}»: grupo inválido (use {", ".join(GRUPOS)}).')
            factor = dec(cruda.get('factor', 1), f'Línea «{cod}» (factor)')
            if factor < 0:
                raise PerfilInvalido(f'Línea «{cod}»: el factor no puede ser negativo.')
            linea.update(grupo=cruda['grupo'], factor=factor)
        else:
            base = cruda.get('base')
            if not isinstance(base, list) or not base:
                raise PerfilInvalido(f'Línea «{cod}»: falta la base.')
            for b in base:
                if b not in vistos:
                    raise PerfilInvalido(
                        f'Línea «{cod}»: la base «{b}» no existe o no está antes de esta línea.')
                if nivel == 'apu' and vistos[b] == 'presupuesto':
                    raise PerfilInvalido(f'Línea «{cod}»: una línea de apu no puede basarse en una de presupuesto.')
            linea['base'] = list(base)
            if tipo == 'porcentaje':
                pct = dec(cruda.get('pct'), f'Línea «{cod}» (pct)')
                modo_pct = cruda.get('modo', 'normal')
                if modo_pct not in MODOS_PCT:
                    raise PerfilInvalido(f'Línea «{cod}»: modo «{modo_pct}» inválido.')
                if pct < 0 or (modo_pct == 'sobre_precio' and pct >= 1) or pct > 10:
                    raise PerfilInvalido(f'Línea «{cod}»: porcentaje fuera de rango '
                                         f'(use 0.10 para 10 %; sobre_precio exige menos de 1).')
                linea.update(pct=pct, modo=modo_pct)
        if linea['total']:
            if nivel in totales:
                raise PerfilInvalido(f'Hay más de una línea total de nivel {nivel}.')
            totales[nivel] = cod
        vistos[cod] = nivel
        lineas.append(linea)

    if 'apu' not in totales:
        raise PerfilInvalido('Falta marcar la línea que da el precio unitario (total: true).')
    return {'perfil': datos.get('perfil', ''), 'moneda': datos.get('moneda', ''),
            'redondeo': redondeo, 'lineas': lineas, 'totales': totales}
