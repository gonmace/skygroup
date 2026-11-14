"""Llamadas de skygroup a webhooks de n8n (dirección Django → n8n; la inversa está en `core/interno.py`).

Criterio de CEV (~/Django/CEV/core/n8n.py): un webhook por paso del asistente, token opcional en una cabecera
y los fallos traducidos a `N8NError` con un mensaje en español apto para mostrar.
"""
import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class N8NError(Exception):
    """Fallo al llamar un webhook de n8n, con mensaje apto para mostrar al usuario."""


def webhook_url(ruta):
    return f"{settings.N8N_BASE_URL.rstrip('/')}/webhook/{ruta}"


def llamar_webhook(url, payload, timeout=120):
    """POST con el payload y devuelve el JSON parseado (`{}` si la respuesta viene vacía).
    Lanza `requests.RequestException` o `json.JSONDecodeError`; las vistas usan `llamar_webhook_seguro`."""
    headers = {'Content-Type': 'application/json'}
    if settings.N8N_WEBHOOK_TOKEN:
        headers[settings.N8N_WEBHOOK_TOKEN_HEADER] = settings.N8N_WEBHOOK_TOKEN
    respuesta = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if not respuesta.ok:
        raise requests.exceptions.HTTPError(
            f'HTTP {respuesta.status_code} desde {url}: {respuesta.text[:500]}', response=respuesta)
    texto = respuesta.text.strip()
    return respuesta.json() if texto else {}


def llamar_webhook_seguro(url, payload, timeout=120):
    """Como `llamar_webhook`, pero traduce los fallos a `N8NError`."""
    try:
        return llamar_webhook(url, payload, timeout=timeout)
    except requests.exceptions.Timeout:
        raise N8NError('El servicio de IA tardó demasiado en responder. Inténtalo de nuevo.')
    except requests.exceptions.HTTPError as e:
        estado = e.response.status_code if e.response is not None else '?'
        logger.error('Webhook n8n %s respondió HTTP %s: %s', url, estado, e)
        raise N8NError(f'El servicio de IA respondió con un error (HTTP {estado}).')
    except requests.exceptions.RequestException as e:
        logger.error('Error de conexión con el webhook n8n %s: %s', url, e)
        raise N8NError('No se pudo conectar con el servicio de IA.')
    except json.JSONDecodeError:
        raise N8NError('El servicio de IA devolvió una respuesta inválida.')


def desempaquetar(respuesta):
    """n8n envuelve el resultado de formas distintas según el workflow: un dict plano, `{'output': {...}}` o una
    lista de cualquiera de los dos. Normaliza a un dict plano, o `{}` si no reconoce la forma."""
    dato = respuesta
    if isinstance(dato, list):
        dato = dato[0] if dato else {}
    if isinstance(dato, dict) and isinstance(dato.get('output'), dict):
        dato = dato['output']
    return dato if isinstance(dato, dict) else {}
