"""PDF «Reporte de Visita de Supervisión» (Supervisión Campo), con el formato de reg.tekon-rl.cl.

Reutiliza la hoja de estilos y los ayudantes de imagen del reporte de Construcción; añade `reporte_cb.css` para
hallazgos y firmas. Las imágenes viajan incrustadas (data URI): nada se pide por red."""
import re
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string

from reg_actividades.models import DatoPaso
from reg_construccion.pdf.reporte import CSS, _buscar, _data_uri, _decimal, _dms, _logo_data_uri
from reg_fotos.models import Foto

from ..models import Hallazgo, RegConstruccionBase, SeguimientoHallazgo

CSS_CB = Path(__file__).with_name('reporte_cb.css')
SECCIONES_FOTOS = (('actividades', 'Actividades'), ('hallazgos', 'Hallazgos'), ('seguimiento', 'Verificación'),
                   ('libro', 'Libro de obras'))
SEVERIDADES = (('critica', 'Crítica'), ('mayor', 'Mayor'), ('menor', 'Menor'))


def _dato(registro, ct, paso):
    return DatoPaso.objects.filter(content_type=ct, object_id=registro.pk, paso_nombre=paso).first()


def _lista(registro, ct, paso):
    return [str(i) for i in (_buscar(_dato(registro, ct, paso), 'entradas') or []) if str(i).strip()]


def _fotos(registro, ct, etapas, desde, leyendas=None):
    """Fotos de una o varias etapas, numeradas «Imagen n» desde `desde`. `leyendas`: {etapa: prefijo}."""
    salida = []
    leyendas = leyendas or {}
    qs = Foto.objects.filter(content_type=ct, object_id=registro.pk, etapa__in=etapas).order_by('etapa', 'orden', 'id')
    for n, p in enumerate(qs, start=desde):
        uri, orientacion = _data_uri(p.imagen)
        if uri is None:
            continue
        texto = (p.descripcion or '').strip()
        prefijo = leyendas.get(p.etapa, '')
        texto = f'{prefijo}: {texto}'.strip(': ') if prefijo else texto
        salida.append({
            'url': uri, 'orientation': orientacion,
            'descripcion': f'Imagen {n}: {texto}' if texto else f'Imagen {n}',
            'exif_datetime': p.exif_fecha.strftime('%d/%m/%Y %H:%M') if p.exif_fecha else None,
            'exif_lat': round(p.exif_lat, 6) if p.exif_lat is not None else None,
            'exif_lon': round(p.exif_lon, 6) if p.exif_lon is not None else None,
        })
    return salida


def secciones_con_fotos(registro):
    ct = ContentType.objects.get_for_model(RegConstruccionBase)
    return [{'key': k, 'label': l} for k, l in SECCIONES_FOTOS
            if Foto.objects.filter(content_type=ct, object_id=registro.pk).exists()]


def nombre_archivo(registro):
    def limpio(s):
        return re.sub(r'[\\/:*?"<>|]', '', str(s or '')).strip()
    p = registro.proyecto
    partes = [limpio(p.codigo) if p else '', f'visita{registro.numero}', f'rev{registro.rev_numero}',
              registro.fecha.strftime('%Y%m%d')]
    if not registro.concluido:
        partes.append('borrador')
    return '-'.join(x for x in partes if x) + '.pdf'


def _resumen_abiertos(registro):
    """Observaciones sin cerrar del proyecto hasta esta visita, por severidad, y cuántas están vencidas."""
    abiertos = list(Hallazgo.objects.filter(
        empresa_id=registro.empresa_id, proyecto_id=registro.proyecto_id, is_deleted=False, visita__is_deleted=False,
        visita__rev_vigente=True, visita__numero__lte=registro.numero).exclude(estado='cerrado'))
    return {'total': len(abiertos), 'vencidos': sum(1 for h in abiertos if h.vencido),
            'por_severidad': [(n, sum(1 for h in abiertos if h.severidad == k)) for k, n in SEVERIDADES]}


def contexto(registro, columnas):
    """`columnas`: {'actividades'|'hallazgos'|'seguimiento'|'libro': 1 | 2}."""
    p = registro.proyecto
    ct = ContentType.objects.get_for_model(RegConstruccionBase)
    inicio = (RegConstruccionBase.objects.filter(proyecto=p, empresa=registro.empresa, is_deleted=False)
              .order_by('fecha').values_list('fecha', flat=True).first())
    ubic = (_dato(registro, ct, 'cb_datos').datos if _dato(registro, ct, 'cb_datos') else {}).get('ubicacion_widget') or {}
    lat, lon = ubic.get('lat'), ubic.get('lon')
    if lat in (None, '') or lon in (None, ''):
        lat, lon = registro.proyecto.coordenada_principal if p else (None, None)
    lat = float(lat) if lat not in (None, '') else None
    lon = float(lon) if lon not in (None, '') else None

    d_datos, d_rec = _dato(registro, ct, 'cb_datos'), _dato(registro, ct, 'cb_recursos')
    hallazgos = list(registro.hallazgos.filter(is_deleted=False).order_by('numero'))
    seguimientos = list(SeguimientoHallazgo.objects.filter(visita=registro).select_related('hallazgo__visita')
                        .order_by('hallazgo__numero'))
    sin_hallazgos = bool(_buscar(_dato(registro, ct, 'cb_hallazgos'), 'sin_hallazgos'))

    f_act = _fotos(registro, ct, ['cb_actividades'], 1)
    et_hal = ['cb_hallazgos'] + [h.etapa_fotos for h in hallazgos]
    f_hal = _fotos(registro, ct, et_hal, len(f_act) + 1, {h.etapa_fotos: h.codigo for h in hallazgos})
    et_seg = ['cb_seguimiento'] + [s.etapa_fotos for s in seguimientos]
    f_seg = _fotos(registro, ct, et_seg, len(f_act) + len(f_hal) + 1, {s.etapa_fotos: s.hallazgo.codigo for s in seguimientos})
    f_lib = _fotos(registro, ct, ['cb_libro'], len(f_act) + len(f_hal) + len(f_seg) + 1)
    cols = lambda k: columnas.get(k, 2)   # noqa: E731
    empresa = registro.empresa
    return {
        'registro': registro, 'empresa': empresa, 'proyecto': p, 'codigo': p.codigo if p else '',
        'logo_empresa': _logo_data_uri(empresa.logo_claro) if getattr(empresa, 'logo_claro', None) else None,
        'borrador': not registro.concluido, 'supervisor': registro.responsable_nombre,
        'fecha_inicio': inicio, 'dias_transcurridos': (registro.fecha - inicio).days if inicio else None,
        'motivo': _buscar(d_datos, 'motivo') or '', 'comentario': str(_buscar(d_datos, 'comentario') or '').strip(),
        'coord_lat': _dms(lat, 'N', 'S'), 'coord_lon': _dms(lon, 'E', 'O'),
        'coord_lat_deg': _decimal(lat), 'coord_lon_deg': _decimal(lon),
        'actividades': _lista(registro, ct, 'cb_actividades'),
        'trabajadores': _buscar(d_rec, 'trabajadores'), 'equipo_pesado': _buscar(d_rec, 'equipo_pesado') or '',
        'hallazgos': hallazgos, 'sin_hallazgos': sin_hallazgos, 'seguimientos': seguimientos,
        'resumen': _resumen_abiertos(registro),
        'instrucciones': _lista(registro, ct, 'cb_instrucciones'),
        'fotos_actividades': f_act, 'fotos_actividades_cols': cols('actividades'),
        'fotos_hallazgos': f_hal, 'fotos_hallazgos_cols': cols('hallazgos'),
        'fotos_seguimiento': f_seg, 'fotos_seguimiento_cols': cols('seguimiento'),
        'fotos_libro': f_lib, 'fotos_libro_cols': cols('libro'),
    }


def generar(registro, columnas=None):
    """Bytes del PDF."""
    from weasyprint import CSS as Css, HTML
    html = render_to_string('reg_construccion_base/pdf/reporte.html', contexto(registro, columnas or {}))
    return HTML(string=html).write_pdf(stylesheets=[Css(filename=str(CSS)), Css(filename=str(CSS_CB))])
