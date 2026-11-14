"""PDF «TX / Technical Site Survey» de un registro TX/TSS (poste o torre), con el formato del original reg.tekon-rl.cl.

Reutiliza la hoja de estilos y los ayudantes de imagen del reporte de Construcción. Las secciones salen de los pasos
de la plantilla del registro: «mandato» y «desfase» van primero (con la tabla de datos geográficos entre ambas); el
resto, en el orden de la plantilla. Las imágenes viajan incrustadas (data URI): nada se pide por red."""
import re
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string

from reg_actividades import mapas, servicios
from reg_actividades.widgets.base import Contexto
from reg_base.geo import distancia_m, formatear_distancia
from reg_construccion.pdf.reporte import CSS, _data_uri, _decimal, _dms, _logo_data_uri, logo_proveedor
from reg_fotos.models import Foto

from ..models import RegTxtss

CSS_TXTSS = Path(__file__).with_name('txtss.css')
PRIMEROS = ('mandato', 'desfase')
SECCIONES_PROPIAS = ('mandato', 'desfase', 'poste', 'imagenes')   # las que el original traía fijas en el informe
PASOS_INSPECCION = ('poste', 'sitio')   # paso cuya ubicación es la «inspección» (poste / torre)
TITULOS = {'mandato': 'Punto de Referencia', 'desfase': 'Desfase Referencia — Inspección (Poste)', 'poste': 'Datos del Poste',
           'imagenes': 'Imágenes de Cobertura'}
# Imágenes por fila por defecto en cada paso (2 si no figura): las del dron se ven mejor de a una.
COLUMNAS_DEFECTO = {'imagenes': 1}

ETIQUETA_FOTOS = {'poste': 'Registro Fotográfico del Poste', 'imagenes': 'Imágenes de Cobertura'}
# Leyenda del mapa de 2 puntos de cada paso, tal como la traía el reporte de reg.tekon-rl.cl.
LEYENDA_MAPA2 = {'desfase': ('Referencia', 'Poste (Inspección)')}
COLOR_1, COLOR_2 = '#3b82f6', '#e74c3c'
SLUGS_FOTO = ('camera_widget', 'camera_libro_widget', 'imgs_desc_widget')


def _num(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return v


def _dms_orig(valor, pos, neg):
    """DMS como lo imprimía reg.tekon-rl.cl: «S 36° 51' 56.32''» (hemisferio primero, segundos con hasta 2 decimales)."""
    if valor is None:
        return 'N/A'
    v = float(valor)
    absoluto = abs(v)
    grados = int(absoluto)
    minutos_completos = (absoluto - grados) * 60
    minutos = int(minutos_completos)
    segundos = round((minutos_completos - minutos) * 60, 2)
    return f"{pos if v >= 0 else neg} {grados}° {minutos}' {segundos}''"


def _fila_geo(nombre, lat, lon):
    return [nombre, f'{lat:.6f}' if lat is not None else '', _dms_orig(lat, 'N', 'S'),
            f'{lon:.6f}' if lon is not None else '', _dms_orig(lon, 'E', 'W')]


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
            nota = ''
            if slug == 'mapa_2_puntos':
                n1, n2 = LEYENDA_MAPA2.get(paso.nombre) or (
                    titulos.get(str(config.get('paso1')).lower()) or str(config.get('paso1')).capitalize(),
                    titulos.get(str(config.get('paso2')).lower()) or str(config.get('paso2')).capitalize())
                leyenda = [{'color': config.get('color1') or COLOR_1, 'nombre': n1},
                           {'color': config.get('color2') or COLOR_2, 'nombre': n2}]
            else:
                leyenda = [{'color': config.get('color') or COLOR_1, 'nombre': paso.titulo}]
                if imagen.coordenadas:   # como el original: bajo la leyenda, las coordenadas del punto
                    p0 = imagen.coordenadas[0]
                    nota = 'Lat: {}|Lon: {}'.format(f"{p0['lat']:.6f}".replace('.', ','), f"{p0['lon']:.6f}".replace('.', ','))
            bloques.append({'tipo': 'mapa', 'src': uri, 'leyenda': leyenda, 'nota': nota.split('|')})
        elif slug == 'ubicacion_widget' and datos.get('lat') not in (None, ''):
            lat, lon = float(datos['lat']), float(datos['lon'])
            if paso.nombre == 'poste':   # el original: «Ubicación GPS» con DMS y decimal, y «Referencia → Poste» (se completa luego)
                bloques.append({'tipo': 'poste_ubic', 'lat_dms': _dms_orig(lat, 'N', 'S'), 'lon_dms': _dms_orig(lon, 'E', 'W'),
                                'lat': f'{lat:.6f}'.replace('.', ','), 'lon': f'{lon:.6f}'.replace('.', ','),
                                'precision': round(datos['accuracy']) if datos.get('accuracy') else None, 'desfase': None})
            else:
                bloques.append({'tipo': 'ubicacion', 'etiqueta': config.get('label') or 'Ubicación GPS',
                                'coords': f'{lat:.6f}, {lon:.6f}'.replace('.', ','),
                                'dms': f"{_dms(lat, 'N', 'S')}, {_dms(lon, 'E', 'O')}",
                                'precision': round(datos['accuracy']) if datos.get('accuracy') else None})
        elif slug == 'poste_form_widget' and datos:
            c = w.contexto(datos, config, ctx)
            t = c['textos']
            si_no = lambda k: 'Sí' if datos.get(k) else 'No'
            filas = [(l, t[k]['valor']) for l, k in (('Tipo de Estructura', 'tipo_estructura'), ('Altura', 'altura'),
                                                      ('Tensión', 'tension'), ('Placa del Poste', 'placa_poste'),
                                                      ('Obstáculos', 'obstaculos')) if t[k]['valor']]
            filas += [('Luminaria', si_no('luminaria')), ('Red Protegida', si_no('red_protegida')),
                      ('Acceso Camión Grúa', si_no('acceso_camion_grua')), ('Vegetación', si_no('vegetacion')),
                      ('Antena de Microondas', si_no('antena_microondas'))]
            if t['comentario']['valor']:
                filas.append(('Comentario', t['comentario']['valor']))
            bloques.append({'tipo': 'tabla', 'etiqueta': 'Características', 'filas': filas})
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
    for p in Foto.objects.filter(content_type=ct, object_id=registro.pk, etapa=etapa).order_by('orden', '-creada', '-id'):
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
                               'fotos': fotos, 'cols': columnas.get(paso.nombre, COLUMNAS_DEFECTO.get(paso.nombre, 2))})
        if bloques or grupos:
            secciones.append({'nombre': paso.nombre, 'titulo': TITULOS.get(paso.nombre, paso.titulo),
                              'bloques': bloques, 'grupos': grupos,
                              'propia': paso.nombre in SECCIONES_PROPIAS})   # estilo de título plano, como el original

    # Coordenadas: mandato (paso o proyecto) frente a la inspección (poste / sitio).
    man = mapas.coordenada_de_paso(registro, 'mandato')
    if man[0] is None:
        man = mapas.coordenada_del_proyecto(registro)
    insp = (None, None)
    for nombre in PASOS_INSPECCION:
        insp = mapas.coordenada_de_paso(registro, nombre)
        if insp[0] is not None:
            break
    filas_geo = [_fila_geo('Referencia', *man)]
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
    # Datos del poste: el original los muestra también en «Datos Generales» (altura y empresa de energía).
    poste = {}
    for a_ in asignados:
        if a_.paso.nombre == 'poste':
            poste = (datos_pasos.get('poste').datos if datos_pasos.get('poste') else {}).get('poste_form_widget', {}) or {}
    generales = [('Código PTI ID', p.codigo if p else ''), ('Código Operador ID', p.codigo_operador if p else ''),
                 ('Nombre del sitio', p.nombre if p else ''), ('Tipo de sitio', p.tipo.nombre if p and p.tipo else ''),
                 ('Alternativa', registro.alternativa), ('Región', p.region if p else ''), ('Comuna', p.comuna if p else '')]
    if not es_torre:
        generales += [('Altura', poste.get('altura') or 'N/A'), ('Empresa de Energía', poste.get('empresa_energia') or 'N/A')]
    for sec in secciones:   # «Referencia → Poste» de la ubicación GPS del poste
        for b in sec['bloques']:
            if b['tipo'] == 'poste_ubic':
                b['desfase'] = desfase
    empresa = registro.empresa
    return {
        'registro': registro, 'proyecto': p, 'empresa': empresa,
        'logo_empresa': _logo_data_uri(empresa.logo_claro) if getattr(empresa, 'logo_claro', None) else None,
        'logo_proveedor': logo_proveedor(empresa)[0], 'proveedor': logo_proveedor(empresa)[1],
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
    mapas.generar_automaticas(registro, 'txtss')   # que el informe lleve siempre sus dos mapas, aunque no se hayan generado aún
    html = render_to_string('reg_txtss/pdf/txtss.html', contexto(registro, columnas or {}, user))
    return HTML(string=html).write_pdf(stylesheets=[Css(filename=str(CSS)), Css(filename=str(CSS_TXTSS))])
