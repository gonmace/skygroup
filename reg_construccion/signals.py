"""Mantiene dos campos denormalizados de `RegConstruccion`:

- `avance_pct`: avance total ACUMULADO hasta cada visita. Depende de las visitas anteriores del mismo proyecto, así que
  al guardar/borrar el paso de avance, o al crear/mover/borrar una visita, se recalcula la serie completa del proyecto.
- `completo`: todos los elementos obligatorios de los pasos están completos (pinta la fila de verde).

Se escribe con queryset.update() a propósito: no dispara señales (evita bucles)."""
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from reg_actividades.models import DatoPaso
from reg_actividades.servicios import pasos_obligatorios_completos
from reg_actividades.widgets.tabla_avance import recalcular_avance
from reg_fotos.models import Foto

from .models import PASO_AVANCE, RegConstruccion


def _es_de_construccion(instance):
    return instance.content_type_id == ContentType.objects.get_for_model(RegConstruccion).pk


def recalcular_completo(registro_id):
    registro = RegConstruccion.objects.filter(pk=registro_id, is_deleted=False).first()
    if registro is not None:
        RegConstruccion.objects.filter(pk=registro_id).update(
            completo=pasos_obligatorios_completos(registro, 'construccion'))


def _recalcular_avance_de(registro):
    recalcular_avance(RegConstruccion, registro.proyecto_id, registro.empresa_id, PASO_AVANCE)


@receiver([post_save, post_delete], sender=DatoPaso, dispatch_uid='reg_construccion.dato_paso')
def por_dato(sender, instance, **kwargs):
    if not _es_de_construccion(instance):
        return
    registro = RegConstruccion.objects.filter(pk=instance.object_id).first()
    if registro is None:
        return
    if instance.paso_nombre == PASO_AVANCE:
        _recalcular_avance_de(registro)
    recalcular_completo(registro.pk)


@receiver([post_save, post_delete], sender=Foto, dispatch_uid='reg_construccion.foto')
def por_foto(sender, instance, **kwargs):
    if _es_de_construccion(instance):
        recalcular_completo(instance.object_id)


@receiver(post_save, sender=RegConstruccion, dispatch_uid='reg_construccion.visita_guardada')
def por_visita_guardada(sender, instance, created, **kwargs):
    # Una visita nueva (o movida de fecha/proyecto, o restaurada) cambia el acumulado de las demás.
    _recalcular_avance_de(instance)
    if created:
        recalcular_completo(instance.pk)


@receiver(post_delete, sender=RegConstruccion, dispatch_uid='reg_construccion.visita_borrada')
def por_visita_borrada(sender, instance, **kwargs):
    _recalcular_avance_de(instance)
