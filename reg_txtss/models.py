from django.db import models
from django.db.models import Q

from reg_base.estado import EstadoQuerySet
from reg_base.models import RegistroBase

ALTERNATIVAS = [(c, c) for c in 'ABCDE']


class RegTxtssQuerySet(EstadoQuerySet, models.QuerySet):
    pass


class RegTxtss(RegistroBase):
    """Inspección TX/TSS de un proyecto (poste o torre). Un mismo proyecto/día/responsable puede tener
    varias alternativas (A–E)."""

    alternativa = models.CharField('Alternativa', max_length=1, choices=ALTERNATIVAS, default='A', blank=True)
    concluido = models.BooleanField('Concluido', default=False, db_index=True)

    objects = RegTxtssQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Registro TX/TSS'
        verbose_name_plural = 'Registros TX/TSS'
        constraints = [
            # Único solo entre activos: tras un borrado lógico se puede volver a crear.
            models.UniqueConstraint(
                fields=['proyecto', 'user', 'fecha', 'alternativa'], condition=Q(is_deleted=False),
                name='unique_proyecto_user_fecha_alternativa_regtxtss',
                violation_error_message='Ya existe un registro de este proyecto, responsable, fecha y alternativa.',
            ),
        ]
        indexes = [models.Index(fields=['empresa', 'fecha'], name='regtxtss_emp_fecha_idx')]

    def __str__(self):
        return f'TX/TSS {self.proyecto or "—"} · {self.fecha:%d/%m/%Y}'

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def siguiente_alternativa(self):
        letras = [c for c, _ in ALTERNATIVAS]
        actual = self.alternativa or 'A'
        if actual not in letras or letras.index(actual) >= len(letras) - 1:
            return None
        return letras[letras.index(actual) + 1]
