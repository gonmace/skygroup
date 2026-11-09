"""API para que los módulos emitan avisos: `notificar(...)`."""
from django.db import transaction


def ruta_segura(url):
    """Solo rutas internas: empiezan con una sola «/» (nada de //host ni esquemas)."""
    return bool(url) and url.startswith('/') and not url.startswith('//') and '\\' not in url and '\n' not in url


def notificar(destinatario, empresa, mensaje, *, url='', actor=None):
    """Crea un aviso. Un actor no se notifica a sí mismo. Devuelve la Notificacion o None."""
    from .models import Notificacion
    if actor is not None and actor.pk == destinatario.pk:
        return None
    if url and not ruta_segura(url):
        raise ValueError(f'La URL de una notificación debe ser una ruta interna: {url!r}')
    notif = Notificacion.objects.create(
        destinatario=destinatario, empresa=empresa, actor=actor, mensaje=mensaje[:240], url=url,
    )
    transaction.on_commit(lambda: _empujar(notif))
    return notif


def notificar_a_varios(destinatarios, empresa, mensaje, **kwargs):
    return [n for n in (notificar(u, empresa, mensaje, **kwargs) for u in destinatarios) if n]


def _empujar(notif):
    """Hook para el push en tiempo real (se enchufa en consumers.py cuando hay Channels)."""
    try:
        from .consumers import empujar_notificacion
    except ImportError:
        return
    empujar_notificacion(notif)
