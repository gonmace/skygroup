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
            'tarifas': 'apu-tarifas'}
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
        fila['personas'] = str(numero(crudo.get('personas'), Decimal(1)))
    else:
        fila['cantidad'] = str(numero(crudo.get('cantidad'), Decimal(0)))
    if tipo == 'materiales':
        fila['desperdicio_pct'] = str(numero(crudo.get('desperdicio_pct'), Decimal(0)))
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
        recomendada = _texto(c.get('recomendada'), 40)
        if opciones and recomendada not in {o['clave'] for o in opciones} and tipo == 'opciones':
            recomendada = opciones[0]['clave']
        salida.append({'id': _texto(c.get('id'), 20) or f'c{i}', 'tipo': tipo, 'pregunta': _texto(c.get('pregunta'), 400),
                       'motivo': _texto(c.get('motivo'), 400), 'recomendada': recomendada, 'opciones': opciones})
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
    propuesta = {'filas': filas, 'consultas': consultas}
    if tipo == 'mano_obra':
        for campo, defecto in (('rendimiento', Decimal(1)), ('horas_jornada', Decimal(8))):
            valor = numero(datos.get(campo), defecto if con_defectos else None)
            if valor is not None:
                propuesta[campo] = str(valor)
    return propuesta


# ── Tokens y costo ────────────────────────────────────────────────────────────

def uso_de_ejecucion(ejecucion):
    """{modelo: {'entrada': n, 'salida': n}} a partir del JSON de una ejecución de n8n (`includeData=true`)."""
    nodos = {n.get('name'): n for n in (ejecucion.get('workflowData') or {}).get('nodes', [])}
    corridas = ((ejecucion.get('data') or {}).get('resultData') or {}).get('runData') or {}
    uso = {}
    for nombre, runs in corridas.items():
        params = (nodos.get(nombre) or {}).get('parameters') or {}
        modelo = params.get('model')
        modelo = modelo.get('value') if isinstance(modelo, dict) else modelo
        for run in runs:
            for salidas in ((run.get('data') or {}).get('ai_languageModel') or []):
                for item in salidas or []:
                    tokens = (item.get('json') or {}).get('tokenUsage') or {}
                    if not tokens:
                        continue
                    fila = uso.setdefault(modelo or nombre, {'entrada': 0, 'salida': 0})
                    fila['entrada'] += int(tokens.get('promptTokens') or 0)
                    fila['salida'] += int(tokens.get('completionTokens') or 0)
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


def sincronizar_uso(llamadas):
    """Completa `uso` y `costo_usd` de las llamadas aún sin medir, consultando la API pública de n8n. Un fallo deja la
    llamada pendiente (no rompe nada). Devuelve cuántas se sincronizaron."""
    if not (settings.N8N_API_URL and settings.N8N_API_KEY):
        return 0
    hechas = 0
    for ll in llamadas:
        if ll.uso is not None or not ll.ejecucion_id:
            continue
        try:
            r = requests.get(f"{settings.N8N_API_URL.rstrip('/')}/api/v1/executions/{ll.ejecucion_id}",
                             params={'includeData': 'true'}, headers={'X-N8N-API-KEY': settings.N8N_API_KEY}, timeout=20)
            r.raise_for_status()
            uso = uso_de_ejecucion(r.json())
        except (requests.RequestException, ValueError) as e:
            logger.warning('No se pudo leer la ejecución %s de n8n: %s', ll.ejecucion_id, e)
            continue
        ll.uso, ll.costo_usd = uso, costo_de_uso(uso)
        ll.save(update_fields=['uso', 'costo_usd'])
        hechas += 1
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
    filas = sorted(por_modelo.values(), key=lambda f: f['modelo'])
    return {'modelos': filas, 'entrada': sum(f['entrada'] for f in filas), 'salida': sum(f['salida'] for f in filas),
            'costo': costo_total if completo else None, 'pendientes': pendientes, 'duracion_ms': duracion,
            'llamadas': len(llamadas)}
