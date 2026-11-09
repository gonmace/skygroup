import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()
NUM_COLORES_AVATAR = 8


@register.filter
def avatar_color(user):
    """Índice (0-7) de color pastel estable por usuario (deriva del pk)."""
    return (getattr(user, 'pk', None) or 0) % NUM_COLORES_AVATAR


@register.filter
def as_list(obj):
    """Envuelve un objeto en una lista de un elemento (avatar-stack con un solo ejecutor)."""
    return [obj]


@register.filter
def ids_familia_division(t):
    """pk del padre de `t` + pks de sus otras partes (hermanas), separados por coma."""
    if not t.padre_id:
        return ''
    ids = [str(t.padre_id)] + [str(c.pk) for c in t.padre.hijos.all() if c.pk != t.pk]
    return ','.join(ids)


@register.filter
def tiene_hijo_dividido(hijos):
    """True si alguno de `hijos` es una parte dividida (icono tijera vs. flecha de «derivado»)."""
    return any(c.es_parte_dividida for c in hijos)


_URL_RE = re.compile(r'(?P<url>(?:https?://|www\.)[^\s<>"\']+)')
_LIMITE_VISIBLE = 60


def _acortar(url):
    if len(url) <= _LIMITE_VISIBLE:
        return url
    mitad = (_LIMITE_VISIBLE - 1) // 2
    return url[:mitad] + '…' + url[-mitad:]


@register.filter
def urlizar_chat(valor):
    """Convierte las URLs del texto en enlaces (target=_blank, noopener). Escapa todo lo demás, así que
    no hay riesgo de HTML arbitrario; compatible con whitespace-pre-wrap."""
    if not valor:
        return valor
    salida, ultimo = [], 0
    for m in _URL_RE.finditer(valor):
        salida.append(escape(valor[ultimo:m.start()]))
        url = m.group('url')
        href = url if url.startswith(('http://', 'https://')) else 'https://' + url
        salida.append(f'<a href="{escape(href)}" class="link link-primary break-all" target="_blank" '
                      f'rel="noopener noreferrer">{escape(_acortar(url))}</a>')
        ultimo = m.end()
    salida.append(escape(valor[ultimo:]))
    return mark_safe(''.join(salida))


@register.filter
def seleccionado(pk, valores):
    """True si `pk` está entre los valores de un campo M2M del form (strings tras un POST, ints si viene
    de la instancia)."""
    return bool(valores) and str(pk) in {str(v) for v in valores}
