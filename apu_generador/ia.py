"""Llamadas del generador de APU a los workflows de n8n. La IA vive SOLO en n8n: aquí se arma el payload, se llama
con `core.n8n`, se registra la llamada (`LlamadaIA`) y se normaliza lo que vuelve. Nada de SDKs ni prompts."""
import logging
import re
import time
import unicodedata
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

from core import n8n
from core.n8n import N8NError

from .models import LlamadaIA, TarifaModeloIA

logger = logging.getLogger(__name__)

WEBHOOKS = {'coherencia': 'apu-coherencia', 'insumos': 'apu-insumos', 'modificar': 'apu-modificar',
            'tarifas': 'apu-tarifas', 'precios': 'apu-precios'}
TIMEOUT = 180
TIPOS_INSUMO = ('materiales', 'mano_obra', 'equipos')
CODIGO_TIPO = {'materiales': 'MAT', 'mano_obra': 'MO', 'equipos': 'EQ'}


def contexto_proyecto(proyecto):
    """El proyecto como lo ve la IA. Sin país: el contexto lo dan la descripción y el vocabulario de la empresa."""
    return {'nombre': proyecto.nombre, 'descripcion': proyecto.descripcion or '',
            'tipo': proyecto.tipo.nombre if proyecto.tipo_id else '', 'ciudad': proyecto.ciudad or '',
            'region': proyecto.region or ''}


def llamar(clave, payload, *, empresa, usuario=None, borrador=None, paso='', apu=None):
    """Llama al webhook `clave`, registra la `LlamadaIA` y devuelve la respuesta ya desempaquetada (un dict).
    Lanza `N8NError` con un mensaje apto para mostrar."""
    inicio = time.monotonic()
    ok, datos = True, {}
    try:
        datos = n8n.desempaquetar(n8n.llamar_webhook_seguro(n8n.webhook_url(WEBHOOKS[clave]), payload, timeout=TIMEOUT))
    except N8NError:
        ok = False
        raise
    finally:
        LlamadaIA.objects.create(
            empresa=empresa, usuario=usuario, borrador=borrador, apu=apu, webhook=WEBHOOKS[clave], paso=paso, ok=ok,
            ejecucion_id=str(datos.get('ejecucion_id') or ''), duracion_ms=int((time.monotonic() - inicio) * 1000))
    if not datos:
        raise N8NError('El servicio de IA no devolvió resultados. Inténtalo de nuevo.')
    return datos


# ── Normalización ─────────────────────────────────────────────────────────────

def numero(valor, defecto=None):
    """A Decimal aceptando coma decimal; `defecto` si no es un número."""
    if isinstance(valor, bool) or valor in (None, ''):
        return defecto
    try:
        return Decimal(str(valor).strip().replace(',', '.'))
    except (InvalidOperation, ValueError):
        return defecto


def texto_numero(valor):
    """Un Decimal como texto normal, sin ceros de más ni notación científica (830, no 8.3E+2)."""
    return format(valor.normalize(), 'f') if valor else '0'


def clave_texto(texto):
    """Para comparar términos: sin tildes, en minúsculas y con los espacios normalizados."""
    sin = unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', sin).strip().lower()


def _texto(valor, largo):
    return str(valor or '').strip()[:largo]


def normalizar_fila(crudo, tipo):
    """Una fila propuesta por la IA, con los tipos correctos. None si no sirve (sin descripción)."""
    if not isinstance(crudo, dict):
        return None
    descripcion = _texto(crudo.get('descripcion'), 200)
    if not descripcion:
        return None
    fila = {'descripcion': descripcion, 'unidad': _texto(crudo.get('unidad'), 20),
            'codigo_catalogo': _texto(crudo.get('codigo_catalogo'), 30), 'nuevo': bool(crudo.get('nuevo')),
            'justificacion': _texto(crudo.get('justificacion'), 400), 'check': bool(crudo.get('check', True)),
            'consulta': _texto(crudo.get('consulta'), 20)}
    if not fila['unidad'] and tipo in ('mano_obra', 'equipos'):
        fila['unidad'] = 'h'
    if crudo.get('codigo_subitem'):
        fila['codigo_subitem'] = _texto(crudo.get('codigo_subitem'), 30)
    if tipo == 'mano_obra':
        fila['personas'] = texto_numero(numero(crudo.get('personas'), Decimal(1)))
    else:
        fila['cantidad'] = texto_numero(numero(crudo.get('cantidad'), Decimal(0)))
    if tipo == 'materiales':
        fila['desperdicio_pct'] = texto_numero(numero(crudo.get('desperdicio_pct'), Decimal(0)))
    return fila


def normalizar_consultas(crudas):
    """Consultas de la IA: `opciones` (alternativas con sus filas) o `dato` (duda abierta)."""
    salida = []
    for i, c in enumerate(crudas if isinstance(crudas, list) else [], 1):
        if not isinstance(c, dict) or not str(c.get('pregunta') or '').strip():
            continue
        tipo = 'dato' if c.get('tipo') == 'dato' else 'opciones'
        opciones = []
        for o in c.get('opciones') or []:
            if isinstance(o, dict) and o.get('clave') and o.get('etiqueta'):
                opciones.append({'clave': _texto(o['clave'], 40), 'etiqueta': _texto(o['etiqueta'], 200),
                                 'filas': o.get('filas') if isinstance(o.get('filas'), list) else [],
                                 'codigo_subitem': _texto(o.get('codigo_subitem'), 30)})
            elif tipo == 'dato' and isinstance(o, str) and o.strip():
                opciones.append({'clave': _texto(o, 40), 'etiqueta': _texto(o, 200), 'filas': [], 'codigo_subitem': ''})
        if tipo == 'opciones' and len(opciones) < 2:
            continue
        # TODA pregunta lleva una respuesta recomendada: la de la IA si es una de las opciones (por clave o por su texto);
        # si no, la primera opción (la IA las ordena de más a menos recomendable); si solo dio el texto, se ofrece como opción.
        bruta = str(c.get('recomendada') or '').strip()
        claves = {o['clave'] for o in opciones}
        recomendada = _texto(bruta, 40)
        if opciones and recomendada not in claves:
            recomendada = next((o['clave'] for o in opciones if bruta and clave_texto(o['etiqueta']) == clave_texto(bruta)), opciones[0]['clave'])
        elif not opciones and tipo == 'dato' and bruta:
            opciones = [{'clave': _texto(bruta, 40), 'etiqueta': _texto(bruta, 200), 'filas': [], 'codigo_subitem': ''}]
            recomendada = opciones[0]['clave']
        salida.append({'id': _texto(c.get('id'), 20) or f'c{i}', 'tipo': tipo, 'pregunta': _texto(c.get('pregunta'), 400),
                       'motivo': _texto(c.get('motivo'), 400), 'recomendada': recomendada, 'por_que': _texto(c.get('por_que'), 400),
                       'opciones': opciones})
    return salida


def normalizar_propuesta(datos, tipo, con_defectos=True):
    """Respuesta de `apu-insumos`: filas, consultas y, en mano de obra, rendimiento y horas de jornada."""
    filas = [f for f in (normalizar_fila(x, tipo) for x in (datos.get('filas') or [])) if f]
    consultas = normalizar_consultas(datos.get('consultas'))
    for c in consultas:  # las filas de cada opción también se normalizan
        for o in c['opciones']:
            o['filas'] = [f for f in (normalizar_fila(x, tipo) for x in o['filas']) if f]
            for f in o['filas']:
                f['consulta'] = c['id']
    # Salvaguarda: una fila que ya viene dentro de una opción no debe repetirse en el nivel superior (se contaría dos veces).
    en_opciones = {clave_texto(f['descripcion']) for c in consultas for o in c['opciones'] for f in o['filas']}
    filas = [f for f in filas if clave_texto(f['descripcion']) not in en_opciones]
    for f in filas:  # una cantidad cero no aporta nada: queda desmarcada para que la persona decida
        if tipo != 'mano_obra' and numero(f.get('cantidad'), Decimal(0)) <= 0:
            f['check'] = False
    propuesta = {'filas': filas, 'consultas': consultas}
    if tipo == 'mano_obra':
        # El rendimiento no tiene valor por defecto: si la IA no lo dio (o dio 0 porque aún pregunta), la persona lo completa.
        for campo, defecto in (('rendimiento', None), ('horas_jornada', Decimal(8) if con_defectos else None)):
            valor = numero(datos.get(campo), defecto)
            if valor is not None and valor > 0:
                propuesta[campo] = texto_numero(valor)
    return propuesta


def normalizar_precios(datos, permitidos, moneda):
    """Sugerencias de precio de la IA como {insumo_id: {precio, moneda, confianza, fuente, nota}}. Solo de los insumos
    pedidos (`permitidos`, ids) y con un precio válido (> 0). Son recomendaciones, no precios guardados."""
    salida = {}
    for c in datos.get('precios') or []:
        if not isinstance(c, dict):
            continue
        try:
            pk = int(c.get('id'))
        except (TypeError, ValueError):
            continue
        precio = numero(c.get('precio'))
        if pk not in permitidos or precio is None or precio <= 0:
            continue
        confianza = str(c.get('confianza') or '').lower()
        salida[pk] = {'precio': texto_numero(precio), 'moneda': (str(c.get('moneda') or moneda)[:3] or moneda).upper(),
                      'confianza': confianza if confianza in ('alta', 'media', 'baja') else 'baja',
                      'fuente': _texto(c.get('fuente'), 200), 'nota': _texto(c.get('nota'), 300)}
    return salida


# ── Tokens y costo ────────────────────────────────────────────────────────────

def _modelo_de(nodo_params, item):
    """Nombre del modelo: el que respondió (sin la fecha de versión: «gpt-5.1-2025-11-13» → «gpt-5.1», para casar con
    las tarifas) o, si no viene, el configurado en el nodo."""
    for gens in ((item.get('json') or {}).get('response') or {}).get('generations') or []:
        for g in gens or []:
            nombre = (g.get('generationInfo') or {}).get('model_name')
            if nombre:
                return re.sub(r'-\d{4}-\d{2}-\d{2}$', '', str(nombre))
    modelo = nodo_params.get('model')
    return modelo.get('value') if isinstance(modelo, dict) else modelo


def uso_de_ejecucion(ejecucion):
    """{modelo: {'entrada': n, 'salida': n[, 'estimado': True]}} a partir del JSON de una ejecución de n8n
    (`includeData=true`). Si OpenAI no reportó el uso real (`tokenUsage`), n8n solo guarda una estimación
    (`tokenUsageEstimate`: la entrada se estima del texto enviado y la salida suele quedar en 0): se usa y se marca
    `estimado`."""
    nodos = {n.get('name'): n for n in (ejecucion.get('workflowData') or {}).get('nodes', [])}
    corridas = ((ejecucion.get('data') or {}).get('resultData') or {}).get('runData') or {}
    uso = {}
    for nombre, runs in corridas.items():
        params = (nodos.get(nombre) or {}).get('parameters') or {}
        for run in runs:
            for salidas in ((run.get('data') or {}).get('ai_languageModel') or []):
                for item in salidas or []:
                    datos = item.get('json') or {}
                    tokens, estimado = datos.get('tokenUsage') or {}, False
                    if not tokens:
                        tokens, estimado = datos.get('tokenUsageEstimate') or {}, True
                    if not tokens:
                        continue
                    fila = uso.setdefault(_modelo_de(params, item) or nombre, {'entrada': 0, 'salida': 0})
                    fila['entrada'] += int(tokens.get('promptTokens') or 0)
                    fila['salida'] += int(tokens.get('completionTokens') or 0)
                    if estimado:
                        fila['estimado'] = True
    return uso


def costo_de_uso(uso):
    """Costo en USD con las tarifas guardadas; None si algún modelo no tiene tarifa."""
    tarifas = {t.modelo: t for t in TarifaModeloIA.objects.filter(modelo__in=list(uso))}
    total = Decimal(0)
    for modelo, v in uso.items():
        if modelo not in tarifas:
            return None
        total += tarifas[modelo].costo(v['entrada'], v['salida'])
    return total.quantize(Decimal('0.000001'))


def probar_api_n8n(api_url, api_key):
    """Comprueba la URL y la clave de la API de n8n sin guardar nada. Devuelve (ok, mensaje apto para mostrar)."""
    api_url = (api_url or '').strip().rstrip('/')
    if not api_url or not (api_key or '').strip():
        return False, 'Falta la URL o la API key de n8n.'
    try:
        r = requests.get(f'{api_url}/api/v1/executions', params={'limit': 1},
                         headers={'X-N8N-API-KEY': api_key.strip()}, timeout=10)
    except requests.RequestException:
        return False, f'No se pudo conectar con n8n en {api_url}. Revisa la URL y que n8n esté en marcha.'
    if r.status_code in (401, 403):
        return False, (f'n8n rechazó la API key (error {r.status_code}). Debe ser una clave creada en el n8n de {api_url} '
                       '(Settings → n8n API), no de otra instancia.')
    if r.status_code == 404:
        return False, f'{api_url} respondió, pero no tiene la API pública de n8n (/api/v1). Revisa la URL.'
    if not r.ok:
        return False, f'n8n respondió con el error {r.status_code}.'
    return True, f'Conexión correcta con n8n en {api_url}: la API key es válida.'


ESTADO_MEDICION = {'motivo': ''}   # por qué la última sincronización no pudo medir (se muestra al superusuario)


def sincronizar_uso(llamadas):
    """Completa `uso` y `costo_usd` de las llamadas aún sin medir, consultando la API pública de n8n DE LA EMPRESA de
    cada llamada (empresa → Credenciales; cada empresa tiene su propia clave). Un fallo deja la llamada pendiente (no
    rompe nada) y deja el motivo en `ESTADO_MEDICION`. Devuelve cuántas se sincronizaron."""
    from cuentas.models import CredencialesEmpresa
    ESTADO_MEDICION['motivo'] = ''
    motivos, credenciales, bloqueadas = {}, {}, set()
    hechas = no_disponibles = 0
    for ll in llamadas:
        if ll.uso is not None or not ll.ejecucion_id or ll.empresa_id in bloqueadas:
            continue
        if ll.empresa_id not in credenciales:
            credenciales[ll.empresa_id] = CredencialesEmpresa.n8n_api(ll.empresa)
        api_url, api_key = credenciales[ll.empresa_id]
        nombre = ll.empresa.nombre
        if not (api_url and api_key):
            motivos[ll.empresa_id] = f'{nombre}: la medición está desactivada: falta la URL o la API key de n8n (empresa → Credenciales).'
            bloqueadas.add(ll.empresa_id)
            continue
        try:
            r = requests.get(f"{api_url}/api/v1/executions/{ll.ejecucion_id}",
                             params={'includeData': 'true'}, headers={'X-N8N-API-KEY': api_key}, timeout=20)
        except requests.RequestException as e:
            logger.warning('No se pudo conectar con n8n (%s): %s', api_url, e)
            motivos[ll.empresa_id] = f'{nombre}: No se pudo conectar con n8n en {api_url}.'
            bloqueadas.add(ll.empresa_id)    # sin conexión no tiene sentido seguir con las demás llamadas de esa empresa
            continue
        if r.status_code in (401, 403):
            motivos[ll.empresa_id] = (f'{nombre}: n8n rechazó la clave de la API (error {r.status_code}). Revisa la clave en '
                                      f'empresa → Credenciales: debe ser una clave creada en el n8n de {api_url}.')
            bloqueadas.add(ll.empresa_id)
            continue
        if r.status_code == 404:
            no_disponibles += 1      # n8n limpia las ejecuciones antiguas: esa ya no se puede medir
            continue
        try:
            r.raise_for_status()
            uso = uso_de_ejecucion(r.json())
        except (requests.RequestException, ValueError) as e:
            logger.warning('No se pudo leer la ejecución %s de n8n: %s', ll.ejecucion_id, e)
            motivos.setdefault(ll.empresa_id, f'{nombre}: n8n respondió con un error al leer la ejecución {ll.ejecucion_id}.')
            continue
        ll.uso, ll.costo_usd = uso, costo_de_uso(uso)
        ll.save(update_fields=['uso', 'costo_usd'])
        hechas += 1
    lista = list(motivos.values())
    if no_disponibles and not lista:
        lista.append(f'n8n ya no conserva {no_disponibles} ejecución(es): se limpian con el tiempo.')
    ESTADO_MEDICION['motivo'] = ' · '.join(lista)
    return hechas


def resumen_uso(llamadas):
    """Consumo por modelo de un conjunto de llamadas: [{'modelo', 'llamadas', 'entrada', 'salida', 'costo'}] y totales.
    `costo` es None si algún modelo no tiene tarifa."""
    llamadas = list(llamadas)
    por_modelo, pendientes, duracion, costo_total, completo = {}, 0, 0, Decimal(0), True
    for ll in llamadas:
        duracion += ll.duracion_ms
        if ll.uso is None:
            pendientes += 1
            continue
        if ll.costo_usd is None and ll.uso:
            completo = False
        else:
            costo_total += ll.costo_usd or Decimal(0)
        for modelo, v in ll.uso.items():
            fila = por_modelo.setdefault(modelo, {'modelo': modelo, 'llamadas': 0, 'entrada': 0, 'salida': 0})
            fila['llamadas'] += 1
            fila['entrada'] += v.get('entrada', 0)
            fila['salida'] += v.get('salida', 0)
            if v.get('estimado'):
                fila['estimado'] = True
    filas = sorted(por_modelo.values(), key=lambda f: f['modelo'])
    return {'modelos': filas, 'entrada': sum(f['entrada'] for f in filas), 'salida': sum(f['salida'] for f in filas),
            'costo': costo_total if completo else None, 'pendientes': pendientes, 'duracion_ms': duracion,
            'llamadas': len(llamadas), 'motivo': ESTADO_MEDICION['motivo'] if pendientes else ''}
