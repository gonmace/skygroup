"""Módulo Tareas: tickets con subtickets por persona (RACI), aprobación y tiempos.

Portado de skydesk (`tickets`). Diferencias de diseño:
- `Empresa`/`Proyecto` vienen de las apps comunes (no hay Company/Project propios).
- El correlativo vive en `ConfigTareas` (por empresa), no en la empresa.
- Los roles se resuelven por capacidades (`cuentas.capacidades`), no por un rol fijo.
"""
import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import IntegrityError, models, transaction
from django.utils import timezone

prefijo_validator = RegexValidator(r'^[A-Z]{2,6}$', 'Entre 2 y 6 letras mayúsculas, ej. EMBOL.')


class ConfigTareas(models.Model):
    """Configuración del módulo por empresa: prefijo y último correlativo de los tickets."""

    empresa = models.OneToOneField('empresas.Empresa', on_delete=models.CASCADE, related_name='config_tareas')
    prefijo = models.CharField(
        'Prefijo de tickets', max_length=6, validators=[prefijo_validator],
        help_text='Ej. EMBOL → EMBOL-0001. Cambiarlo no renumera: el correlativo sigue.',
    )
    secuencia = models.PositiveIntegerField('Último correlativo', default=0)

    class Meta:
        verbose_name = 'Configuración de Tareas'
        verbose_name_plural = 'Configuraciones de Tareas'

    def __str__(self):
        return f'{self.empresa}: {self.prefijo}-{self.secuencia:04d}'

    def save(self, *args, **kwargs):
        self.prefijo = (self.prefijo or '').strip().upper()
        super().save(*args, **kwargs)

    @staticmethod
    def prefijo_por_defecto(empresa):
        letras = re.sub(r'[^A-Za-z]', '', empresa.slug).upper()[:6]
        return letras if len(letras) >= 2 else 'TAR'

    @classmethod
    def de(cls, empresa):
        """Config de la empresa (se crea con un prefijo derivado del slug si falta)."""
        config, _ = cls.objects.get_or_create(empresa=empresa, defaults={'prefijo': cls.prefijo_por_defecto(empresa)})
        return config


class Etiqueta(models.Model):
    """Tipo de actividad (con color) para clasificar tickets."""

    class Color(models.TextChoices):
        INFO = 'info', 'Azul'
        SUCCESS = 'success', 'Verde'
        WARNING = 'warning', 'Ámbar'
        ERROR = 'error', 'Rojo'
        ACCENT = 'accent', 'Acento'
        NEUTRAL = 'neutral', 'Gris'
        SECONDARY = 'secondary', 'Secundario'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='etiquetas_tareas')
    nombre = models.CharField('Nombre', max_length=50)
    color = models.CharField('Color', max_length=20, choices=Color.choices, default=Color.NEUTRAL)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Tipo de actividad'
        verbose_name_plural = 'Tipos de actividad'
        constraints = [
            models.UniqueConstraint(models.functions.Lower('nombre'), 'empresa', name='tar_etiqueta_nombre_unico'),
        ]

    def __str__(self):
        return self.nombre


class Ticket(models.Model):
    class Estado(models.TextChoices):
        # El orden define el orden de las columnas del tablero.
        ENTRADA = 'BACKLOG', 'Entrada'
        POR_HACER = 'TODO', 'Por hacer'
        EN_PROGRESO = 'IN_PROGRESS', 'En progreso'
        CONCLUIDO = 'DONE', 'Concluido'
        SUSPENDIDO = 'WAITING', 'Suspendido/Cancelado'

    class Prioridad(models.TextChoices):
        BAJA = 'LOW', 'Baja'
        MEDIA = 'MEDIUM', 'Media'
        ALTA = 'HIGH', 'Alta'
        URGENTE = 'URGENT', 'Urgente'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='tickets')
    codigo = models.CharField('Código', max_length=24, blank=True, default='')
    titulo = models.CharField('Título', max_length=255)
    solicitante = models.CharField('Solicitante', max_length=150)
    descripcion = models.TextField('Descripción', blank=True)
    padre = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='hijos', verbose_name='Deriva de',
    )
    estado = models.CharField('Estado', max_length=20, choices=Estado.choices, default=Estado.ENTRADA)
    prioridad = models.CharField('Prioridad', max_length=10, choices=Prioridad.choices, default=Prioridad.MEDIA)
    tiene_subproductos = models.BooleanField(
        'Tiene subproductos', default=False,
        help_text='Si se marca, cada ejecutor tiene su subticket independiente (avanza por separado). '
                  'Si no, la tarea es colaborativa: un estado compartido que mueve cualquiera.',
    )
    creador = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='tickets_creados',
        verbose_name='Creado por',
    )
    proyecto = models.ForeignKey(
        'proyectos.Proyecto', null=True, blank=True, on_delete=models.SET_NULL, related_name='tickets',
    )
    vence = models.DateField('Vence', null=True, blank=True)
    etiquetas = models.ManyToManyField(Etiqueta, blank=True, related_name='tickets')

    posicion = models.PositiveIntegerField(default=0)
    cerrado_en = models.DateTimeField('Cerrado', null=True, blank=True)
    archivado_en = models.DateTimeField('Archivado', null=True, blank=True)
    suspendido_en = models.DateTimeField(
        'Suspendido por el coordinador', null=True, blank=True,
        help_text='Distinto de «Suspendido» por el ejecutor: solo quien dirige lo fija/quita, y mientras '
                  'está fijado el ticket queda bloqueado (no se puede mover).',
    )
    dividido_en = models.DateTimeField(
        'Dividido en partes', null=True, blank=True,
        help_text='El ticket es un contenedor: se descompuso en partes (-1, -2…) y ya no aparece '
                  'como card en el tablero; solo sus partes.',
    )
    es_parte_dividida = models.BooleanField(
        'Es una parte dividida', default=False,
        help_text='Hijos creados por «Dividir» (clon del padre) frente a los creados por «Derivar».',
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)
    legacy_source = models.CharField(max_length=20, blank=True, editable=False)
    legacy_id = models.PositiveIntegerField(null=True, blank=True, editable=False, db_index=True)

    class Meta:
        ordering = ['posicion', '-creado']
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'codigo'], name='tar_ticket_empresa_codigo_unico'),
        ]

    def __str__(self):
        return f'{self.clave} · {self.titulo}'

    # ── Códigos ───────────────────────────────────────────────────────────────
    @staticmethod
    def _siguiente_codigo(empresa_id):
        """Correlativo POR EMPRESA `<prefijo>-0001`. Se incrementa bajo lock de fila: dos
        tickets simultáneos nunca reciben el mismo número y cambiar el prefijo no reinicia
        la numeración. Debe llamarse dentro de transaction.atomic()."""
        from empresas.models import Empresa
        ConfigTareas.de(Empresa.objects.get(pk=empresa_id))
        config = ConfigTareas.objects.select_for_update().get(empresa_id=empresa_id)
        config.secuencia += 1
        config.save(update_fields=['secuencia'])
        return f'{config.prefijo}-{config.secuencia:04d}'

    def _resolver_empresa(self):
        """Empresa del ticket si no vino explícita: la del padre. Un ticket sin empresa no existe."""
        if not self.empresa_id and self.padre_id:
            self.empresa_id = Ticket.objects.filter(pk=self.padre_id).values_list('empresa_id', flat=True).first()
        if not self.empresa_id:
            raise ValueError('El ticket necesita una empresa.')

    def _siguiente_codigo_hijo(self):
        """Correlativo jerárquico colgado del código del padre: EMBOL-0014-1, -2… Robusto ante
        huecos: toma el mayor sufijo numérico existente + 1, no el conteo."""
        base = self.codigo or self.clave
        prefijo = f'{base}-'
        nums = [
            int(c[len(prefijo):])
            for c in self.hijos.exclude(codigo='').values_list('codigo', flat=True)
            if c.startswith(prefijo) and c[len(prefijo):].isdigit()
        ]
        return f'{base}-{(max(nums) + 1) if nums else 1}'

    def crear_hijo(self, **kwargs):
        """Crea un hijo con código jerárquico, reintentando ante colisión. Fija el código ANTES
        de save(), así save() no consume el correlativo de la empresa."""
        kwargs.setdefault('padre', self)
        kwargs.setdefault('empresa_id', self.empresa_id)
        for _ in range(5):
            hijo = Ticket(codigo=self._siguiente_codigo_hijo(), **kwargs)
            try:
                with transaction.atomic():
                    hijo.save()
                return hijo
            except IntegrityError:
                continue
        hijo = Ticket(codigo=self._siguiente_codigo_hijo(), **kwargs)
        hijo.save()
        return hijo

    def clean(self):
        super().clean()
        if self.proyecto_id and self.empresa_id and self.proyecto.empresa_id != self.empresa_id:
            raise ValidationError({'proyecto': 'El proyecto pertenece a otra empresa.'})

    def save(self, *args, **kwargs):
        self._resolver_empresa()
        if self.proyecto_id and self.proyecto.empresa_id != self.empresa_id:
            raise ValueError('El proyecto del ticket pertenece a otra empresa.')
        if not self.codigo:
            for _ in range(5):
                try:
                    with transaction.atomic():
                        self.codigo = self._siguiente_codigo(self.empresa_id)
                        return super().save(*args, **kwargs)
                except IntegrityError:
                    self.codigo = ''
            with transaction.atomic():
                self.codigo = self._siguiente_codigo(self.empresa_id)
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)

    # ── Propiedades ───────────────────────────────────────────────────────────
    @property
    def clave(self):
        return self.codigo or f'#{self.pk}'

    @property
    def esta_archivado(self):
        return self.archivado_en is not None

    @property
    def esta_suspendido(self):
        return self.suspendido_en is not None

    @property
    def esta_dividido(self):
        return self.dividido_en is not None

    @property
    def esta_vencido(self):
        return bool(self.vence and self.estado != self.Estado.CONCLUIDO and self.vence < timezone.localdate())

    @property
    def color_estado(self):
        E = self.Estado
        return {E.ENTRADA: 'neutral', E.POR_HACER: 'info', E.EN_PROGRESO: 'warning',
                E.CONCLUIDO: 'success', E.SUSPENDIDO: 'error'}.get(self.estado, 'neutral')

    @property
    def color_prioridad(self):
        P = self.Prioridad
        return {P.BAJA: 'ghost', P.MEDIA: 'info', P.ALTA: 'warning', P.URGENTE: 'error'}.get(self.prioridad, 'ghost')

    def ids_hilo(self, max_profundidad=10):
        """[pk propio + ancestros]: el detalle de un derivado muestra también el seguimiento de su
        cadena de padres. `max_profundidad` corta ciclos accidentales."""
        ids, t = [self.pk], self
        while t.padre_id and len(ids) <= max_profundidad:
            ids.append(t.padre_id)
            t = t.padre
        return ids

    @property
    def ejecutores(self):
        return self.asignaciones.filter(tipo=Asignacion.Tipo.EJECUTOR)

    @property
    def expertos(self):
        return self.asignaciones.filter(tipo=Asignacion.Tipo.EXPERTO)

    def es_participante(self, user):
        return self.asignaciones.filter(user=user).exists()

    def recalcular_estado(self):
        """Estado del ticket = agregado de los subtickets de los ejecutores."""
        ejec = list(self.ejecutores)
        E = self.Estado
        if self.suspendido_en:
            nuevo = E.SUSPENDIDO        # suspendido por el director, incluso sin ejecutores
        elif not ejec:
            nuevo = E.ENTRADA
        elif all(a.estado == E.SUSPENDIDO for a in ejec):
            nuevo = E.SUSPENDIDO
        elif all(a.estado == E.CONCLUIDO and a.aprobado_en for a in ejec):
            nuevo = E.CONCLUIDO         # todos concluidos Y aprobados
        elif any(a.estado in (E.EN_PROGRESO, E.CONCLUIDO) for a in ejec):
            nuevo = E.EN_PROGRESO
        else:
            nuevo = E.POR_HACER
        if nuevo != self.estado:
            self.estado = nuevo
            if nuevo == E.CONCLUIDO and not self.cerrado_en:
                self.cerrado_en = timezone.now()
            elif nuevo != E.CONCLUIDO:
                self.cerrado_en = None
            self.save(update_fields=['estado', 'cerrado_en', 'actualizado'])
        return nuevo


class Comentario(models.Model):
    """Mensaje del chat de seguimiento de un ticket."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='comentarios')
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    texto = models.TextField('Mensaje')
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['creado']

    def __str__(self):
        return f'Comentario #{self.pk} en {self.ticket.clave}'


class Evento(models.Model):
    """Historial de actividad de un ticket (estado, asignación, prioridad, aprobación…)."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='eventos')
    # SET_NULL: si se desasigna a alguien, el historial sobrevive (`detalle` ya guarda el texto).
    asignacion = models.ForeignKey('Asignacion', null=True, blank=True, on_delete=models.SET_NULL, related_name='eventos')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    tipo = models.CharField(max_length=30)  # created | status | assignee | priority | due | conclude | approve | reject | archived | split
    detalle = models.CharField(max_length=255, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['creado']

    def __str__(self):
        return f'{self.tipo} en {self.ticket.clave}'


class Asignacion(models.Model):
    """Subticket por persona asignada. El ejecutor avanza su propio estado; el ticket agrega."""

    class Tipo(models.TextChoices):
        EJECUTOR = 'EJECUTOR', 'Ejecutor'
        EXPERTO = 'EXPERTO', 'Experto'

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='asignaciones')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='asignaciones_tareas')
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.EJECUTOR)
    estado = models.CharField(max_length=20, choices=Ticket.Estado.choices, default=Ticket.Estado.POR_HACER)
    posicion = models.PositiveIntegerField(default=0)
    iniciado_en = models.DateTimeField(null=True, blank=True)
    cerrado_en = models.DateTimeField(null=True, blank=True)
    conclusion = models.TextField('Conclusión', blank=True)
    aprobado_en = models.DateTimeField(null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    # Tiempo acumulado por estado (se pausa mientras el subticket está suspendido).
    tiempo_por_hacer = models.DurationField('Tiempo en Por hacer', default=timedelta)
    tiempo_en_progreso = models.DurationField('Tiempo en En progreso', default=timedelta)
    estado_cambiado_en = models.DateTimeField(default=timezone.now)

    # Estado previo a la suspensión del director: al reactivar se restaura.
    estado_antes_de_suspender = models.CharField(max_length=20, blank=True, default='')

    class Meta:
        ordering = ['posicion', 'creado']
        constraints = [
            models.UniqueConstraint(fields=['ticket', 'user'], name='tar_asignacion_ticket_user_unico'),
        ]

    def __str__(self):
        return f'{self.get_tipo_display()} {self.user} · {self.ticket.clave}'

    @property
    def es_ejecutor(self):
        return self.tipo == self.Tipo.EJECUTOR

    @property
    def necesita_aprobacion(self):
        return self.estado == Ticket.Estado.CONCLUIDO and self.aprobado_en is None

    _BUCKETS = {
        Ticket.Estado.POR_HACER: 'tiempo_por_hacer',
        Ticket.Estado.EN_PROGRESO: 'tiempo_en_progreso',
    }

    def avanzar_a(self, nuevo_estado, ahora=None):
        """Cambia de estado acumulando el tiempo del tramo anterior. No guarda.

        Solo POR_HACER/EN_PROGRESO acumulan; SUSPENDIDO, CONCLUIDO y ENTRADA pausan el reloj.
        Salir de CONCLUIDO (reabrir) invalida la conclusión: se limpian `aprobado_en` y
        `cerrado_en`, así el trabajo rehecho vuelve a pasar por aprobación.
        """
        ahora = ahora or timezone.now()
        bucket = self._BUCKETS.get(self.estado)
        if bucket:
            setattr(self, bucket, getattr(self, bucket) + (ahora - self.estado_cambiado_en))
        if nuevo_estado == Ticket.Estado.EN_PROGRESO and not self.iniciado_en:
            self.iniciado_en = ahora
        if self.estado == Ticket.Estado.CONCLUIDO and nuevo_estado != Ticket.Estado.CONCLUIDO:
            self.aprobado_en = None
            self.cerrado_en = None
        self.estado = nuevo_estado
        self.estado_cambiado_en = ahora

    def tiempo_en(self, estado, ahora=None):
        """Tiempo acumulado en `estado`, incluyendo el tramo en curso si es el estado actual."""
        bucket = self._BUCKETS.get(estado)
        if not bucket:
            return timedelta()
        total = getattr(self, bucket)
        if self.estado == estado:
            total += (ahora or timezone.now()) - self.estado_cambiado_en
        return total
