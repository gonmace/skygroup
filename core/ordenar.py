"""Orden por columna en tablas paginadas (en el servidor, para que ordene todo el listado y no solo la página).

    qs, orden = ordenar(request, qs, {'fecha': 'fecha', 'responsable': ('user__first_name', 'user__last_name')},
                        defecto=('-fecha', '-id'))

y en la plantilla, por cada columna ordenable:

    {% include "components/th_orden.html" with col=orden.fecha texto="Fecha" %}

Los parámetros son `orden` (clave de columna) y `dir` (`asc`/`desc`); con varias tablas en la misma página se usan
`param`/`param_dir`/`param_pagina` distintos. Al cambiar el orden se vuelve a la primera página y se conservan los
demás filtros. Los nulos van al final en ambos sentidos. Una clave desconocida se ignora (queda el orden por defecto).
"""
from django.db.models import F


def ordenar(request, qs, columnas, defecto=('-id',), param='orden', param_dir='dir', param_pagina='page'):
    """Devuelve (qs ordenado, {clave: {url, activo, flecha, aria}}). `columnas`: {clave: campo | (campos…)}."""
    clave = request.GET.get(param, '')
    desc = request.GET.get(param_dir) == 'desc'
    if clave not in columnas:
        clave = ''
    if clave:
        campos = columnas[clave]
        campos = (campos,) if isinstance(campos, str) else tuple(campos)
        orden = [F(c).desc(nulls_last=True) if desc else F(c).asc(nulls_last=True) for c in campos]
        qs = qs.order_by(*orden, *defecto)
    else:
        qs = qs.order_by(*defecto)
    encabezados = {}
    for k in columnas:
        activa = k == clave
        sentido = 'desc' if (activa and not desc) else 'asc'
        q = request.GET.copy()
        q[param], q[param_dir] = k, sentido
        q.pop(param_pagina, None)
        encabezados[k] = {
            'url': '?' + q.urlencode(), 'activo': activa,
            'flecha': ('▼' if desc else '▲') if activa else '',
            'aria': ('descending' if desc else 'ascending') if activa else 'none',
        }
    return qs, encabezados
