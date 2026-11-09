"""Integridad del avance acumulado: el % anterior/acumulado de una visita depende de las visitas previas del
proyecto, así que tocar una visita antigua alteraría los datos de una posterior ya concluida."""
from .models import RegConstruccion

MENSAJE_POSTERIOR_CONCLUIDA = (
    'Hay una visita posterior de este proyecto ya concluida: reábrela para modificar el avance, '
    'la fecha o eliminar esta visita (el avance acumulado de la posterior cambiaría).'
)


def hay_posterior_concluida(registro, fecha=None):
    """¿El proyecto tiene una visita concluida con fecha posterior a `fecha` (por defecto, la del registro)?"""
    return RegConstruccion.objects.filter(
        empresa_id=registro.empresa_id, proyecto_id=registro.proyecto_id, is_deleted=False, concluido=True,
        fecha__gt=fecha or registro.fecha,
    ).exclude(pk=registro.pk).exists()


def bloqueo_de_paso(registro, paso):
    """Mensaje si guardar este paso alteraría una visita posterior concluida (solo el paso con la tabla de
    avance), o None."""
    if not paso.widgets.filter(widget_slug='tabla_avance_widget').exists():
        return None
    return MENSAJE_POSTERIOR_CONCLUIDA if hay_posterior_concluida(registro) else None
