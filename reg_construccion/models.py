from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from reg_base.estado import EstadoQuerySet
from proyectos.models import Proyecto
from reg_base.models import RegistroBase

# El estado de la obra ES el estado del proyecto (una sola fuente): ver RegConstruccion.estado_obra.
ESTADOS_OBRA = Proyecto.Estado.choices
# Paso que contiene la tabla de ítems y avance (ver reg_actividades.widgets.tabla_avance).
PASO_AVANCE = 'obra_avance'
# Etapas (pasos) opcionales: sus datos y fotos NO cuentan para el color de la visita (verde/amarillo/rojo).
ETAPAS_OPCIONALES = ('obra_electrico', 'obra_libro')
DESCRIPCION_DEFAULT = 'Construcción de nuevo sitio de telecomunicación'


class RegConstruccionQuerySet(EstadoQuerySet, models.QuerySet):
    pass


class RegConstruccion(RegistroBase):
    """Una visita del ITO a un proyecto en obra. Un proyecto activado acumula varias visitas, una por fecha."""

    contratista = models.ForeignKey(
        'empresas.Contratista', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='reg_construcciones', verbose_name='Contratista',
    )
    nombre_obra = models.CharField('Proyecto (nombre de la obra)', max_length=120, blank=True)
    descripcion = models.CharField('Descripción del proyecto', max_length=255, blank=True, default=DESCRIPCION_DEFAULT)
    revision = models.PositiveSmallIntegerField('Revisión', default=0)
    concluido = models.BooleanField('Concluido', default=False, db_index=True)
    # Denormalizados (los mantiene el tramo de la tabla de avance): % acumulado hasta esta visita y si los
    # pasos obligatorios están completos (pinta la fila de verde).
    avance_pct = models.DecimalField('Avance total %', max_digits=5, decimal_places=2, default=Decimal('0'))
    completo = models.BooleanField('Pasos obligatorios completos', default=False)

    ETAPAS_OPCIONALES = ETAPAS_OPCIONALES

    @property
    def estado_obra(self):
        return self.proyecto.estado if self.proyecto_id else ''

    def get_estado_obra_display(self):
        return self.proyecto.get_estado_display() if self.proyecto_id else '—'
    objects = RegConstruccionQuerySet.as_manager()

    class Meta:
        verbose_name = 'Registro de construcción'
        verbose_name_plural = 'Registros de construcción'
        ordering = ['-fecha', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['proyecto', 'fecha'], condition=Q(is_deleted=False),
                name='unique_visita_proyecto_fecha_regconstruccion',
                violation_error_message='Ya existe un reporte de este proyecto en esa fecha.',
            ),
        ]
        indexes = [models.Index(fields=['proyecto', 'fecha'], name='regconstr_proy_fecha_idx')]

    def __str__(self):
        return f'Construcción {self.proyecto or "—"} · {self.fecha:%d/%m/%Y}'

    def clean(self):
        super().clean()
        if self.contratista_id and self.empresa_id and self.contratista.empresa_id != self.empresa_id:
            raise ValidationError({'contratista': 'El contratista pertenece a otra empresa.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def numero_visita(self):
        """Posición de esta visita entre las de su proyecto (por fecha)."""
        return (type(self).objects.filter(proyecto_id=self.proyecto_id, is_deleted=False)
                .filter(Q(fecha__lt=self.fecha) | Q(fecha=self.fecha, id__lte=self.id)).count())

    @property
    def coordenadas(self):
        """(lat, lon) del proyecto para la obra: ubicación «Construcción», luego «Ingeniería», luego la propia."""
        p = self.proyecto
        if p is None:
            return None, None
        por_etiqueta = {u.etiqueta.lower(): u for u in p.ubicaciones.all()}
        for clave in ('construcción', 'construccion', 'ingeniería', 'ingenieria'):
            u = por_etiqueta.get(clave)
            if u is not None:
                return float(u.lat), float(u.lon)
        lat, lon = p.coordenada_principal
        if lat is not None:
            return float(lat), float(lon)
        return None, None
