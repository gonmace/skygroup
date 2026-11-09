from django import template

register = template.Library()


@register.filter
def horas_min(minutos):
    """90 → «1 h 30 min»; 45 → «45 min»; 120 → «2 h»."""
    try:
        minutos = int(minutos)
    except (TypeError, ValueError):
        return ''
    h, m = divmod(max(minutos, 0), 60)
    if h and m:
        return f'{h} h {m} min'
    return f'{h} h' if h else f'{m} min'
