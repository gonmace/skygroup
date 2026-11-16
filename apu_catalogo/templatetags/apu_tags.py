from decimal import Decimal, InvalidOperation

from django import template
from django.utils.formats import get_format

register = template.Library()


@register.filter
def numlimpio(valor, modo=''):
    """Un número sin ceros de más ni notación científica: 1.5000 → 1,5; 830 → 830; 0.500000 → 0,5. Con el argumento «u»
    deja el punto decimal (para atributos y valores de campos); sin él usa el separador decimal del idioma."""
    if valor in (None, ''):
        return ''
    try:
        d = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return valor
    texto = format(d.normalize(), 'f') if d else '0'
    return texto if modo == 'u' else texto.replace('.', get_format('DECIMAL_SEPARATOR'))


@register.inclusion_tag('apu_catalogo/_unidades_lista.html')
def lista_unidades(id_lista='apu-unidades'):
    """`<datalist>` con las unidades de uso común (abreviatura + nombre). Enlazarlo con `list="apu-unidades"`."""
    from apu_catalogo.unidades import sugerencias
    return {'id_lista': id_lista, 'unidades': sugerencias()}
