import re

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from tar_tickets.templatetags.tareas_extras import urlizar_chat

from .. import servicios

register = template.Library()
_MENCION = re.compile(r'((?<![\w/.])@[\w.\-]+)')


@register.filter
def mensaje_html(msg):
    """Texto del mensaje: escapado, con enlaces y con las @menciones de personas reales resaltadas."""
    reales = {servicios.handle(u) for u in msg.menciones.all()}
    salida = []
    for i, trozo in enumerate(_MENCION.split(msg.texto or '')):
        if i % 2 == 0:
            salida.append(urlizar_chat(trozo) or '')
            continue
        nombre = trozo[1:].rstrip('.-')
        cola = trozo[1 + len(nombre):]
        if nombre.lower() in reales:
            salida.append(format_html('<span class="mencion">@{}</span>{}', nombre, cola))
        else:
            salida.append(escape(trozo))
    return mark_safe(''.join(str(s) for s in salida))


@register.filter
def tamano_legible(n):
    n = int(n or 0)
    if n >= 1024 * 1024:
        return f'{n / (1024 * 1024):.1f} MB'
    return f'{max(1, round(n / 1024))} KB'
