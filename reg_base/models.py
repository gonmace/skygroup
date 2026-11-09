"""Base común del módulo Registros: modelo abstracto del registro."""
import uuid
from datetime import date

from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TipoHabilitado(models.Model):
    """Un tipo de registro (clave definida en código, ver `reg_base.tipos`) activo en una empresa."""

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='tipos_registro_activos')
    clave = models.SlugField('Tipo de registro', max_length=50)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Tipo de registro activo'
        verbose_name_plural = 'Tipos de registro activos'
        constraints = [models.UniqueConstraint(fields=['empresa', 'clave'], name='reg_tipo_habilitado_unico')]

    def __str__(self):
        return f'{self.empresa} · {self.clave}'


class RevisionesMixin(models.Model):
    """Revisiones de un registro (opcional: lo añade a su modelo el tipo que las admita; ver `reg_base.revisiones`).

    Todas las revisiones de un mismo registro comparten `serie`. Cada una conserva SUS datos y fotos (se crean
    copiando la anterior) y un comentario de por qué se hizo; una sola es la VIGENTE: la que se muestra en las
    listas y la que cuenta para el proyecto."""

    serie = models.UUIDField('Serie de revisiones', default=uuid.uuid4, db_index=True, editable=False)
    rev_numero = models.PositiveSmallIntegerField('Revisión', default=0)
    rev_comentario = models.TextField('Comentario de la revisión', blank=True)
    rev_vigente = models.BooleanField('Revisión vigente', default=True, db_index=True)
    rev_origen = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                   verbose_name='Copiada de')

    class Meta:
        abstract = True

    @property
    def rev_etiqueta(self):
        return f'Rev. {self.rev_numero}'

    def revisiones(self):
        """Todas las revisiones del registro (no borradas), de la más antigua a la más nueva."""
        return type(self).objects.filter(empresa_id=self.empresa_id, serie=self.serie,
                                         is_deleted=False).order_by('rev_numero')

    def preparar_revision(self, origen):
        """Gancho: deja en `self` (copia aún sin guardar de `origen`) el estado propio del tipo para una revisión
        nueva (por ejemplo, volver a abierto). Por defecto la deja abierta."""
        if hasattr(self, 'concluido'):
            self.concluido = False

    def copiar_revision_extras(self, origen):
        """Gancho: copia lo que cuelga del registro y es propio del tipo (p. ej. sus hallazgos). `self` ya está guardado."""


class RegistroBase(models.Model):
    """Una visita/inspección de un proyecto, a cargo de un responsable. Base de TX/TSS y Construcción.

    Todo cuelga de la EMPRESA (`empresa`, denormalizada: sobrevive aunque el proyecto se borre y permite
    acotar cada consulta). Los borrados son lógicos."""

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='+')
    # SET_NULL: borrar un proyecto o usuario no debe eliminar en cascada datos de campo irrecuperables.
    proyecto = models.ForeignKey(
        'proyectos.Proyecto', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='%(app_label)s_%(class)s', verbose_name='Proyecto',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='%(app_label)s_%(class)s', verbose_name='Responsable',
    )
    fecha = models.DateField('Fecha de registro', default=date.today)
    is_active = models.BooleanField('Activo', default=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    legacy_source = models.CharField(max_length=20, blank=True, editable=False)
    legacy_id = models.PositiveIntegerField(null=True, blank=True, editable=False, db_index=True)
    # Borrar físicamente un registro elimina sus fotos (y sus archivos, por la señal de Foto).
    fotos = GenericRelation('reg_fotos.Foto', related_query_name='registro_%(class)s')
    datos_pasos = GenericRelation('reg_actividades.DatoPaso', related_query_name='registro_%(class)s')

    class Meta:
        abstract = True
        ordering = ['-created_at']

    def clean(self):
        super().clean()
        if self.proyecto_id and self.empresa_id and self.proyecto.empresa_id != self.empresa_id:
            raise ValidationError({'proyecto': 'El proyecto pertenece a otra empresa.'})
        if self.user_id and self.empresa_id and not self.user.is_superuser and not self.user.membresias.filter(
                empresa_id=self.empresa_id, activa=True).exists():
            raise ValidationError({'user': 'El responsable no pertenece a esta empresa.'})

    def soft_delete(self):
        self.is_deleted = True
        self.is_active = False
        self.updated_at = timezone.now()
        self.save(update_fields=['is_deleted', 'is_active', 'updated_at'])

    def restore(self):
        """Deshace `soft_delete`. Lanza ValidationError si ya existe otro registro activo con la misma clave."""
        self.is_deleted = False
        self.is_active = True
        self.updated_at = timezone.now()
        self.save(update_fields=['is_deleted', 'is_active', 'updated_at'])

    @property
    def responsable_nombre(self):
        if not self.user:
            return '—'
        return self.user.get_full_name().strip() or self.user.email
