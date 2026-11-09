import unicodedata
from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify

from cuentas.capacidades import tiene_capacidad
from empresas.acceso import acceso_modulo
from jor_actividades.models import ItemActividad

from jor_empleados.models import ConfigJornadas

from . import certificado, excel, periodo as per, plantilla_base as base_xlsx, servicios

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _id(get, clave):
    v = get.get(clave, '')
    return int(v) if v.isdigit() else None


def _contexto_periodo(request, periodo, **extra):
    hoy = timezone.localdate()
    return {'periodo': periodo, 'meses': list(enumerate((m.capitalize() for m in per.MESES), 1)),
            'anios': list(range(hoy.year - 3, hoy.year + 1)), 'get': request.GET,
            'anio_sel': periodo.desde.year if periodo.desde else hoy.year,
            'mes_sel': periodo.desde.month if periodo.desde else hoy.month,
            'miembros': request.empresa.membresias.filter(activa=True).select_related('user').order_by('user__first_name', 'user__email'),
            **extra}


def _descarga(contenido, nombre):
    r = HttpResponse(contenido, content_type=XLSX)
    r['Content-Disposition'] = f'attachment; filename="{nombre}"'
    return r


CLAVES_PERIODO = ('mode', 'year', 'month', 'from', 'to', 'page')


def _url_con_filtros(request, quitar=CLAVES_PERIODO, **datos):
    """`?…` con los filtros actuales (sin los de `quitar`) más `datos`."""
    base = {k: v for k, v in request.GET.items() if k not in quitar and v}
    return '?' + urlencode({**base, **datos})


def _navegacion_periodo(request, periodo, modos=(('month', 'Mes'), ('range', 'Rango'))):
    """Enlaces de la barra de período: cambio de modo y mes anterior/siguiente. Conservan los demás filtros
    (persona, tipo, nivel…)."""
    hoy = timezone.localdate()

    def url(**datos):
        return _url_con_filtros(request, **datos)

    desde = periodo.desde or hoy.replace(day=1)
    hasta = periodo.hasta or hoy
    anterior = desde.replace(day=1) - timedelta(days=1)
    siguiente = (desde.replace(day=28) + timedelta(days=4)).replace(day=1)
    destinos = {
        'month': url(mode='month', year=desde.year, month=desde.month),
        'range': url(mode='range', **{'from': desde.isoformat(), 'to': hasta.isoformat()}),
        'all': url(mode='all'), 'last': url(mode='last'),
    }
    return {
        'modos_enlaces': [{'nombre': n, 'url': destinos[v], 'activo': periodo.modo == v} for v, n in modos],
        'url_mes_anterior': url(mode='month', year=anterior.year, month=anterior.month),
        'url_mes_siguiente': url(mode='month', year=siguiente.year, month=siguiente.month) if siguiente <= hoy else '',
    }


@acceso_modulo('jor', 'jor.reportes.ver')
def asistencia(request):
    periodo = per.leer(request.GET)
    persona = _id(request.GET, 'persona')
    personas = servicios.asistencia(request.empresa, periodo, persona)
    resumen = {
        'personas': len(personas), 'dias': sum(p['dias'] for p in personas),
        'horas': servicios.hhmm(sum(p['neto_min'] for p in personas)),
        'atraso_min': sum(p['atraso_min'] for p in personas), 'no_cerro': sum(p['no_cerro'] for p in personas),
        'ausencias': sum(p['ausencias'] for p in personas),
    }
    return render(request, 'jor_reportes/asistencia.html', _contexto_periodo(
        request, periodo, personas=personas, persona=persona, resumen=resumen,
        **_navegacion_periodo(request, periodo)))


@acceso_modulo('jor', 'jor.reportes.ver')
def asistencia_excel(request):
    periodo = per.leer(request.GET)
    datos = servicios.asistencia(request.empresa, periodo, _id(request.GET, 'persona'))
    return _descarga(excel.asistencia_xlsx(datos, periodo, request.empresa),
                     f'asistencia-{request.empresa.slug}-{periodo.desde:%Y%m%d}-{periodo.hasta:%Y%m%d}.xlsx')


def _estadisticas(request):
    periodo = per.leer(request.GET, permitir_todo=True)
    gran = request.GET.get('gran')
    datos = servicios.estadisticas(
        request.empresa, periodo, request.GET.get('tipo', ItemActividad.Tipo.HECHO),
        '', _id(request.GET, 'persona'),
        gran if gran in servicios.GRANULARIDADES else 'auto', cargo_id=_id(request.GET, 'cargo'))
    return periodo, datos


def _barras(filas):
    """Agrega `pct` (0-100, relativo al mayor) a cada fila {label, count}."""
    tope = max((f['count'] for f in filas), default=0) or 1
    for f in filas:
        f['pct'] = round(100 * f['count'] / tope)
    return filas


# Sedes con color propio (se reconocen por el nombre, sin tildes ni mayúsculas).
COLORES_SEDE = (('santa cruz', '#15803d'),   # verde
                ('la paz', '#b3354f'),       # guindo claro
                ('cochabamba', '#38bdf8'))   # celeste
# El resto va por posición, con tonos muy separados entre sí y distintos de los tres anteriores.
PALETA_SEDES = ('#f97316', '#9333ea', '#eab308', '#db2777', '#1e3a8a', '#84cc16', '#64748b', '#92400e',
                '#4f46e5', '#0f766e')


def _color_sede(nombre, i):
    """Color propio si la sede es Santa Cruz, La Paz o Cochabamba; si no, uno distinto según su posición."""
    n = unicodedata.normalize('NFKD', nombre.lower()).encode('ascii', 'ignore').decode()
    for clave, color in COLORES_SEDE:
        if clave in n:
            return color
    return PALETA_SEDES[i % len(PALETA_SEDES)]


def _segmentos(valores, cats):
    """Barra apilada al 100 % (x/ancho en str: ver nota de `_grafico_evolucion`)."""
    total = sum(valores) or 1
    x, segmentos = 0.0, []
    for cat, v in zip(cats, valores):
        if v:
            w = v * 100 / total
            segmentos.append({'x': f'{x:.1f}', 'w': f'{w:.1f}', 'color': cat['color'], 'titulo': f"{cat['etiqueta']}: {v:g}"})
            x += w
    return segmentos


def _escala(tope):
    """Máximo 'redondo' (1, 2, 5 × 10^k) ≥ tope y su paso, para 2-4 líneas guía."""
    paso = 1
    while tope / paso > 4:
        paso *= 2 if str(paso)[0] in '15' else 2.5
        paso = int(paso)
    return paso, -(-tope // paso) * paso


def _url_tramo(request, t, gran):
    if gran == 'month':
        return _url_con_filtros(request, mode='month', year=t['desde'].year, month=t['desde'].month)
    return _url_con_filtros(request, mode='range', **{'from': t['desde'].isoformat(), 'to': t['hasta'].isoformat()})


PERSONA_COLOR = '#f97316'


def _grafico_evolucion(request, datos, vista='barras', limite=60):
    """Evolución por tramos, apilada por categoría (`barras`) o una línea por categoría (`lineas`), con líneas guía y
    enlace por tramo. La geometría va como str: con LANGUAGE_CODE='es' los floats se formatean con coma y romperían
    los atributos del SVG."""
    cats = datos['categorias'][:len(datos['codigos'])]
    gran = datos['granularidad']
    tramos = datos['evolucion'][-limite:]
    lineas = vista == 'lineas'
    activas = sorted((i for i, c in enumerate(cats) if c['n']), key=lambda i: -cats[i]['n'])[:8] if lineas else []
    maximo = max((max((t['por_cat'][i] for i in activas), default=0) if lineas else t['total'] for t in tramos), default=0)
    paso, tope = _escala(maximo or 1)
    n = len(tramos) or 1
    paso_x, ancho, alto_max, margen = 100 / n, min(8.0, 100 / n * 0.7), 40, 4
    barras = []
    for i, t in enumerate(tramos):
        y = margen + alto_max
        segmentos = []
        if not lineas:
            for cat, cantidad in zip(cats, t['por_cat']):
                if not cantidad:
                    continue
                alto = cantidad / tope * alto_max
                y -= alto
                segmentos.append({'y': f'{y:.1f}', 'h': f'{alto:.1f}', 'color': cat['color'],
                                  'titulo': f"{t['clave']} · {cat['etiqueta']}: {cantidad}"})
        barras.append({'x': f'{i * paso_x:.1f}', 'xb': f'{i * paso_x + (paso_x - ancho) / 2:.1f}', 'w': f'{ancho:.1f}',
                       'wt': f'{paso_x:.1f}', 'clave': t['clave'], 'total': t['total'], 'segmentos': segmentos,
                       'url': _url_tramo(request, t, gran), 'titulo': f"{t['clave']}: {t['total']} actividades"})
    series = [{'color': cats[i]['color'], 'etiqueta': cats[i]['etiqueta'], 'total': cats[i]['n'],
               'puntos': ' '.join(f"{j * paso_x + paso_x / 2:.1f},{margen + alto_max - t['por_cat'][i] / tope * alto_max:.1f}"
                                  for j, t in enumerate(tramos))} for i in activas]
    guias = [{'y': f'{margen + alto_max - v / tope * alto_max:.1f}', 'valor': v} for v in range(0, int(tope) + 1, int(paso))]
    claves = [t['clave'] for t in tramos]
    marcas = [claves[round(k * (len(claves) - 1) / 5)] for k in range(6)] if len(claves) > 6 else claves
    return {'barras': barras, 'series': series, 'lineas': lineas, 'guias': guias, 'marcas': marcas, 'maximo': int(tope),
            'recortado': len(datos['evolucion']) > limite,
            'etiqueta_gran': {'week': 'semanal', 'month': 'mensual', 'quarter': 'trimestral', 'year': 'anual'}[gran],
            'unidad': {'week': 'semana', 'month': 'mes', 'quarter': 'trimestre', 'year': 'año'}[gran]}


def _donut(categorias, total):
    """Anillo SVG (circunferencia = 100 para que `stroke-dasharray` sea el porcentaje). Empieza arriba."""
    acumulado, trozos = 0.0, []
    for c in sorted((c for c in categorias if c['n']), key=lambda c: -c['n']):
        pct = 100 * c['n'] / total
        trozos.append({'color': c['color'], 'dash': f'{pct:.2f} {100 - pct:.2f}', 'offset': f'{25 - acumulado:.2f}',
                       'etiqueta': c['etiqueta'], 'n': c['n'], 'pct': c['pct'], 'titulo': f"{c['etiqueta']}: {c['n']} ({c['pct']}%)"})
        acumulado += pct
    return trozos


def _abrev(etiqueta):
    palabra = (etiqueta or '').split(' ')[0]
    return palabra[:6] + '.' if len(palabra) > 8 else palabra


def _por_cargo(datos, cats):
    """Cada categoría con una barra por cargo: % del trabajo de ese cargo (como «Supervisores vs PM»)."""
    cargos_cmp = [{'nombre': r['rol']} for r in datos['roles']]   # el cargo se identifica por su nombre, no por color
    tope = max((p for r in datos['roles'] for p in r['pct_cat']), default=0) or 1
    filas = []
    for j, cat in enumerate(cats):
        barras = [{'nivel': cargos_cmp[i]['nombre'], 'color': cat['color'], 'pct': r['pct_cat'][j],
                   'w': f"{r['pct_cat'][j] / tope * 100:.1f}"} for i, r in enumerate(datos['roles'])]
        if any(b['pct'] for b in barras):
            filas.append({'etiqueta': cat['etiqueta'], 'color': cat['color'], 'barras': barras})
    filas.sort(key=lambda f: -sum(b['pct'] for b in f['barras']))
    return cargos_cmp, filas


def _categorias_persona(datos, cats, persona):
    """Persona vs total del período, en % sobre el TOTAL global (el aporte de la persona queda dentro de la barra
    del total de cada categoría)."""
    glob, tg = datos['por_cat_global'], datos['total_global'] or 1
    filas = []
    for i, cat in enumerate(cats):
        total, mio = 100 * glob.get(cat['codigo'], 0) / tg, 100 * persona['por_cat'][i] / tg
        if total or mio:
            filas.append({'etiqueta': cat['etiqueta'], 'color': cat['color'], 'total': round(total, 1), 'persona': round(mio, 1)})
    filas.sort(key=lambda f: (-f['persona'], -f['total']))
    tope = max((f['total'] for f in filas), default=0) or 1
    for f in filas:
        f['w_total'], f['w_persona'] = f"{f['total'] / tope * 100:.1f}", f"{f['persona'] / tope * 100:.1f}"
    return filas


def _etiquetas_segmentadas(lista, cats_por_codigo, color_fijo=None):
    """Barras de proyectos/entregables/sedes: la barra (relativa a la mayor) se divide por categoría."""
    tope = max((e['n'] for e in lista), default=0) or 1
    filas = []
    for i, e in enumerate(lista):
        ancho, x, segmentos = 100 * e['n'] / tope, 0.0, []
        if not color_fijo:
            for codigo, n in sorted(e['por_cat'].items(), key=lambda kv: -kv[1]):
                cat = cats_por_codigo.get(codigo)
                w = ancho * n / e['n']
                segmentos.append({'x': f'{x:.1f}', 'w': f'{w:.1f}', 'color': cat['color'] if cat else '#64748b',
                                  'titulo': f"{cat['etiqueta'] if cat else codigo}: {n}"})
                x += w
        filas.append({'label': e['nombre'], 'count': e['n'], 'texto': e['n'], 'pct': round(ancho),
                      **({'color': color_fijo(e['nombre'], i)} if color_fijo else {'segmentos': segmentos})})
    return filas


@acceso_modulo('jor', 'jor.stats.view')
def estadisticas(request):
    periodo, datos = _estadisticas(request)
    persona_id = _id(request.GET, 'persona')
    cats = datos['categorias'][:len(datos['codigos'])]
    por_codigo = {c['codigo']: c for c in datos['categorias']}
    principal = max(datos['categorias'], key=lambda c: c['n'], default=None)
    categorias_barras = _barras([{'label': c['etiqueta'], 'count': c['n'], 'pct_total': c['pct'], 'color': c['color'],
                                  'texto': f"{c['n']} · {c['pct']}%"}
                                 for c in sorted(datos['categorias'], key=lambda c: -c['n']) if c['n']])

    def etiqueta_cat(codigo):
        c = por_codigo.get(codigo)
        return {'etiqueta': c['etiqueta'] if c else '', 'color': c['color'] if c else '#64748b'}

    personas = []
    for p in datos['personas']:
        personas.append({**p, 'segmentos': _segmentos(p['por_cat'], cats), 'top_cat': etiqueta_cat(p['top']),
                         'segundo_cat': etiqueta_cat(p['segundo']) if p['segundo'] else None,
                         'top_etiqueta': etiqueta_cat(p['top'])['etiqueta'], 'top_color': etiqueta_cat(p['top'])['color'],
                         'url': _url_con_filtros(request, quitar=('persona', 'page'), persona=p['id'])})
    roles = [{**r, 'segmentos': _segmentos(r['por_cat'], cats), 'top_cat': etiqueta_cat(r['top']),
              'segundo_cat': etiqueta_cat(r['segundo']) if r['segundo'] else None} for r in datos['roles']]
    comparacion = cmp_categorias = None
    if persona_id and len(personas) == 1:
        yo = personas[0]
        grupo = next((r for r in datos['roles'] if r['rol_id'] == yo['rol_id']), None)
        if grupo:
            comparacion = {'persona': yo, 'grupo': grupo, 'dif': round(yo['total'] - grupo['promedio'], 1)}
        cmp_categorias = _categorias_persona(datos, cats, yo)
    # Matriz persona × categoría (solo categorías con actividades; con una persona, también los promedios por cargo).
    cols = sorted((i for i, c in enumerate(cats) if c['n'] or (persona_id and any(r['por_cat'][i] for r in roles))),
                  key=lambda i: -cats[i]['n'])
    matriz = {'columnas': [{'etiqueta': cats[i]['etiqueta'], 'abrev': _abrev(cats[i]['etiqueta'])} for i in cols],
              'filas': [{'nombre': p['nombre'], 'rol': p['rol'], 'total': p['total'], 'valores': [p['por_cat'][i] for i in cols]}
                        for p in personas],
              'referencias': [{'nombre': f"Prom. {r['rol']}", 'total': r['promedio'], 'valores': [r['por_cat'][i] for i in cols]}
                              for r in roles] if persona_id else []}
    cargos_cmp, por_cargo = _por_cargo(datos, cats)
    horas = _barras([{'label': r['nombre'], 'count': r['minutos'], 'texto': f"{r['horas_enteras']} h · {r['jornadas']}"}
                     for r in datos['horas_proyecto'] if not r['sin_proyecto']])
    horas_sin_proyecto = next((r for r in datos['horas_proyecto'] if r['sin_proyecto']), None)   # va como nota, no como barra
    tops = [('Proyectos mencionados', _etiquetas_segmentadas(datos['proyectos'], por_codigo)),
            ('Sedes', _etiquetas_segmentadas(datos['ubicaciones'], por_codigo, _color_sede)),
            ('Entregables', _etiquetas_segmentadas(datos['entregables'], por_codigo))]
    cargo_sel = _id(request.GET, 'cargo')
    extra = {}
    if cargo_sel:                                      # al elegir un cargo, la lista de personas se limita a ese cargo
        extra['miembros'] = request.empresa.membresias.filter(activa=True, rol_id=cargo_sel).select_related('user').order_by(
            'user__first_name', 'user__email')
    vista = 'lineas' if request.GET.get('evo') == 'lineas' else 'barras'
    return render(request, 'jor_reportes/estadisticas.html', _contexto_periodo(
        request, periodo, d=datos, persona=persona_id, cargos=request.empresa.roles.filter(activo=True), roles_res=roles, comparacion=comparacion,
        cmp_categorias=cmp_categorias, persona_color=PERSONA_COLOR, matriz=matriz, cargos_cmp=cargos_cmp, por_cargo=por_cargo,
        donut=_donut(datos['categorias'], datos['total'] or 1), vista=vista,
        url_vista_barras=_url_con_filtros(request, quitar=('evo',)), url_vista_lineas=_url_con_filtros(request, quitar=('evo',), evo='lineas'),
        persona_nombre=personas[0]['nombre'] if persona_id and personas else '',
        url_sin_persona=_url_con_filtros(request, quitar=('persona', 'page')),
        personas=personas, categorias_barras=categorias_barras, principal=principal if principal and principal['n'] else None,
        grafico=_grafico_evolucion(request, datos, vista), tops=tops, horas_proyecto=horas, horas_sin_proyecto=horas_sin_proyecto,
        **extra, **_navegacion_periodo(request, periodo, (('month', 'Mes'), ('range', 'Rango'), ('all', 'Todo'), ('last', 'Último día')))))


@acceso_modulo('jor', 'jor.stats.view')
def estadisticas_excel(request):
    _, datos = _estadisticas(request)
    return _descarga(excel.estadisticas_xlsx(datos, request.empresa), f'estadisticas-{request.empresa.slug}.xlsx')


def _fecha(get, clave):
    try:
        return date.fromisoformat(get.get(clave, ''))
    except ValueError:
        return None


@acceso_modulo('jor', 'jor.certificado.generar')
def certificado_pago(request):
    """GET sin parámetros: formulario. Con `descargar=1`: genera el .xlsx del mes o del rango elegido."""
    if 'descargar' not in request.GET:
        hoy = timezone.localdate()
        return render(request, 'jor_reportes/certificado.html', {
            'meses': list(enumerate((m.capitalize() for m in per.MESES), 1)), 'anios': list(range(hoy.year - 3, hoy.year + 1)),
            'anio_sel': hoy.year, 'mes_sel': hoy.month, 'max_dias': certificado.MAX_DAYS,
            'plantilla_propia': bool(ConfigJornadas.de(request.empresa).plantilla_certificado),
            'puede_config': tiene_capacidad(request.user, 'jor.config.manage', request.empresa)})
    g = request.GET
    try:
        anio, mes = int(g.get('year', 0)) or None, int(g.get('month', 0)) or None
    except ValueError:
        anio = mes = None
    fechas, valor, etiqueta = certificado.periodo_certificado(g.get('mode', 'month'), anio, mes,
                                                              _fecha(g, 'from'), _fecha(g, 'to'))
    try:
        contenido = certificado.generar(request.empresa, fechas, valor, request.user)
    except certificado.CertificadoError as e:
        messages.error(request, str(e))
        return redirect('jor_reportes:certificado')
    return _descarga(contenido, f'{slugify(request.empresa.nombre_certificado)}-{request.empresa.slug}-{etiqueta}.xlsx')


@acceso_modulo('jor', 'jor.config.manage')
def descargar_plantilla_base(request):
    """La plantilla base con todas las variables: punto de partida para crear la propia."""
    return _descarga(base_xlsx.bytes_plantilla(), f'plantilla-{slugify(request.empresa.nombre_certificado)}.xlsx')


@acceso_modulo('jor', 'jor.config.manage')
def descargar_plantilla_modelo(request):
    """El certificado de pago de skylog con variables: modelo completo (personal, alimentación por ciudad, hoja por persona)."""
    return _descarga(base_xlsx.bytes_modelo(), f'plantilla-modelo-{slugify(request.empresa.nombre_certificado)}.xlsx')


@acceso_modulo('jor', 'jor.config.manage')
def descargar_plantilla_actual(request):
    """La plantilla que la empresa subió (archivo privado)."""
    config = ConfigJornadas.de(request.empresa)
    if not config.plantilla_certificado:
        raise Http404
    with config.plantilla_certificado.open('rb') as f:
        return _descarga(f.read(), f'plantilla-actual-{slugify(request.empresa.nombre_certificado)}.xlsx')
