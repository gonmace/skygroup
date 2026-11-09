from django.db import models

OTROS = 'otros'


class CategoriaActividad(models.Model):
    """Categoría de actividad de la empresa. Las base se siembran al primer uso (`servicios.categorias`)."""
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='categorias_actividad')
    codigo = models.SlugField('Código', max_length=20)
    etiqueta = models.CharField('Nombre', max_length=80)
    color = models.CharField('Color', max_length=20, default='#64748b')
    orden = models.PositiveSmallIntegerField('Orden', default=0)
    activa = models.BooleanField('Activa', default=True, help_text='Las inactivas no se ofrecen al clasificar.')
    protegida = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ['orden', 'etiqueta']
        verbose_name = 'Categoría de actividad'
        verbose_name_plural = 'Categorías de actividad'
        constraints = [models.UniqueConstraint(fields=['empresa', 'codigo'], name='jor_categoria_unica')]

    def __str__(self):
        return self.etiqueta


class Etiqueta(models.Model):
    """Proyecto, sede o entregable mencionado en un reporte. Como un mismo proyecto se nombra de varias
    formas, se fusionan variantes apuntando `canonica` al elegido (fusión no destructiva)."""

    class Tipo(models.TextChoices):
        PROYECTO = 'proyecto', 'Proyecto'
        UBICACION = 'ubicacion', 'Sede'
        ENTREGABLE = 'entregable', 'Entregable'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='etiquetas_actividad')
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    nombre = models.CharField('Nombre', max_length=120)
    codigo = models.CharField('Código', max_length=40, blank=True)
    color = models.CharField('Color', max_length=20, blank=True)
    clave = models.CharField(max_length=120, editable=False)
    canonica = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='alias')
    ignorada = models.BooleanField(default=False)
    # Proyecto del modelo `proyectos.Proyecto` al que se agregó esta etiqueta (solo tipo «proyecto»).
    proyecto = models.ForeignKey('proyectos.Proyecto', null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='etiquetas')
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tipo', 'nombre']
        verbose_name = 'Etiqueta de actividad'
        verbose_name_plural = 'Etiquetas de actividad'
        constraints = [models.UniqueConstraint(fields=['empresa', 'tipo', 'clave'], name='jor_etiqueta_unica')]

    def __str__(self):
        return f'{self.get_tipo_display()}: {self.nombre}'

    @property
    def raiz(self):
        return self.canonica or self


class ItemActividad(models.Model):
    """Una actividad individual de un reporte diario, con su categoría."""

    class Tipo(models.TextChoices):
        HECHO = 'hecho', 'Realizada'
        PLANIFICADO = 'planificado', 'Planificada'

    class Fuente(models.TextChoices):
        PALABRAS = 'palabras', 'Palabras clave'
        LLM = 'llm', 'LLM'
        MANUAL = 'manual', 'Manual'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='items_actividad')
    reporte = models.ForeignKey('jor_diario.ReporteDiario', on_delete=models.CASCADE, related_name='items')
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    posicion = models.PositiveSmallIntegerField(default=0)
    texto = models.TextField()
    categoria = models.CharField(max_length=20, default=OTROS)      # código de CategoriaActividad (clave de agregación)
    fuente = models.CharField(max_length=10, choices=Fuente.choices, default=Fuente.PALABRAS)
    palabra = models.CharField(max_length=60, blank=True)
    etiquetas = models.ManyToManyField(Etiqueta, blank=True, related_name='items')
    manual = models.BooleanField(default=False, help_text='Asignada a mano: el clasificador no la pisa.')
    clasificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['reporte_id', 'tipo', 'posicion']
        verbose_name = 'Ítem de actividad'
        verbose_name_plural = 'Ítems de actividad'
        constraints = [models.UniqueConstraint(fields=['reporte', 'tipo', 'posicion'], name='jor_item_posicion_unica')]
        indexes = [models.Index(fields=['empresa', 'tipo', 'categoria'])]
