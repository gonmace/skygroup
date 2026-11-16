"""PDF de los APU de un proyecto: resumen con presupuesto y, por cada APU, su composición y desglose de precio (PyMuPDF)."""
import io
from decimal import Decimal
from html import escape

import pymupdf

from . import calculo

CSS = '''
body { font-family: sans-serif; font-size: 8.5pt; color: #1f2937; }
h1 { font-size: 17pt; margin: 0 0 2pt 0; }
h2 { font-size: 12pt; margin: 4pt 0 2pt 0; padding-bottom: 2pt; border-bottom: 1px solid #94a3b8; color: #0f172a; }
h3 { font-size: 9pt; margin: 5pt 0 1pt 0; color: #475569; }
table { width: 100%; }
td, th { padding: 1pt 4pt; vertical-align: top; border-bottom: 0.5pt solid #e2e8f0; }
th { text-align: left; color: #475569; font-weight: bold; background-color: #f1f5f9; }
.sub { color: #64748b; }
.num { text-align: right; }
.tot td, .tot th { font-weight: bold; }
'''


MAX_PAGINAS_POR_APU = 60


def _t(v):
    return escape('' if v is None else str(v))


def _n(v, dec=2):
    if v is None:
        return '—'
    s = f'{Decimal(v):,.{dec}f}'
    return s.replace(',', ' ').replace('.', ',')


def _q(v):
    """Cantidad sin ceros sobrantes."""
    if v is None:
        return '—'
    s = format(Decimal(v).normalize(), 'f')
    return s.replace('.', ',')


def _resumen(proyecto, resumen):
    pa = getattr(proyecto, 'apu', None)
    meta = [f'Perfil: {_t(pa.perfil.nombre)}' if pa else '', f'Precios: {_t(resumen["region"] or "nacionales")}']
    filas = ''.join(
        f'<tr><td>{_t(f["item"].codigo)}</td><td>{_t(f["item"].descripcion)}</td><td>{_t(f["item"].unidad)}</td>'
        f'<td class="num">{_q(f["metrado"])}</td><td class="num">{_n(f["total"])}</td><td class="num">{_n(f["subtotal"])}</td></tr>'
        for f in resumen['filas'])
    return (f'<h1>APU · {_t(proyecto.nombre)}</h1><p class="sub">{" · ".join(m for m in meta if m)}</p>'
            f'<h2>Resumen</h2><table width="100%"><tr><th>Código</th><th>Descripción</th><th>Un.</th><th class="num">Cantidad</th>'
            f'<th class="num">P. unitario ({_t(resumen["moneda"])})</th><th class="num">Subtotal</th></tr>{filas}'
            f'<tr class="tot"><td colspan="5">Presupuesto estimado ({resumen["n_con_metrado"]} de {resumen["n"]} APU con cantidad)</td>'
            f'<td class="num">{_n(resumen["presupuesto"])}</td></tr></table>')


def _fila_insumo(f):
    extra = (f' (+{_q(f.desperdicio_pct)} % desp.)' if f.desperdicio_pct else '') + (' · sin precio' if f.sin_precio else '')
    return (f'<tr><td>{_t(f.nombre)}<span class="sub">{_t(extra)}</span></td><td class="num">{_q(f.cantidad)} {_t(f.unidad)}</td>'
            f'<td class="num">{_n(f.precio)}</td><td class="num">{_n(f.costo)}</td></tr>')


def _fila_linea(l, valores, fuerte=False):
    """Una línea del perfil (porcentaje, subtotal o total) con su % y su valor."""
    pct = f'{_q(l["pct"] * 100)} %' if l.get('pct') is not None and l['tipo'] == 'porcentaje' else ''
    cls = ' class="tot"' if fuerte else ''
    return (f'<tr{cls}><td>{_t(l["nombre"])}</td><td></td><td class="num">{pct}</td>'
            f'<td class="num">{_n(valores.get(l["cod"]))}</td></tr>')


def _bloques(a):
    """Reparte las líneas del perfil por bloque: para cada grupo (MAT, MO, EQ) su suma, los recargos que lo afectan (p. ej.
    beneficios sociales, IVA sobre mano de obra, herramientas) y su subtotal de cierre; el resto (costo directo, gastos
    generales, utilidad, impuestos, total) queda para el final. Devuelve ({grupo: {suma, miembros, cierre}}, finales)."""
    lineas = [l for l in a.perfil['lineas'] if l['cod'] in a.resultado.lineas]
    por_cod = {l['cod']: l for l in lineas}
    sumas = {l['grupo']: l for l in lineas if l['tipo'] == 'suma'}
    cierres = {}
    for l in lineas:
        if l['tipo'] != 'subtotal':
            continue
        directas = [b for b in l['base'] if b in por_cod and por_cod[b]['tipo'] == 'suma']
        if len(directas) == 1 and not any(b in {c['cod'] for c in cierres.values()} for b in l['base']):
            cierres.setdefault(por_cod[directas[0]]['grupo'], l)
    cods_cierre = {c['cod'] for c in cierres.values()}
    bloques, usados = {}, set()
    for g, suma in sumas.items():
        cierre = cierres.get(g)
        miembros, pila = set(), list(cierre['base']) if cierre else []
        while pila:
            c = pila.pop()
            l = por_cod.get(c)
            if not l or l['tipo'] == 'suma' or c in cods_cierre or c in miembros:
                continue
            miembros.add(c)
            pila.extend(l.get('base') or [])
        orden = [l for l in lineas if l['cod'] in miembros]
        bloques[g] = {'suma': suma, 'miembros': orden, 'cierre': cierre}
        usados |= miembros | ({cierre['cod']} if cierre else set())
    finales = [l for l in lineas if l['tipo'] != 'suma' and l['cod'] not in usados]
    return bloques, finales


def _detalle(item, region, perfil):
    a = calculo.analizar(item, region=region, perfil=perfil)
    html = (f'<h2>{_t(item.codigo)} · {_t(item.descripcion)}</h2><p class="sub">Unidad: {_t(item.unidad)}'
            f'{" · Precio unitario: " + _n(a.total) + " " + _t(a.moneda) if a.total is not None else ""}</p>')
    if not a.secciones:
        return html + '<p class="sub">Sin composición.</p>'
    valores = a.resultado.lineas if a.resultado else {}
    bloques, finales = _bloques(a) if (a.perfil and a.resultado) else ({}, [])
    cabecera = ('<tr><th style="width:245pt">Insumo</th><th style="width:70pt" class="num">Cantidad</th><th style="width:70pt" class="num">Precio / %</th>'
                '<th style="width:70pt" class="num">Costo</th></tr>')
    cuerpo = ''
    for sec in a.secciones:
        if sec['clave'] == 'SUB':
            continue
        cuerpo += f'<h3>{_t(sec["nombre"])}</h3><table width="100%">{cabecera}'
        cuerpo += ''.join(_fila_insumo(f) for f in sec['filas'])
        b = bloques.get(sec['clave'])
        if b:
            cuerpo += _fila_linea({**b['suma'], 'nombre': f'Subtotal {sec["nombre"].lower()}', 'tipo': 'subtotal'}, valores, fuerte=not b['cierre'])
            cuerpo += ''.join(_fila_linea(l, valores, fuerte=l['tipo'] == 'subtotal') for l in b['miembros'])
            if b['cierre']:
                cuerpo += _fila_linea(b['cierre'], valores, fuerte=True)
        else:
            cuerpo += f'<tr class="tot"><td>Subtotal {_t(sec["nombre"].lower())}</td><td></td><td></td><td class="num">{_n(sec["subtotal"])}</td></tr>'
        cuerpo += '</table>'
    sub = next((s for s in a.secciones if s['clave'] == 'SUB'), None)
    if sub:
        cuerpo += (f'<h3>Sub-análisis <span class="sub">(su costo ya está incluido en los bloques de arriba)</span></h3><table width="100%">{cabecera}'
                   + ''.join(_fila_insumo(f) for f in sub['filas']) + '</table>')
    if finales:
        cuerpo += '<h3>Costo total</h3><table width="100%">' + cabecera.replace('Insumo', 'Concepto') + ''.join(
            _fila_linea(l, valores, fuerte=l['tipo'] == 'subtotal' or bool(l.get('total'))) for l in finales) + '</table>'
    return html + cuerpo


def generar(proyecto):
    """Bytes del PDF con el resumen y el análisis de cada APU del proyecto."""
    resumen = calculo.resumen_proyecto(proyecto)
    pa = getattr(proyecto, 'apu', None)
    perfil = pa.perfil_efectivo() if pa else None
    partes = [_resumen(proyecto, resumen)] + [_detalle(f['item'], resumen['region'], perfil) for f in resumen['filas']]

    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    caja = pymupdf.paper_rect('a4')
    zona = caja + (40, 48, -40, -52)
    for html in partes:          # cada APU empieza en una página nueva
        story = pymupdf.Story(html=html, user_css=CSS)
        mas, paginas = True, 0
        while mas:
            paginas += 1
            if paginas > MAX_PAGINAS_POR_APU:   # salvaguarda: si el motor no avanza no se queda en bucle ni agota la memoria
                raise ValueError('No se pudo componer el PDF: un APU no cabe en la página.')
            dev = writer.begin_page(caja)
            mas, _ = story.place(zona)
            story.draw(dev)
            writer.end_page()
    writer.close()

    doc = pymupdf.open('pdf', buf.getvalue())
    total = doc.page_count
    for i, pagina in enumerate(doc, start=1):
        r = pagina.rect
        pagina.insert_text((40, r.height - 28), f'APU · {proyecto.nombre}', fontsize=8, color=(.4, .45, .5))
        pagina.insert_text((r.width - 90, r.height - 28), f'Página {i} de {total}', fontsize=8, color=(.4, .45, .5))
    salida = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return salida
