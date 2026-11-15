"""Reglas de los hallazgos y su seguimiento."""
from django.db.models import Q

from .models import Hallazgo, RegConstruccionBase, SeguimientoHallazgo

Estado = Hallazgo.Estado
Resultado = SeguimientoHallazgo.Resultado


def pendientes_de_seguimiento(visita):
    """Hallazgos de visitas ANTERIORES del proyecto que esta visita debe revisar: los que siguen abiertos o en
    proceso, más los que ella misma cerró (para poder corregirlo mientras está abierta). Solo cuentan los
    hallazgos de la revisión vigente de cada visita anterior."""
    if not visita.proyecto_id:
        return Hallazgo.objects.none()
    return (Hallazgo.objects.filter(empresa_id=visita.empresa_id, proyecto_id=visita.proyecto_id, is_deleted=False,
                                    visita__is_deleted=False, visita__rev_vigente=True, visita__numero__lt=visita.numero)
            .filter(Q(estado__in=[Estado.ABIERTO, Estado.EN_PROCESO]) | Q(cerrado_en__serie=visita.serie))
            .select_related('visita').order_by('numero'))


PASOS_ARRASTRADOS = ('cb_actividades', 'cb_recursos')


def importar_de_anterior(visita):
    """Una visita nueva parte con las actividades y los recursos presentes de la visita anterior del proyecto
    (solo el texto de las listas, no las fotos). Los hallazgos pendientes no se copian: ya aparecen en el paso de
    verificación (`pendientes_de_seguimiento`). Devuelve la visita anterior usada, o None."""
    from django.contrib.contenttypes.models import ContentType
    from reg_actividades.models import DatoPaso
    if not visita.proyecto_id:
        return None
    anterior = (RegConstruccionBase.objects.filter(empresa_id=visita.empresa_id, proyecto_id=visita.proyecto_id,
                                                   is_deleted=False, rev_vigente=True, numero__lt=visita.numero)
                .order_by('-numero').first())
    if anterior is None:
        return None
    ct = ContentType.objects.get_for_model(RegConstruccionBase)
    for d in DatoPaso.objects.filter(content_type=ct, object_id=anterior.pk, paso_nombre__in=PASOS_ARRASTRADOS):
        listas = {slug: {**bloque, 'importado': True} for slug, bloque in (d.datos or {}).items()
                  if slug == 'lista_widget' and (bloque or {}).get('entradas')}
        if listas:
            DatoPaso.objects.get_or_create(
                empresa_id=visita.empresa_id, content_type=ct, object_id=visita.pk, paso_nombre=d.paso_nombre,
                defaults={'datos': listas, 'tiene_datos': True})
    return anterior


def _revertir(seguimiento):
    """Deshace el efecto de un seguimiento sobre el estado del hallazgo."""
    h = seguimiento.hallazgo
    h.estado = seguimiento.estado_previo
    if h.cerrado_en_id == seguimiento.visita_id:
        h.cerrado_en = None
        h.cerrado_fecha = None
    h.save(update_fields=['estado', 'cerrado_en', 'cerrado_fecha', 'actualizado'])


def registrar_seguimiento(visita, hallazgo, resultado, comentario=''):
    """Crea o actualiza el seguimiento de `hallazgo` en `visita` y aplica su efecto sobre el estado."""
    previo = SeguimientoHallazgo.objects.filter(hallazgo=hallazgo, visita=visita).first()
    if previo:
        _revertir(previo)
        hallazgo.refresh_from_db()
        previo.estado, previo.comentario = resultado, comentario
        previo.save()
        seguimiento = previo
    else:
        seguimiento = SeguimientoHallazgo.objects.create(
            hallazgo=hallazgo, visita=visita, estado=resultado, comentario=comentario, estado_previo=hallazgo.estado)
    if resultado == Resultado.CERRADO:
        hallazgo.estado, hallazgo.cerrado_en, hallazgo.cerrado_fecha = Estado.CERRADO, visita, visita.fecha
    elif resultado == Resultado.EN_PROCESO:
        hallazgo.estado = Estado.EN_PROCESO
    hallazgo.save(update_fields=['estado', 'cerrado_en', 'cerrado_fecha', 'actualizado'])
    return seguimiento


def quitar_seguimientos_salvo(visita, hallazgos_ids):
    """Elimina (y revierte) los seguimientos de la visita cuyo hallazgo ya no figura en `hallazgos_ids`."""
    for s in SeguimientoHallazgo.objects.filter(visita=visita).exclude(hallazgo_id__in=hallazgos_ids).select_related('hallazgo'):
        _revertir(s)
        s.delete()


def abiertos_del_proyecto(empresa, proyecto_id):
    return Hallazgo.objects.filter(empresa=empresa, proyecto_id=proyecto_id, is_deleted=False, visita__rev_vigente=True,
                                   visita__is_deleted=False).exclude(estado=Estado.CERRADO)


def faltan_para_emitir(visita):
    """Títulos de los pasos con elementos OBLIGATORIOS incompletos (lista vacía = se puede emitir)."""
    from reg_actividades import servicios as pasos
    from reg_base.tipos import tipo
    clave = tipo('construccion-base').clave
    datos = pasos._datos_por_paso(visita)
    asignados = pasos.asignados_de(visita, clave)
    faltan = []
    for a in asignados:
        bloques, _ = pasos.construir_paso(visita, clave, a.paso, datos.get(a.paso.nombre), None, False)
        if any(not b['pw'].config.get('opcional') and b['nivel'] < 3 for b in bloques):
            faltan.append(a.paso.titulo)
    return faltan
