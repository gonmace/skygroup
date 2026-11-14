"""Piezas de interfaz comunes a la pantalla de detalle de todos los registros (TX/TSS, Construcción, Supervisión...).

    {% load reg_ui %}
    {% reg_tarjeta "Título" contador=3 enlace_url=url enlace_texto="Ver todos" %}…contenido…{% endreg_tarjeta %}

Todo contenedor que va bajo la línea de pasos se arma con `reg_tarjeta` (mismo borde, espaciado y encabezado) y la tarjeta
de imágenes es siempre `reg_base/_imagenes.html`, para que las pantallas no se desvíen unas de otras.
"""
from django import template
from django.template.loader import render_to_string

register = template.Library()


@register.simple_block_tag(takes_context=True)
def reg_tarjeta(context, content, titulo='', contador=None, enlace_url='', enlace_texto='', clase=''):
    return render_to_string('reg_base/_tarjeta.html', {
        'titulo': titulo, 'contador': contador, 'enlace_url': enlace_url, 'enlace_texto': enlace_texto,
        'clase': clase, 'contenido': content}, request=context.get('request'))
