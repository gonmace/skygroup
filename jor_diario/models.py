from django.conf import settings
from django.db import models
from django.db.models import Q


class JornadaQuerySet(models.QuerySet):
    def computables(self):
        """Las que cuentan en reportes, asistencia y nómina: verificadas o con excepción aprobada."""
        return self.filter(estado_verificacion__in=Jornada.VERIFICACION_COMPUTABLE)


class Jornada(models.Model):
    class Verificacion(models.TextChoices):
        VERIFICADA = 'verificada', 'Verificada'
        EXCEPCION_PENDIENTE = 'excepcion_pendiente', 'Excepción pendiente'
        EXCEPCION_APROBADA = 'excepcion_aprobada', 'Excepción aprobada'
        RECHAZADA = 'rechazada', 'Rechazada'

    VERIFICACION_COMPUTABLE = (Verificacion.VERIFICADA, Verificacion.EXCEPCION_APROBADA)

    class Estado(models.TextChoices):
        EN_CURSO = 'en_curso', 'En curso'
        COMPLETADA = 'completada', 'Completada'
        INCOMPLETA = 'incompleta', 'Incompleta'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='jornadas')
    perfil = models.ForeignKey('jor_empleados.Perfil', on_delete=models.CASCADE, related_name='jornadas')
    proyecto = models.ForeignKey('proyectos.Proyecto', null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='jornadas')
    inicio = models.DateTimeField()
    fin = models.DateTimeField(null=True, blank=True)
    duracion_min = models.PositiveIntegerField(null=True, blank=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.EN_CURSO)
    cierre_auto = models.BooleanField(default=False)
    lat_inicio = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lon_inicio = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lat_fin = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lon_fin = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # Verificación de presencia e identidad (ver jor_diario.verificacion). Las anteriores a este control: «verificada».
    precision_inicio = models.FloatField(null=True, blank=True)
    precision_fin = models.FloatField(null=True, blank=True)
    ip_inicio = models.GenericIPAddressField(null=True, blank=True)
    ip_fin = models.GenericIPAddressField(null=True, blank=True)
    dispositivo = models.ForeignKey('jor_empleados.DispositivoMarcacion', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='jornadas')
    equipo_inicio = models.ForeignKey('jor_empleados.EquipoMarcacion', null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='+')
    equipo_fin = models.ForeignKey('jor_empleados.EquipoMarcacion', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    verificacion = models.JSONField(default=dict, blank=True)
    estado_verificacion = models.CharField(max_length=20, choices=Verificacion.choices,
                                           default=Verificacion.VERIFICADA)
    motivo_excepcion = models.CharField(max_length=300, blank=True)
    revisada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='+')
    revisada_en = models.DateTimeField(null=True, blank=True)
    legacy_source = models.CharField(max_length=20, blank=True, editable=False)
    legacy_id = models.PositiveIntegerField(null=True, blank=True, editable=False, db_index=True)

    objects = JornadaQuerySet.as_manager()

    class Meta:
        ordering = ['-inicio']
        verbose_name = 'Jornada'
        verbose_name_plural = 'Jornadas'
        constraints = [
            # Una sola jornada abierta por persona, aunque lleguen dos «iniciar» a la vez.
            models.UniqueConstraint(fields=['perfil'], condition=Q(estado='en_curso'), name='jor_una_jornada_en_curso'),
        ]
        indexes = [models.Index(fields=['empresa', 'inicio']), models.Index(fields=['perfil', 'inicio'])]

    def __str__(self):
        return f'{self.perfil} — {self.inicio:%Y-%m-%d}'

    @property
    def abierta(self):
        return self.estado == self.Estado.EN_CURSO


class ReporteDiario(models.Model):
    jornada = models.OneToOneField(Jornada, on_delete=models.CASCADE, related_name='reporte')
    realizado = models.TextField('Actividades realizadas', blank=True)
    planificado = models.TextField('Actividades planificadas', blank=True)
    enviado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Reporte diario'
        verbose_name_plural = 'Reportes diarios'


class Ausencia(models.Model):
    class Tipo(models.TextChoices):
        VACACION = 'vacacion', 'Vacación'
        LICENCIA = 'licencia', 'Licencia'
        PERMISO = 'permiso', 'Permiso'
        OTRO = 'otro', 'Otro'

    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        APROBADA = 'aprobada', 'Aprobada'
        RECHAZADA = 'rechazada', 'Rechazada'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='ausencias')
    perfil = models.ForeignKey('jor_empleados.Perfil', on_delete=models.CASCADE, related_name='ausencias')
    desde = models.DateField('Desde')
    hasta = models.DateField('Hasta')
    tipo = models.CharField('Tipo', max_length=10, choices=Tipo.choices)
    nota = models.CharField('Nota', max_length=200, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.APROBADA)
    decidida_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='+')
    decidida_en = models.DateTimeField(null=True, blank=True)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-desde']
        verbose_name = 'Ausencia'
        verbose_name_plural = 'Ausencias'
        indexes = [models.Index(fields=['perfil', 'desde', 'hasta'])]


class NotaCalendario(models.Model):
    class Tipo(models.TextChoices):
        FERIADO = 'feriado', 'Feriado'
        EVENTO = 'evento', 'Evento'
        OTRO = 'otro', 'Otro'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='notas_calendario')
    fecha = models.DateField('Fecha')
    texto = models.CharField('Texto', max_length=200)
    tipo = models.CharField('Tipo', max_length=10, choices=Tipo.choices, default=Tipo.FERIADO)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['fecha']
        verbose_name = 'Nota de calendario'
        verbose_name_plural = 'Notas de calendario'
        indexes = [models.Index(fields=['empresa', 'fecha'])]
