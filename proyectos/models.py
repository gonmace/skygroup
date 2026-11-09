from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower


class ProyectoQuerySet(models.QuerySet):
    def de_empresa(self, empresa):
        return self.filter(empresa=empresa)

    def activos(self):
        return self.filter(is_deleted=False)


class TipoProyecto(models.Model):
    """Tipos definidos por cada empresa (en reg: «Poste», «Torre»)."""

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='tipos_proyecto')
    nombre = models.CharField('Nombre', max_length=60)
    descripcion = models.CharField('Descripción', max_length=200, blank=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['empresa', 'orden', 'nombre']
        verbose_name = 'Tipo de proyecto'
        verbose_name_plural = 'Tipos de proyecto'
        constraints = [
            models.UniqueConstraint(Lower('nombre'), 'empresa', name='proyectos_tipo_nombre_unico'),
        ]

    def __str__(self):
        return self.nombre

    @property
    def color_idx(self):
        """0-5: tono estable de la insignia (clase `.badge-tipo-N` en styles.css), derivado de la pk."""
        return self.pk % 6


class Proyecto(models.Model):
    """Proyecto único por empresa, usado directamente por Registros, Tareas y Jornadas.
    (En reg se llama «Sitio»: es solo el término configurable de la empresa.)"""

    class Estado(models.TextChoices):
        INGENIERIA = 'INGENIERIA', 'Ingeniería'
        CONSTRUCCION = 'CONSTRUCCION', 'Construcción'
        PARALIZADO = 'PARALIZADO', 'Paralizado'
        CONCLUIDO = 'CONCLUIDO', 'Concluido'
        CANCELADO = 'CANCELADO', 'Cancelado'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='proyectos')
    nombre = models.CharField('Nombre', max_length=160)
    codigo = models.CharField('Código', max_length=40, blank=True)
    codigo_operador = models.CharField('Código del operador', max_length=60, blank=True)
    tipo = models.ForeignKey(TipoProyecto, null=True, blank=True, on_delete=models.PROTECT, related_name='proyectos')
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.CONSTRUCCION)
    region = models.CharField('Región', max_length=80, blank=True)
    comuna = models.CharField('Comuna', max_length=80, blank=True)
    ciudad = models.CharField('Ciudad', max_length=80, blank=True)
    descripcion = models.TextField('Descripción', blank=True)
    equipo = models.ManyToManyField('cuentas.Membresia', blank=True, related_name='proyectos')
    is_deleted = models.BooleanField(default=False, db_index=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)
    # Trazabilidad para los futuros importadores.
    legacy_source = models.CharField(max_length=20, blank=True, editable=False)
    legacy_id = models.PositiveIntegerField(null=True, blank=True, editable=False, db_index=True)

    objects = ProyectoQuerySet.as_manager()

    class Meta:
        ordering = ['empresa', 'nombre']
        verbose_name = 'Proyecto'
        verbose_name_plural = 'Proyectos'
        constraints = [
            # Único solo entre activos: permite recrear un código tras borrar (soft delete).
            models.UniqueConstraint(
                Lower('codigo'), 'empresa', condition=models.Q(is_deleted=False) & ~models.Q(codigo=''),
                name='proyectos_codigo_unico_activo',
            ),
        ]

    def __str__(self):
        return f'{self.codigo} · {self.nombre}' if self.codigo else self.nombre

    @property
    def coordenada_principal(self):
        """(lat, lon) de la primera ubicación del proyecto, o (None, None)."""
        u = self.ubicaciones.first()
        return (u.lat, u.lon) if u else (None, None)

    def clean(self):
        if self.tipo_id and self.empresa_id and self.tipo.empresa_id != self.empresa_id:
            raise ValidationError({'tipo': 'El tipo pertenece a otra empresa.'})


class ProyectoUbicacion(models.Model):
    """Ubicaciones adicionales de un proyecto (mandato, ingeniería, construcción…)."""

    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='ubicaciones')
    etiqueta = models.CharField(max_length=60)
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lon = models.DecimalField(max_digits=9, decimal_places=6)

    class Meta:
        verbose_name = 'Ubicación de proyecto'
        verbose_name_plural = 'Ubicaciones de proyecto'
        constraints = [
            models.UniqueConstraint(fields=['proyecto', 'etiqueta'], name='proyectos_ubicacion_unica'),
        ]

    def __str__(self):
        return f'{self.proyecto.codigo or self.proyecto.nombre} · {self.etiqueta}'
