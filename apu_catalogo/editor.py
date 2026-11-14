"""Editor de perfiles sin JavaScript: el formulario completo viaja en cada envío y cada botón («Agregar recargo»,
«Quitar», «Subir»…) es una acción que se aplica al estado recibido antes de volver a mostrarlo.

Estado = {'filas': [...], 'total_apu': cod, 'total_presupuesto': cod|'', 'prueba': {'MAT': str, ...}}.
Fila    = {'cod', 'nombre', 'tipo', 'grupo', 'nivel', 'valor', 'modo', 'bases'}; `valor` es el porcentaje (14,94) en
las líneas de recargo y el factor en las sumas de insumos.
"""
import re
from decimal import Decimal, InvalidOperation

from apu_motor import PerfilInvalido, calcular, validar_perfil
from apu_motor.perfil import GRUPOS

MAX_FILAS = 60
ETIQUETA_GRUPO = {'MAT': 'materiales', 'MO': 'mano de obra', 'EQ': 'equipos'}
PRUEBA_INICIAL = {'MAT': '100', 'MO': '50', 'EQ': '20'}

# Perfil mínimo para crear uno desde cero: los tres grupos de insumos y el costo directo.
MINIMO = {
    'redondeo': {'linea': None, 'total': 2, 'modo': 'HALF_UP'},
    'lineas': [
        {'cod': 'MAT', 'nombre': 'Materiales', 'tipo': 'suma', 'grupo': 'MAT'},
        {'cod': 'MO', 'nombre': 'Mano de obra', 'tipo': 'suma', 'grupo': 'MO'},
        {'cod': 'EQ', 'nombre': 'Equipos y herramientas', 'tipo': 'suma', 'grupo': 'EQ'},
        {'cod': 'DIRECTO', 'nombre': 'Costo directo', 'tipo': 'subtotal', 'base': ['MAT', 'MO', 'EQ'], 'total': True},
    ],
}


def _texto_numero(valor):
    return format(Decimal(str(valor)).normalize(), 'f')


def estado_inicial(datos):
    """Estado del editor a partir de los `datos` de un perfil (o de `MINIMO`)."""
    perfil = validar_perfil(datos)
    filas = []
    for l in perfil['lineas']:
        valor = ''
        if l['tipo'] == 'porcentaje':
            valor = _texto_numero(l['pct'] * 100)
        elif l['tipo'] == 'suma':
            valor = _texto_numero(l['factor'])
        filas.append({'cod': l['cod'], 'nombre': l['nombre'], 'tipo': l['tipo'], 'grupo': l.get('grupo', ''),
                      'nivel': l['nivel'], 'valor': valor, 'modo': l.get('modo', 'normal'),
                      'bases': list(l.get('base', []))})
    return {'filas': filas, 'total_apu': perfil['totales']['apu'],
            'total_presupuesto': perfil['totales'].get('presupuesto', ''), 'prueba': dict(PRUEBA_INICIAL)}


def estado_desde_post(post):
    """Reconstruye el estado desde el formulario enviado (campos `cod_0`, `nombre_0`, `sobre_0`…)."""
    try:
        n = min(int(post.get('n', 0)), MAX_FILAS)
    except ValueError:
        n = 0
    filas = []
    for i in range(max(n, 0)):
        tipo = post.get(f'tipo_{i}', '')
        filas.append({
            'cod': post.get(f'cod_{i}', '')[:30], 'nombre': post.get(f'nombre_{i}', '')[:100], 'tipo': tipo,
            'grupo': post.get(f'grupo_{i}', ''), 'nivel': 'presupuesto' if post.get(f'nivel_{i}') == 'presupuesto' else 'apu',
            'valor': post.get(f'valor_{i}', '').strip(), 'modo': 'sobre_precio' if post.get(f'modo_{i}') else 'normal',
            'bases': post.getlist(f'sobre_{i}')})
    estado = {'filas': filas, 'total_apu': post.get('total_apu', ''), 'total_presupuesto': post.get('total_presupuesto', ''),
              'prueba': {g: post.get(f'prueba_{g}', PRUEBA_INICIAL[g]).strip() for g in GRUPOS}}
    _ordenar(estado)
    return estado


def _ordenar(estado):
    """Las líneas de cada APU van antes que las del presupuesto (partición estable) y cada base solo puede ser una
    línea anterior: se descartan las que quedaron después al mover filas."""
    filas = estado['filas']
    filas[:] = [f for f in filas if f['nivel'] == 'apu'] + [f for f in filas if f['nivel'] == 'presupuesto']
    previas = set()
    for f in filas:
        f['bases'] = [b for b in f['bases'] if b in previas]
        previas.add(f['cod'])
    cods = {f['cod'] for f in filas}
    if estado['total_apu'] not in {f['cod'] for f in filas if f['nivel'] == 'apu'}:
        estado['total_apu'] = ''
    if estado['total_presupuesto'] not in {f['cod'] for f in filas if f['nivel'] == 'presupuesto'} & cods:
        estado['total_presupuesto'] = ''


def _codigo_nuevo(filas):
    usados = {f['cod'] for f in filas}
    n = 1
    while f'L{n}' in usados:
        n += 1
    return f'L{n}'


def aplicar_accion(estado, accion):
    """Aplica un botón del editor: agregar_recargo, agregar_subtotal, quitar:<i>, subir:<i>, bajar:<i>.
    Cualquier otra acción (guardar, probar) no cambia nada."""
    filas = estado['filas']
    nombre, _, arg = accion.partition(':')
    if nombre in ('agregar_recargo', 'agregar_subtotal') and len(filas) < MAX_FILAS:
        ultima = next((f for f in reversed(filas) if f['nivel'] == 'apu'), None)
        nueva = {'cod': _codigo_nuevo(filas), 'nivel': 'apu', 'grupo': '', 'bases': [ultima['cod']] if ultima else [],
                 'modo': 'normal'}
        if nombre == 'agregar_recargo':
            nueva.update(nombre='Nuevo recargo', tipo='porcentaje', valor='0')
        else:
            nueva.update(nombre='Nuevo subtotal', tipo='subtotal', valor='')
            cods_apu = [f['cod'] for f in filas if f['nivel'] == 'apu']
            if estado['total_apu'] in cods_apu:
                # Suma el resultado actual y lo que vino después (p. ej. Costo directo + Gastos generales) y pasa a
                # ser el nuevo resultado: es lo que casi siempre se quiere al cerrar con «Precio unitario».
                nueva['bases'] = cods_apu[cods_apu.index(estado['total_apu']):]
                estado['total_apu'] = nueva['cod']
        filas.append(nueva)
    elif nombre in ('quitar', 'subir', 'bajar') and arg.isdigit() and int(arg) < len(filas):
        i = int(arg)
        if nombre == 'quitar':
            if filas[i]['tipo'] != 'suma':
                cod = filas.pop(i)['cod']
                for f in filas:
                    f['bases'] = [b for b in f['bases'] if b != cod]
        else:
            j = i - 1 if nombre == 'subir' else i + 1
            if 0 <= j < len(filas) and filas[i]['tipo'] != 'suma' and filas[j]['tipo'] != 'suma' \
                    and filas[i]['nivel'] == filas[j]['nivel']:
                filas[i], filas[j] = filas[j], filas[i]
    _ordenar(estado)


def _numero(texto, donde, errores):
    try:
        return Decimal(texto.replace(',', '.'))
    except (InvalidOperation, AttributeError):
        errores.append(f'«{texto}» no es un número ({donde}).')
        return Decimal(0)


def datos_desde_estado(estado, redondeo):
    """(datos para `validar_perfil`, errores de captura). Los errores de esquema los da el validador."""
    errores, lineas = [], []
    for f in estado['filas']:
        nombre = f['nombre'].strip() or f['cod']
        l = {'cod': f['cod'], 'nombre': nombre, 'tipo': f['tipo'], 'nivel': f['nivel'],
             'total': (f['cod'] == estado['total_apu'] and f['nivel'] == 'apu')
                      or (f['cod'] == estado['total_presupuesto'] and f['nivel'] == 'presupuesto')}
        if f['tipo'] == 'suma':
            l.update(grupo=f['grupo'], factor=float(_numero(f['valor'] or '1', nombre, errores)))
        else:
            l['base'] = list(f['bases'])
            if f['tipo'] == 'porcentaje':
                l.update(pct=float(_numero(f['valor'] or '0', nombre, errores) / 100), modo=f['modo'])
        lineas.append(l)
    return {'redondeo': redondeo, 'lineas': lineas}, errores


def previsualizar(datos, prueba):
    """Calcula el perfil con montos de ejemplo. Devuelve {'apu': [(nombre, valor)], 'presupuesto': [...] | None,
    'total_apu', 'total_presupuesto'}; None si el perfil no es válido."""
    try:
        perfil = validar_perfil(datos)
    except PerfilInvalido:
        return None
    grupos = {}
    for g in GRUPOS:
        try:
            grupos[g] = Decimal(prueba.get(g, '0').replace(',', '.') or '0')
        except InvalidOperation:
            grupos[g] = Decimal(0)

    def tabla(nivel):
        r = calcular(perfil, grupos, nivel=nivel)
        return [(l['nombre'], r.lineas[l['cod']], l['total']) for l in perfil['lineas'] if l['cod'] in r.lineas], r.total

    apu, total_apu = tabla('apu')
    salida = {'apu': apu, 'total_apu': total_apu, 'presupuesto': None, 'total_presupuesto': None}
    if 'presupuesto' in perfil['totales']:
        salida['presupuesto'], salida['total_presupuesto'] = tabla('presupuesto')
    return salida


def filas_para_plantilla(estado):
    """Cada fila con lo que la plantilla necesita: líneas anteriores elegibles como base y las marcadas."""
    filas = estado['filas']
    salida = []
    for i, f in enumerate(filas):
        resultado = (f['cod'] == estado['total_apu'] and f['nivel'] == 'apu') or \
                    (f['cod'] == estado['total_presupuesto'] and f['nivel'] == 'presupuesto')
        salida.append(dict(f, i=i, es_suma=f['tipo'] == 'suma', etiqueta_grupo=ETIQUETA_GRUPO.get(f['grupo'], ''),
                           es_resultado=resultado,
                           seccion='insumos' if f['tipo'] == 'suma' else f['nivel'],
                           candidatas=[{'cod': p['cod'], 'nombre': p['nombre'] or p['cod'], 'marcada': p['cod'] in f['bases']}
                                       for p in filas[:i]],
                           puede_subir=f['tipo'] != 'suma' and i > 0 and filas[i - 1]['tipo'] != 'suma'
                           and filas[i - 1]['nivel'] == f['nivel'],
                           puede_bajar=f['tipo'] != 'suma' and i < len(filas) - 1 and filas[i + 1]['nivel'] == f['nivel'],
                           sobre_precio=f['modo'] == 'sobre_precio'))
    return salida
