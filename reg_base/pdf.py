"""PDF de un registro (cabecera, datos de cada paso y fotos) generado con PyMuPDF. Si el registro no está concluido
se marca cada página con la marca de agua «BORRADOR»."""
import io
from html import escape

import pymupdf

from reg_actividades import mapas, servicios
from reg_actividades.widgets.base import Contexto
from reg_base.geo import formatear_distancia
from reg_fotos.servicios import fotos_de

CSS = '''
body { font-family: sans-serif; font-size: 10pt; color: #1f2937; }
h1 { font-size: 17pt; margin: 0 0 2pt 0; }
h2 { font-size: 12pt; margin: 14pt 0 3pt 0; padding-bottom: 2pt; border-bottom: 1px solid #94a3b8; color: #0f172a; }
h3 { font-size: 10pt; margin: 8pt 0 2pt 0; color: #475569; }
td, th { padding: 2pt 4pt; vertical-align: top; }
th { text-align: left; color: #475569; font-weight: bold; }
.sub { color: #64748b; }
.num { text-align: right; }
.foto td { padding: 3pt; }
.pie { font-size: 8pt; color: #64748b; }
'''


def _t(valor):
    return escape('' if valor is None else str(valor))


def _num(valor):
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return _t(valor)
    return f'{f:.2f}'.rstrip('0').rstrip('.').replace('.', ',')


def _bloque_widget(pw, w, datos, ctx, archivo):
    """HTML con los datos de un componente de paso; '' si no hay nada que mostrar."""
    slug, etiqueta = pw.widget_slug, _t(pw.config.get('label') or w.nombre)
    if hasattr(w, 'html_pdf'):   # el widget sabe pintarse en el PDF (tablas, hallazgos, firma…)
        return w.html_pdf(pw, datos, ctx, archivo)
    if slug in ('mapa_1p', 'mapa_2_puntos'):
        return _mapa_html(pw, w, ctx, etiqueta, archivo)
    if not w.guarda_datos or w.vacio(datos) and slug != 'tabla_avance_widget':
        return ''
    if slug == 'lista_widget':
        items = (datos or {}).get('items') or []
        return f'<h3>{etiqueta}</h3><ul>' + ''.join(f'<li>{_t(i)}</li>' for i in items) + '</ul>' if items else ''
    if slug == 'comentario_widget':
        texto = ((datos or {}).get('texto') or '').strip()
        return f'<h3>{etiqueta}</h3><p>{_t(texto).replace(chr(10), "<br>")}</p>' if texto else ''
    if slug == 'ubicacion_widget':
        d = datos or {}
        if d.get('lat') is None:
            return ''
        return f'<h3>{etiqueta}</h3><p>{_t(d["lat"])}, {_t(d["lon"])}</p>'
    if slug in ('form_dinamico_widget', 'poste_form_widget'):
        campos = w.contexto(datos, pw.config, ctx).get('campos') or []
        filas = ''
        for c in campos:
            valor = ('Sí' if c.get('marcado') else 'No') if c.get('tipo') == 'toggle' else c.get('valor')
            if valor not in (None, ''):
                filas += f'<tr><th width="140">{_t(c.get("label") or c.get("nombre"))}</th><td>{_t(valor)}</td></tr>'
        return f'<h3>{etiqueta}</h3><table class="cab">{filas}</table>' if filas else ''
    if slug == 'tabla_avance_widget':
        c = w.contexto(datos, pw.config, ctx)
        filas = c.get('filas') or []
        if not filas:
            return ''
        cuerpo = ''.join(f'<tr><td>{_t(f.get("nombre"))}</td><td class="num">{_num(f.get("incidencia"))}%</td>'
                         f'<td class="num">{_num(f.get("actual"))}%</td></tr>' for f in filas)
        return (f'<h3>{etiqueta}</h3><table width="100%"><tr><th>Ítem</th><th class="num">Incidencia</th>'
                f'<th class="num">Avance</th></tr>{cuerpo}<tr><th>Total</th><td></td><th class="num">{_num(c.get("total"))}%</th></tr></table>')
    if slug == 'distancia_widget':
        m = (datos or {}).get('distancia_metros')
        return f'<h3>{etiqueta}</h3><p>{_num(m)} m</p>' if m is not None else ''
    return ''


def _mapa_html(pw, w, ctx, etiqueta, archivo):
    """Imagen de mapa ya guardada del paso (no se consulta a Google al generar el PDF); '' si no existe."""
    imagen = mapas.imagen_de(ctx.registro, ctx.paso.nombre)
    if imagen is None:
        return ''
    try:
        with imagen.imagen.open('rb') as fh:
            contenido = fh.read()
    except Exception:
        return ''
    nombre = f'mapa_{imagen.pk}.png'
    archivo.add(contenido, nombre)
    dist = formatear_distancia(imagen.distancia_total_metros) if imagen.distancia_total_metros is not None else ''
    return (f'<h3>{etiqueta}</h3><p><img src="{nombre}" style="width: 300pt;"></p>'
            + (f'<p class="sub">Distancia: {_t(dist)}</p>' if dist else ''))


def _fotos_html(registro, titulos, archivo):
    """HTML de las fotos agrupadas por etapa; añade las imágenes (miniatura) al archivo en memoria."""
    por_etapa, n = {}, 0
    for f in fotos_de(registro):
        campo = f.miniatura or f.imagen
        try:
            with campo.open('rb') as fh:
                contenido = fh.read()
        except Exception:
            continue
        n += 1
        nombre = f'foto{n}.jpg'
        archivo.add(contenido, nombre)
        por_etapa.setdefault(f.etapa, []).append((nombre, f.descripcion))
    html = ''
    for etapa, fotos in por_etapa.items():
        filas = ''
        for i in range(0, len(fotos), 2):
            celdas = ''
            for nombre, desc in fotos[i:i + 2]:
                celdas += (f'<td width="50%"><img src="{nombre}" style="width: 160pt;"><br><span class="sub">{_t(desc)}</span></td>')
            if len(fotos[i:i + 2]) == 1:
                celdas += '<td width="50%"></td>'
            filas += f'<tr>{celdas}</tr>'
        html += f'<h3>Fotos · {_t(titulos.get(etapa, etapa))}</h3><table class="foto" width="100%">{filas}</table>'
    return html


def _referencia(registro):
    """Texto corto que identifica el registro: «visita #n» (construcción) o fecha y alternativa (TX/TSS)."""
    if hasattr(registro, 'referencia_pdf'):
        return registro.referencia_pdf()
    if hasattr(registro, 'numero_visita'):
        return f'visita #{registro.numero_visita}'
    alt = f' · alternativa {registro.alternativa}' if getattr(registro, 'alternativa', '') else ''
    return f'{registro.fecha:%d/%m/%Y}{alt}'


def _cabecera(registro):
    """[(etiqueta, valor)] de la cabecera según el tipo de registro."""
    p = registro.proyecto
    estado = 'Concluido' if registro.concluido else 'En proceso (borrador)'
    if hasattr(registro, 'cabecera_pdf'):
        return registro.cabecera_pdf()
    if hasattr(registro, 'estado_obra'):   # construcción
        return [('Fecha', registro.fecha.strftime('%d/%m/%Y')), ('Obra', registro.nombre_obra or (p.nombre if p else '')),
                ('Descripción', registro.descripcion), ('Revisión', registro.revision),
                ('Estado de la obra', registro.get_estado_obra_display()),
                ('Contratista', registro.contratista.nombre if registro.contratista_id else ''),
                ('ITO', registro.responsable_nombre), ('Avance total', f'{_num(registro.avance_pct)}%'),
                ('Coordenadas', ', '.join(str(c) for c in registro.coordenadas)
                 if registro.coordenadas[0] is not None else '')]
    return [('Fecha', registro.fecha.strftime('%d/%m/%Y')), ('Alternativa', getattr(registro, 'alternativa', '')),
            ('Responsable', registro.responsable_nombre), ('Estado', estado),
            ('Coordenadas', ', '.join(str(c) for c in p.coordenada_principal) if p and p.coordenada_principal[0] is not None else '')]


def generar_pdf(registro, clave, user, titulo_tipo='Registro'):
    """Bytes del PDF del registro. «BORRADOR» como marca de agua si no está concluido."""
    p = registro.proyecto
    datos_pasos = servicios._datos_por_paso(registro)
    archivo = pymupdf.Archive()
    titulos, secciones = (registro.titulos_etapas_pdf() if hasattr(registro, 'titulos_etapas_pdf') else {}), ''
    for a in servicios.asignados_de(registro, clave):
        paso = a.paso
        titulos[paso.nombre] = paso.titulo
        ctx = Contexto(registro=registro, paso=paso, clave=clave, user=user, puede_escribir=False)
        dato = datos_pasos.get(paso.nombre)
        cuerpo = ''.join(_bloque_widget(pw, w, ((dato.datos if dato else {}) or {}).get(pw.widget_slug, {}), ctx, archivo)
                         for pw, w in servicios.widgets_de(paso))
        if cuerpo:
            secciones += f'<h2>{_t(paso.titulo)}</h2>{cuerpo}'
    fotos = _fotos_html(registro, titulos, archivo)
    cab = _cabecera(registro)
    filas = ''.join(f'<tr><th width="110">{k}</th><td>{_t(v)}</td></tr>' for k, v in cab if v not in (None, ''))
    ref = _referencia(registro)
    html = (f'<h1>{_t(titulo_tipo)} · {_t(p.codigo if p else "")}</h1><p class="sub">{_t(p.nombre if p else "")} · '
            f'{_t(ref)}</p><table class="cab" width="100%">{filas}</table>{secciones}'
            + (f'<h2>Fotos</h2>{fotos}' if fotos else ''))

    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    story = pymupdf.Story(html=html, user_css=CSS, archive=archivo)
    caja = pymupdf.paper_rect('a4')
    zona = caja + (40, 48, -40, -52)
    mas = True
    while mas:
        dev = writer.begin_page(caja)
        mas, _ = story.place(zona)
        story.draw(dev)
        writer.end_page()
    writer.close()

    doc = pymupdf.open('pdf', buf.getvalue())
    borrador = not registro.concluido
    total = doc.page_count
    for i, pagina in enumerate(doc, start=1):
        r = pagina.rect
        pagina.insert_text((40, r.height - 28), f'{p.codigo if p else ""} · {ref}'
                           f'{" · BORRADOR" if borrador else ""}', fontsize=8, color=(.4, .45, .5))
        pagina.insert_text((r.width - 90, r.height - 28), f'Página {i} de {total}', fontsize=8, color=(.4, .45, .5))
        if borrador:
            centro = pymupdf.Point(r.width / 2 - 170, r.height / 2 + 60)
            pagina.insert_text(centro, 'BORRADOR', fontsize=96, color=(.8, .1, .1), fill_opacity=.16,
                               fontname='helv', morph=(pymupdf.Point(r.width / 2, r.height / 2), pymupdf.Matrix(45)),
                               overlay=True)
    salida = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return salida
