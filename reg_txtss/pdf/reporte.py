"""PDF «TX / Technical Site Survey» de un registro TX/TSS (poste o torre), con el formato del original reg.tekon-rl.cl.

Reutiliza la hoja de estilos y los ayudantes de imagen del reporte de Construcción. Las secciones salen de los pasos
de la plantilla del registro: «mandato» y «desfase» van primero (con la tabla de datos geográficos entre ambas); el
resto, en el orden de la plantilla. Las imágenes viajan incrustadas (data URI): nada se pide por red."""
import re

from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string

from reg_actividades import mapas, servicios
from reg_actividades.widgets.base import Contexto
from reg_base.geo import distancia_m, formatear_distancia
from reg_construccion.pdf.reporte import CSS, _data_uri, _decimal, _dms
from reg_fotos.models import Foto

from ..models import RegTxtss

PRIMEROS = ('mandato', 'desfase')
PASOS_INSPECCION = ('poste', 'sitio')   # paso cuya ubicación es la «inspección» (poste / torre)
TITULOS = {'mandato': 'Punto de Mandato', 'desfase': 'Desfase Mandato — Inspección', 'poste': 'Datos del Poste',
           'imagenes': 'Imágenes de Cobertura'}
ETIQUETA_FOTOS = {'poste': 'Registro Fotográfico del Poste', 'imagenes': 'Imágenes de Cobertura'}
COLOR_1, COLOR_2 = '#3b82f6', '#e74c3c'
SLUGS_FOTO = ('camera_widget', 'camera_libro_widget', 'imgs_desc_widget')


def _num(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return v


def _fila_geo(nombre, lat, lon):
    return [nombre, f'{lat:.6f}'.replace('.', ',') if lat is not None else '—', _dms(lat, 'N', 'S'),
            f'{lon:.6f}'.replace('.', ',') if lon is not None else '—', _dms(lon, 'E', 'O')]


def _color_desfase(metros):
    return '#90EE90' if metros <= 150 else ('#FFFF44' if metros <= 200 else '#FF4040')


def _widgets_paso(registro, clave, paso, dato, titulos, user):
    """([bloques de datos], [(etapa, etiqueta)] de fotos) de un paso."""
    ctx = Contexto(registro=registro, paso=paso, clave=clave, user=user, puede_escribir=False)
    datos_paso = (dato.datos if dato else None) or {}
    bloques, etapas = [], []
    for pw, w in servicios.widgets_de(paso):
        slug, config = pw.widget_slug, pw.config or {}
        datos = datos_paso.get(slug) or {}
        if slug in SLUGS_FOTO:
            etapas.append((config.get('etapa') or paso.nombre, config.get('label') or 'Registro Fotográfico'))
        elif slug in ('mapa_1p', 'mapa_2_puntos'):
            imagen = mapas.imagen_de(registro, paso.nombre)
            uri = _data_uri(imagen.imagen)[0] if imagen else None
            if not uri:
                continue
            if slug == 'mapa_2_puntos':
                leyenda = [{'color': config.get('color1') or COLOR_1, 'nombre': titulos.get(str(config.get('paso1')).lower()) or str(config.get('paso1')).capitalize()},
                           {'color': config.get('color2') or COLOR_2, 'nombre': titulos.get(str(config.get('paso2')).lower()) or str(config.get('paso2')).capitalize()}]
            else:
                leyenda = [{'color': config.get('color') or COLOR_1, 'nombre': paso.titulo}]
            dist = imagen.distancia_total_metros if slug == 'mapa_2_puntos' else None
            bloques.append({'tipo': 'mapa', 'src': uri, 'leyenda': leyenda,
                            'distancia': formatear_distancia(dist) if dist is not None else ''})
        elif slug == 'ubicacion_widget' and datos.get('lat') not in (None, ''):
            lat, lon = float(datos['lat']), float(datos['lon'])
            bloques.append({'tipo': 'ubicacion', 'etiqueta': config.get('label') or 'Ubicación GPS',
                            'coords': f'{lat:.6f}, {lon:.6f}'.replace('.', ','),
                            'dms': f"{_dms(lat, 'N', 'S')}, {_dms(lon, 'E', 'O')}",
                            'precision': round(datos['accuracy']) if datos.get('accuracy') else None})
        elif slug == 'poste_form_widget' and datos:
            c = w.contexto(datos, config, ctx)
            filas = [(l, v['valor']) for l, v in (
                ('Tipo de Estructura', c['textos']['tipo_estructura']), ('Altura', c['textos']['altura']),
                ('Tensión', c['textos']['tension']), ('Placa Poste', c['textos']['placa_poste']),
                ('Obstáculos', c['textos']['obstaculos'])) if v['valor']]
            filas += [(t['label'], 'Sí' if t['marcado'] else 'No') for t in c['toggles']]
            filas += [(l, c['textos'][k]['valor']) for l, k in (('Empresa de Energía', 'empresa_energia'),
                                                                  ('Comentario', 'comentario')) if c['textos'][k]['valor']]
            bloques.append({'tipo': 'tabla', 'etiqueta': '', 'filas': filas})
        elif slug == 'form_dinamico_widget' and datos:
            filas = []
            for campo in w.contexto(datos, config, ctx)['campos']:
                valor = ('Sí' if campo.get('marcado') else 'No') if campo.get('tipo') == 'toggle' else campo['valor']
                if valor not in (None, '', 'Sin responder'):
                    filas.append((campo.get('label') or campo['nombre'], _num(valor)))
            if filas:
                bloques.append({'tipo': 'tabla', 'etiqueta': config.get('label') or '', 'filas': filas})
        elif slug == 'comentario_widget' and (datos.get('comentario') or '').strip():
            bloques.append({'tipo': 'texto', 'etiqueta': config.get('label') or 'Comentario', 'texto': datos['comentario'].strip()})
        elif slug == 'lista_widget' and datos.get('entradas'):
            bloques.append({'tipo': 'lista', 'etiqueta': config.get('label') or '', 'items': datos['entradas']})
        elif slug == 'distancia_widget' and datos.get('distancia_metros') is not None:
            bloques.append({'tipo': 'tabla', 'etiqueta': config.get('label') or '',
                            'filas': [(config.get('label') or 'Distancia', formatear_distancia(datos['distancia_metros']))]})
    return bloques, etapas


def _fotos(registro, ct, etapa, columnas):
    salida = []
    for p in Foto.objects.filter(content_type=ct, object_id=registro.pk, etapa=etapa).order_by('orden', 'id'):
        uri, orientacion = _data_uri(p.imagen)
        if uri is None:
            continue
        salida.append({
            'url': uri, 'orientation': orientacion, 'descripcion': (p.descripcion or '').strip(),
            'exif_datetime': p.exif_fecha.strftime('%d/%m/%Y %H:%M') if p.exif_fecha else None,
            'exif_lat': round(p.exif_lat, 6) if p.exif_lat is not None else None,
            'exif_lon': round(p.exif_lon, 6) if p.exif_lon is not None else None,
        })
    return salida


def secciones_con_fotos(registro, clave='txtss'):
    """[{key, label}] de los pasos con fotos (para el selector «1/2 por fila»)."""
    ct = ContentType.objects.get_for_model(RegTxtss)
    con = set(Foto.objects.filter(content_type=ct, object_id=registro.pk).values_list('etapa', flat=True))
    return [{'key': a.paso.nombre, 'label': a.paso.titulo} for a in servicios.asignados_de(registro, clave) if a.paso.nombre in con]


def nombre_archivo(registro):
    def limpio(s):
        return re.sub(r'[\\/:*?"<>|]', '', str(s or '')).strip()
    p = registro.proyecto
    partes = [limpio(p.codigo) if p else '', limpio(p.codigo_operador) if p else '',
              limpio(p.nombre) if p else '', limpio(registro.alternativa)]
    if not registro.concluido:
        partes.append('BORRADOR')
    return '-'.join(x for x in partes if x) + '.pdf'


def contexto(registro, columnas, user=None):
    clave = 'txtss'
    p = registro.proyecto
    ct = ContentType.objects.get_for_model(RegTxtss)
    asignados = servicios.asignados_de(registro, clave)
    datos_pasos = servicios._datos_por_paso(registro)
    titulos = {a.paso.nombre.lower(): a.paso.titulo for a in asignados}

    orden = sorted(asignados, key=lambda a: PRIMEROS.index(a.paso.nombre) if a.paso.nombre in PRIMEROS else len(PRIMEROS))
    secciones = []
    for a in orden:
        paso = a.paso
        bloques, etapas = _widgets_paso(registro, clave, paso, datos_pasos.get(paso.nombre), titulos, user)
        grupos = []
        for etapa, etiqueta in etapas:
            fotos = _fotos(registro, ct, etapa, None)
            if fotos:
                grupos.append({'etiqueta': ETIQUETA_FOTOS.get(paso.nombre, etiqueta) if etiqueta == 'Registro Fotográfico' else etiqueta,
                               'fotos': fotos, 'cols': columnas.get(paso.nombre, 2)})
        if bloques or grupos:
            secciones.append({'nombre': paso.nombre, 'titulo': TITULOS.get(paso.nombre, paso.titulo),
                              'bloques': bloques, 'grupos': grupos})

    # Coordenadas: mandato (paso o proyecto) frente a la inspección (poste / sitio).
    man = mapas.coordenada_de_paso(registro, 'mandato')
    if man[0] is None:
        man = mapas.coordenada_del_proyecto(registro)
    insp = (None, None)
    for nombre in PASOS_INSPECCION:
        insp = mapas.coordenada_de_paso(registro, nombre)
        if insp[0] is not None:
            break
    filas_geo = [_fila_geo('Mandato', *man)]
    if insp[0] is not None:
        filas_geo.append(_fila_geo('Inspección', *insp))
    desfase = None
    if man[0] is not None and insp[0] is not None:
        metros = distancia_m(man[0], man[1], insp[0], insp[1])
        desfase = {'texto': f'{metros:.0f} m', 'color': _color_desfase(metros),
                   'estado': ('Fuera de tolerancia (> 200 m)' if metros > 200 else
                              'Revisar (150–200 m)' if metros > 150 else 'Dentro de tolerancia (≤ 150 m)')}
    # La tabla geográfica va justo después de «mandato»; si no hay ese paso, al principio.
    i_geo = next((i + 1 for i, s in enumerate(secciones) if s['nombre'] == 'mandato'), 0)
    desfase_en_seccion = any(s['nombre'] == 'desfase' for s in secciones)

    es_torre = bool(p and p.tipo and 'torre' in p.tipo.nombre.lower())
    generales = [('Código', p.codigo if p else ''), ('Código Operador', p.codigo_operador if p else ''),
                 ('Nombre', p.nombre if p else ''), ('Tipo', p.tipo.nombre if p and p.tipo else ''),
                 ('Alternativa', registro.alternativa), ('Región', p.region if p else ''), ('Comuna', p.comuna if p else '')]
    empresa = registro.empresa
    return {
        'registro': registro, 'proyecto': p, 'empresa': empresa,
        'logo_empresa': _data_uri(empresa.logo_claro)[0] if getattr(empresa, 'logo_claro', None) else None,
        'codigo': p.codigo if p else '', 'borrador': not registro.concluido,
        'titulo': f'TX / Technical Site Survey',
        'generales': [(k, v) for k, v in generales if v not in (None, '')],
        'responsable': registro.responsable_nombre,
        'antes': secciones[:i_geo], 'despues': secciones[i_geo:],
        'geo_filas': filas_geo, 'desfase': desfase, 'desfase_en_seccion': desfase_en_seccion,
    }


def generar(registro, columnas=None, user=None):
    """Bytes del PDF."""
    from weasyprint import CSS as Css, HTML
    html = render_to_string('reg_txtss/pdf/txtss.html', contexto(registro, columnas or {}, user))
    return HTML(string=html).write_pdf(stylesheets=[Css(filename=str(CSS))])
