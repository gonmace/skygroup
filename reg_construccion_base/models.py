"""Supervisión Campo (clave `construccion-base`): reporte de visita de supervisión de obra, con hallazgos que se siguen de visita en visita.

El reporte de visita solo deja evidencia de lo observado ese día. El análisis (avance programado vs real,
desviaciones, indicadores) corresponde al informe semanal, que se arma con estos datos estructurados.
"""
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Max, Q
from django.utils import timezone

from reg_base.estado import EstadoQuerySet
from reg_base.models import RegistroBase, RevisionesMixin

CLAVE = 'construccion-base'
# Pasos opcionales: sus datos y fotos NO cuentan para el color de la visita (y un paso opcional vacío no la deja incompleta).
ETAPAS_OPCIONALES = ('cb_instrucciones', 'cb_libro')


class RegConstruccionBaseQuerySet(EstadoQuerySet, models.QuerySet):
    def vigentes(self):
        """Solo la revisión vigente de cada visita."""
        return self.filter(rev_vigente=True)


class RegConstruccionBase(RegistroBase, RevisionesMixin):
    """Una visita de supervisión a un proyecto. `concluido` significa EMITIDO: queda de solo lectura."""

    contratista = models.ForeignKey(
        'empresas.Contratista', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='reg_construccion_base', verbose_name='Contratista',
    )
    # Correlativo de la visita dentro del proyecto; todas las revisiones de una visita comparten número.
    numero = models.PositiveIntegerField('N° de visita', default=0, editable=False)
    concluido = models.BooleanField('Emitido', default=False, db_index=True)
    emitido_en = models.DateTimeField('Emitido el', null=True, blank=True, editable=False)
    emitido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+', verbose_name='Emitido por', editable=False)

    ETAPAS_OPCIONALES = ETAPAS_OPCIONALES
    objects = RegConstruccionBaseQuerySet.as_manager()

    class Meta:
        verbose_name = 'Visita de construcción'
        verbose_name_plural = 'Visitas de construcción'
        ordering = ['-fecha', '-id']
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'proyecto', 'numero', 'rev_numero'],
                                    condition=Q(is_deleted=False), name='cb_visita_numero_rev_unico'),
            models.UniqueConstraint(fields=['serie', 'rev_numero'], name='cb_serie_rev_unica'),
            models.UniqueConstraint(fields=['serie'], condition=Q(rev_vigente=True, is_deleted=False),
                                    name='cb_una_vigente_por_serie'),
        ]
        indexes = [models.Index(fields=['empresa', 'proyecto', 'fecha'], name='cb_visita_proy_fecha_idx')]

    def __str__(self):
        return f'Construcción {self.proyecto or "—"} · visita {self.numero} · {self.fecha:%d/%m/%Y}'

    def clean(self):
        super().clean()
        if self.contratista_id and self.empresa_id and self.contratista.empresa_id != self.empresa_id:
            raise ValidationError({'contratista': 'El contratista pertenece a otra empresa.'})

    def save(self, *args, **kwargs):
        if self._state.adding and not self.numero:
            ultimo = type(self).objects.filter(empresa_id=self.empresa_id, proyecto_id=self.proyecto_id,
                                               is_deleted=False).aggregate(m=Max('numero'))['m']
            self.numero = (ultimo or 0) + 1
        self.full_clean()
        super().save(*args, **kwargs)

    # ── Revisiones ──────────────────────────────────────────────────────────
    def preparar_revision(self, origen):
        """La revisión nueva parte abierta, sin datos de emisión."""
        self.concluido = False
        self.emitido_en = self.emitido_por = None

    def copiar_revision_extras(self, origen):
        """Copia los hallazgos de la visita y sus seguimientos; las fotos ya se copiaron (con la etapa vieja)."""
        mapeo = {}
        for h in origen.hallazgos.filter(is_deleted=False):
            copia = Hallazgo.objects.get(pk=h.pk)
            copia.pk = copia.id = None
            copia._state.adding = True
            copia.visita = self
            copia.origen_id = h.pk
            copia.save()
            mapeo[h.pk] = copia.pk
        # Las fotos de un hallazgo cuelgan de la etapa «hallazgo-<id>»: se reapuntan a la copia.
        for viejo, nuevo in mapeo.items():
            self.fotos.filter(etapa=f'hallazgo-{viejo}').update(etapa=f'hallazgo-{nuevo}')
        for s in origen.seguimientos.all():
            SeguimientoHallazgo.objects.create(hallazgo=s.hallazgo, visita=self, estado=s.estado,
                                               estado_previo=s.estado_previo, comentario=s.comentario)

    @property
    def es_vigente(self):
        return self.rev_vigente

    # ── Ganchos del PDF genérico (reg_base.pdf) ──────────────────────────────
    def referencia_pdf(self):
        return f'visita {self.numero} · {self.rev_etiqueta}'

    def cabecera_pdf(self):
        p = self.proyecto
        filas = [('Fecha', self.fecha.strftime('%d/%m/%Y')), ('Visita N°', self.numero), ('Revisión', self.rev_etiqueta),
                 ('Contratista', self.contratista.nombre if self.contratista_id else ''),
                 ('Supervisor', self.responsable_nombre),
                 ('Estado', 'Emitido' if self.concluido else 'Borrador')]
        if self.rev_numero and self.rev_comentario:
            filas.append(('Motivo de la revisión', self.rev_comentario))
        if self.concluido and self.emitido_en:
            filas.append(('Emitido', f'{timezone.localtime(self.emitido_en):%d/%m/%Y %H:%M}'))
        return filas

    def titulos_etapas_pdf(self):
        """Título de las etapas de fotos que no son un paso (fotos de hallazgos y de verificaciones)."""
        titulos = {h.etapa_fotos: f'{h.codigo} · Hallazgo' for h in self.hallazgos.filter(is_deleted=False)}
        titulos.update({s.etapa_fotos: f'{s.hallazgo.codigo} · Verificación'
                        for s in self.seguimientos.select_related('hallazgo')})
        return titulos


class Hallazgo(models.Model):
    """Observación levantada en una visita. Existe una sola vez y se sigue de visita en visita hasta cerrarse."""

    class Tipo(models.TextChoices):
        CALIDAD = 'calidad', 'Calidad'
        SEGURIDAD = 'seguridad', 'Seguridad'
        AMBIENTAL = 'ambiental', 'Ambiental'
        DISENO = 'diseno', 'Diseño'
        AVANCE = 'avance', 'Avance'
        OTRO = 'otro', 'Otro'

    class Severidad(models.TextChoices):
        CRITICA = 'critica', 'Crítica'
        MAYOR = 'mayor', 'Mayor'
        MENOR = 'menor', 'Menor'

    class Estado(models.TextChoices):
        ABIERTO = 'abierto', 'Abierto'
        EN_PROCESO = 'en_proceso', 'En proceso'
        CERRADO = 'cerrado', 'Cerrado'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='+')
    proyecto = models.ForeignKey('proyectos.Proyecto', null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='hallazgos_construccion')
    visita = models.ForeignKey(RegConstruccionBase, on_delete=models.CASCADE, related_name='hallazgos',
                               verbose_name='Visita donde se levantó')
    numero = models.PositiveIntegerField('N°', default=0, editable=False)   # correlativo por proyecto (H-001…)
    descripcion = models.TextField('Descripción')
    tipo = models.CharField('Tipo', max_length=12, choices=Tipo.choices, default=Tipo.CALIDAD)
    severidad = models.CharField('Severidad', max_length=8, choices=Severidad.choices, default=Severidad.MENOR)
    responsable = models.CharField('Responsable de corregirlo', max_length=120, blank=True)
    plazo = models.DateField('Plazo de corrección', null=True, blank=True)
    estado = models.CharField('Estado', max_length=10, choices=Estado.choices, default=Estado.ABIERTO, db_index=True)
    cerrado_en = models.ForeignKey(RegConstruccionBase, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name='Cerrado en la visita', editable=False)
    cerrado_fecha = models.DateField('Cerrado el', null=True, blank=True, editable=False)
    # En una revisión de la visita el hallazgo se copia: aquí queda de cuál.
    origen = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='+', editable=False)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    class Meta:
        verbose_name = 'Hallazgo'
        verbose_name_plural = 'Hallazgos'
        ordering = ['numero', 'id']
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'proyecto', 'numero', 'visita'], condition=Q(is_deleted=False),
                                    name='cb_hallazgo_numero_unico'),
        ]

    def __str__(self):
        return f'{self.codigo} · {self.descripcion[:40]}'

    @property
    def codigo(self):
        return f'H-{self.numero:03d}'

    @property
    def vencido(self):
        return bool(self.plazo and self.estado != self.Estado.CERRADO and self.plazo < date.today())

    @property
    def etapa_fotos(self):
        return f'hallazgo-{self.pk}'

    def clean(self):
        super().clean()
        if self.visita_id and self.empresa_id and self.visita.empresa_id != self.empresa_id:
            raise ValidationError({'visita': 'La visita pertenece a otra empresa.'})

    def save(self, *args, **kwargs):
        if self._state.adding and not self.numero:
            ultimo = Hallazgo.objects.filter(empresa_id=self.empresa_id, proyecto_id=self.proyecto_id,
                                             is_deleted=False).aggregate(m=Max('numero'))['m']
            self.numero = (ultimo or 0) + 1
        super().save(*args, **kwargs)


class SeguimientoHallazgo(models.Model):
    """Qué se constató de un hallazgo anterior en una visita. Es el ÚNICO camino para cambiar su estado."""

    class Resultado(models.TextChoices):
        CERRADO = 'cerrado', 'Cerrado'
        EN_PROCESO = 'en_proceso', 'En proceso'
        SIN_CAMBIOS = 'sin_cambios', 'Sin cambios'

    hallazgo = models.ForeignKey(Hallazgo, on_delete=models.CASCADE, related_name='seguimientos')
    visita = models.ForeignKey(RegConstruccionBase, on_delete=models.CASCADE, related_name='seguimientos')
    estado = models.CharField('Resultado', max_length=12, choices=Resultado.choices)
    # Estado que tenía el hallazgo antes de este seguimiento (para deshacerlo si la visita se corrige).
    estado_previo = models.CharField(max_length=10, choices=Hallazgo.Estado.choices, default=Hallazgo.Estado.ABIERTO,
                                     editable=False)
    comentario = models.TextField('Comentario', blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Seguimiento de hallazgo'
        verbose_name_plural = 'Seguimientos de hallazgos'
        ordering = ['creado', 'id']
        constraints = [models.UniqueConstraint(fields=['hallazgo', 'visita'], name='cb_seguimiento_unico')]

    def __str__(self):
        return f'{self.hallazgo.codigo} · {self.get_estado_display()}'

    @property
    def etapa_fotos(self):
        return f'seguimiento-{self.hallazgo_id}'
