"""¿La marcación llega de un celular o de un computador? Barrera razonable, no absoluta: el «modo escritorio» de un
navegador móvil puede engañar parte de las señales; por eso el equipo habitual (jor_empleados.equipos) la complementa."""
import re

_UA_MOVIL = re.compile(r'Android|iPhone|iPad|iPod|Mobile', re.I)


def es_movil(request):
    """True si alguna señal indica un celular: Client Hint `Sec-CH-UA-Mobile`, el User-Agent o lo que calcula el JS
    del navegador (`tipo=movil`: puntero táctil principal, iPad que se presenta como Mac…)."""
    if request.META.get('HTTP_SEC_CH_UA_MOBILE', '').strip() == '?1':
        return True
    if _UA_MOVIL.search(request.META.get('HTTP_USER_AGENT', '')):
        return True
    return request.POST.get('tipo') == 'movil'
