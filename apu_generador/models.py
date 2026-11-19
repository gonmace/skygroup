from decimal import Decimal

from django.conf import settings
from django.db import models


class APUBorrador(models.Model):
    """Borrador del generador de APU. Guarda en qué paso va y lo confirmado en cada uno, así que si el proceso se
    corta queda pendiente en el último paso guardado. `apu_guardado` hace idempotente el guardado final."""

    class Modo(models.TextChoices):
        GENERAR = 'generar', 'Generar'
        REUTILIZAR = 'reutilizar', 'Reutilizar'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='apu_borradores')
    proyecto = models.ForeignKey('proyectos.Proyecto', on_delete=models.CASCADE, related_name='apu_borradores')
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    plantilla = models.ForeignKey('apu_catalogo.PlantillaAPU', null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='+', help_text='Tipo de trabajo: decide los prompts de IA de cada paso.')

    # Paso 1
    actividad = models.CharField('Actividad', max_length=200)
    unidad = models.CharField('Unidad', max_length=20)
    descripcion = models.TextField('Descripción', blank=True)
    region = models.CharField('Región o ciudad', max_length=80, blank=True)

    # Lo confirmado en cada paso. `materiales`, `mano_obra` y `equipos` son {"filas": [...], ...}.
    clasificacion = models.JSONField(default=dict, blank=True)
    resumen_alcance = models.TextField('Alcance del ítem', blank=True, help_text='Resumen del alcance que genera el paso 1 y que leen los pasos de insumos.')
    materiales = models.JSONField(default=dict, blank=True)
    mano_obra = models.JSONField(default=dict, blank=True)
    equipos = models.JSONField(default=dict, blank=True)
    consultas = models.JSONField(default=dict, blank=True, help_text='Preguntas de la IA y respuestas, por paso.')
    rondas = models.JSONField(default=dict, blank=True, help_text='Veces que se pidió proponer de nuevo, por paso.')

    paso = models.PositiveSmallIntegerField(default=1)
    eliminado = models.BooleanField(default=False)
    credito_consumido = models.BooleanField(default=False)
    guardado = models.BooleanField(default=False, help_text='El APU ya se guardó; deja de ser un pendiente.')
    apu_guardado = models.ForeignKey('apu_catalogo.ItemModelo', null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='+')

    modo = models.CharField(max_length=10, choices=Modo.choices, default=Modo.GENERAR)
    origen = models.ForeignKey('apu_catalogo.ItemModelo', null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='+')
    instrucciones = models.JSONField(default=list, blank=True, help_text='Historial de prompts de modificación.')

    class Meta:
        ordering = ['-actualizado']
        verbose_name = 'Borrador de APU'
        verbose_name_plural = 'Borradores de APU'

    def __str__(self):
        return f'{self.actividad} · {self.proyecto}'

    @property
    def pendiente(self):
        return not self.eliminado and not self.guardado

    def filas(self, tipo):
        return (getattr(self, tipo) or {}).get('filas', [])


class LimiteEmpresaAPU(models.Model):
    """Tope de APU de toda la empresa (día y mes). Si se agota, nadie genera aunque tenga créditos personales."""
    empresa = models.OneToOneField('empresas.Empresa', on_delete=models.CASCADE, related_name='apu_limite')
    max_dia = models.PositiveIntegerField('Máximo por día', default=20)
    max_mes = models.PositiveIntegerField('Máximo por mes', default=100)
    activo = models.BooleanField('Aplicar límite', default=True)

    class Meta:
        verbose_name = 'Límite de APU de la empresa'
        verbose_name_plural = 'Límites de APU de las empresas'

    def __str__(self):
        return f'{self.empresa}: {self.max_dia}/día · {self.max_mes}/mes'


class LimiteAPU(models.Model):
    """Tope de APU de una persona (día y mes). Sin fila se aplican 3 por día y 10 por mes."""
    membresia = models.OneToOneField('cuentas.Membresia', on_delete=models.CASCADE, related_name='apu_limite')
    max_dia = models.PositiveIntegerField('Máximo por día', default=3)
    max_mes = models.PositiveIntegerField('Máximo por mes', default=10)

    class Meta:
        verbose_name = 'Límite de APU de la persona'
        verbose_name_plural = 'Límites de APU de las personas'

    def __str__(self):
        return f'{self.membresia}: {self.max_dia}/día · {self.max_mes}/mes'


class ConsumoAPU(models.Model):
    """Un crédito gastado. Se cuenta por día y por mes (fecha local); `revertir` lo borra si la IA falla."""

    class Tipo(models.TextChoices):
        GENERAR = 'generar', 'Generar'
        REUTILIZAR = 'reutilizar', 'Reutilizar'
        MODIFICAR = 'modificar', 'Modificar'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='apu_consumos')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    referencia = models.CharField(max_length=60, blank=True, help_text='Ej.: APUBorrador#42')
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']
        indexes = [models.Index(fields=['empresa', 'fecha']), models.Index(fields=['usuario', 'fecha'])]
        verbose_name = 'Consumo de APU'
        verbose_name_plural = 'Consumos de APU'

    def __str__(self):
        return f'{self.get_tipo_display()} · {self.referencia}'


class LlamadaIA(models.Model):
    """Una llamada a un webhook de n8n: su duración y, una vez sincronizado, los tokens por modelo y el costo."""
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='apu_llamadas')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+')
    borrador = models.ForeignKey(APUBorrador, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='llamadas')
    apu = models.ForeignKey('apu_catalogo.ItemModelo', null=True, blank=True, on_delete=models.SET_NULL,
                            related_name='llamadas_ia')
    webhook = models.CharField(max_length=40)
    paso = models.CharField(max_length=20, blank=True)
    prompt_version = models.CharField(max_length=300, blank=True,
                                      help_text='Plantilla, paso, versión y modelo del prompt con que se ejecutó.')
    ejecucion_id = models.CharField(max_length=40, blank=True)
    duracion_ms = models.PositiveIntegerField(default=0)
    ok = models.BooleanField(default=True)
    uso = models.JSONField(null=True, blank=True, help_text='{modelo: {entrada, salida}}. Nulo = aún sin sincronizar.')
    costo_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']
        indexes = [models.Index(fields=['webhook', 'fecha'])]
        verbose_name = 'Llamada a la IA'
        verbose_name_plural = 'Llamadas a la IA'

    def __str__(self):
        return f'{self.webhook} · {self.fecha:%Y-%m-%d %H:%M}'


class TarifaModeloIA(models.Model):
    """Tarifa de un modelo de OpenAI en USD por millón de tokens."""
    modelo = models.CharField(max_length=80, unique=True)
    entrada_usd_mtok = models.DecimalField('Entrada (USD / M tokens)', max_digits=10, decimal_places=4)
    salida_usd_mtok = models.DecimalField('Salida (USD / M tokens)', max_digits=10, decimal_places=4)
    fuente = models.CharField(max_length=200, blank=True)
    verificada_en = models.DateTimeField(null=True, blank=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['modelo']
        verbose_name = 'Tarifa de modelo de IA'
        verbose_name_plural = 'Tarifas de modelos de IA'

    def __str__(self):
        return f'{self.modelo}: {self.entrada_usd_mtok} / {self.salida_usd_mtok}'

    def costo(self, entrada, salida):
        return (Decimal(entrada) * self.entrada_usd_mtok + Decimal(salida) * self.salida_usd_mtok) / Decimal(1_000_000)
