import os

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

slug_validator = RegexValidator(
    r'^[a-z][a-z0-9-]{1,30}$',
    'Solo minúsculas, números y guiones (2 a 31 caracteres), empezando con una letra.',
)
hex_color_validator = RegexValidator(r'^#[0-9A-Fa-f]{6}$', 'Color hexadecimal de 6 dígitos, ej. #E4002B.')

# Primer segmento de ruta que NUNCA puede ser slug de empresa: rutas propias del servidor
# o del urlconf raíz sin prefijo (ver empresas.tenancy.EmpresaMiddleware).
RESERVED_SLUGS = frozenset({
    'static', 'media', 'ws', 'api', 'panel', 'acceso', 'archivos', 'notificaciones', 'healthz',
    'config', 'proyectos', 'registros', 'tareas', 'jornadas', 'admin', 'marca',
    'robots.txt', 'sitemap.xml', '__reload__',
})

EMPRESA_CACHE_KEY = 'empresa:slug:{}'


class Modulo(models.TextChoices):
    REGISTROS = 'reg', 'Registros'
    TAREAS = 'tar', 'Tareas'
    JORNADAS = 'jor', 'Asistencia'
    MENSAJERIA = 'msj', 'Mensajería'
    APU = 'apu', 'APU IA'


def _validate_logo_size(value):
    if value.size > 2 * 1024 * 1024:
        raise ValidationError('El archivo no puede superar los 2 MB.')


def _validate_favicon_ext(value):
    # SVG excluido a propósito: es XML ejecutable si alguien lo abre directo.
    if os.path.splitext(value.name)[1].lower() not in ('.png', '.ico'):
        raise ValidationError('El favicon debe ser PNG o ICO.')


def _ext(filename):
    return os.path.splitext(filename)[1].lower()


# Funciones de módulo (no closures): las migraciones las referencian por ruta.
def logo_light_path(instance, filename):
    return f'branding/{instance.slug}/logo-light{_ext(filename)}'


def logo_dark_path(instance, filename):
    return f'branding/{instance.slug}/logo-dark{_ext(filename)}'


def favicon_path(instance, filename):
    return f'branding/{instance.slug}/favicon{_ext(filename)}'


def modulos_default():
    return [m.value for m in Modulo]


REPORTE_CONTROL_PERSONAL = 'Reporte de personal'   # nombre genérico del reporte de Jornadas (termino_certificado)

class Empresa(models.Model):
    """Empresa cliente (tenant). Todo dato operativo cuelga de una empresa y las empresas
    no se ven entre sí. Se identifica en la URL por el prefijo `/<slug>/`."""

    nombre = models.CharField('Nombre', max_length=120)
    slug = models.SlugField(
        'Identificador en la URL', max_length=31, unique=True, validators=[slug_validator],
        help_text='Prefijo de todas las rutas de la empresa, ej. "tekon" → /tekon/. '
                  'Cambiarlo invalida los links ya enviados por correo.',
    )
    activa = models.BooleanField(
        'Activa', default=True,
        help_text='Desactivada: nadie de la empresa puede entrar (sus datos se conservan).',
    )
    razon_social = models.CharField('Razón social', max_length=160, blank=True)
    rut = models.CharField('RUT / NIT', max_length=20, blank=True)
    contacto_email = models.EmailField('Correo de contacto', blank=True)
    contacto_telefono = models.CharField('Teléfono', max_length=30, blank=True)

    modulos = models.JSONField(
        'Módulos habilitados', default=modulos_default, blank=True,
        help_text='Lista de códigos: reg (Registros), tar (Tareas), jor (Asistencia), msj (Mensajería), apu (Análisis de Precios Unitarios con IA).',
    )

    # ── Término para «Proyecto» ──
    termino_proyecto_singular = models.CharField(
        'Nombre de «proyecto» (singular)', max_length=40, default='Proyecto',
        help_text='Cómo llama esta empresa a sus proyectos, ej. «Sitio».',
    )
    termino_proyecto_plural = models.CharField(
        'Nombre de «proyectos» (plural)', max_length=40, default='Proyectos',
        help_text='Ej. «Sitios».',
    )

    # ── Término para el reporte de personal (Asistencia) ──
    termino_certificado = models.CharField(
        'Nombre del reporte de personal', max_length=60, blank=True, default=REPORTE_CONTROL_PERSONAL,
        help_text='Cómo llama esta empresa al reporte de Asistencia que consolida el control de personal, '
                  'ej. «Certificado de pago» o «Informe de personal». Vacío = «Reporte de personal».',
    )

    @property
    def nombre_certificado(self):
        return self.termino_certificado.strip() or REPORTE_CONTROL_PERSONAL

    # ── Marca ──
    nombre_marca = models.CharField(
        'Nombre de marca', max_length=60, blank=True,
        help_text='Título de la pestaña, login y firma de correos. Vacío = nombre de la empresa.',
    )
    logo_claro = models.ImageField(
        'Logo (tema claro)', upload_to=logo_light_path, blank=True, validators=[_validate_logo_size],
        help_text='PNG/JPG/WEBP, máx. 2 MB. Vacío = logo por defecto.',
    )
    logo_oscuro = models.ImageField(
        'Logo (tema oscuro)', upload_to=logo_dark_path, blank=True, validators=[_validate_logo_size],
        help_text='Vacío = se usa el logo del tema claro.',
    )
    favicon = models.FileField(
        'Favicon', upload_to=favicon_path, blank=True,
        validators=[_validate_logo_size, _validate_favicon_ext], help_text='PNG o ICO.',
    )
    color_primario = models.CharField('Color primario (claro)', max_length=7, blank=True, validators=[hex_color_validator])
    color_primario_oscuro = models.CharField('Color primario (oscuro)', max_length=7, blank=True, validators=[hex_color_validator])
    color_acento = models.CharField('Color de acento (claro)', max_length=7, blank=True, validators=[hex_color_validator])
    color_acento_oscuro = models.CharField('Color de acento (oscuro)', max_length=7, blank=True, validators=[hex_color_validator])

    # ── Correo ──
    email_remitente_nombre = models.CharField('Nombre del remitente', max_length=100, blank=True)
    email_remitente = models.EmailField('Correo del remitente', blank=True)

    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'

    def __str__(self):
        return self.nombre

    @classmethod
    def from_db(cls, db, field_names, values):
        obj = super().from_db(db, field_names, values)
        obj._slug_cargado = obj.__dict__.get('slug')
        return obj

    @property
    def marca(self):
        return self.nombre_marca or self.nombre

    @property
    def tiene_colores(self):
        return any([self.color_primario, self.color_primario_oscuro, self.color_acento, self.color_acento_oscuro])

    def version_tema(self):
        """Valor para cache-bust de logos y CSS de tema (cambia al guardar)."""
        return int(self.actualizada.timestamp()) if self.actualizada else 0

    def tiene_modulo(self, codigo):
        return codigo in (self.modulos or [])

    def clean(self):
        super().clean()
        slug = (self.slug or '').strip().lower()
        if slug in RESERVED_SLUGS or slug.isdigit():
            raise ValidationError({'slug': f'"{slug}" está reservado por el sistema.'})
        validos = {m.value for m in Modulo}
        if not isinstance(self.modulos, list) or set(self.modulos) - validos:
            raise ValidationError({'modulos': f'Módulos válidos: {", ".join(sorted(validos))}.'})

    def save(self, *args, **kwargs):
        self.slug = (self.slug or '').strip().lower()
        super().save(*args, **kwargs)
        self.invalidar_cache()

    def delete(self, *args, **kwargs):
        self.invalidar_cache()
        return super().delete(*args, **kwargs)

    def invalidar_cache(self):
        claves = {EMPRESA_CACHE_KEY.format(self.slug)}
        anterior = getattr(self, '_slug_cargado', None)
        if anterior:
            claves.add(EMPRESA_CACHE_KEY.format(anterior))
        try:
            cache.delete_many(list(claves))
        except Exception:  # Redis caído: el TTL corto termina de limpiar
            pass
        self._slug_cargado = self.slug


class Contratista(models.Model):
    """Organización contratista DENTRO de una empresa (la empresa es el cliente de la plataforma).

    Es lo que reg llama hoy «Empresas»: en toda la interfaz se dice SIEMPRE «contratista», nunca
    «empresa», para no confundirlo con el tenant. Delimita el alcance de lo que ve cada persona
    (un administrador de contratista ve lo de su contratista)."""

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='contratistas')
    nombre = models.CharField('Nombre', max_length=200)
    codigo = models.CharField('Código', max_length=50, help_text='Código único del contratista dentro de la empresa.')
    activo = models.BooleanField('Activo', default=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)
    legacy_source = models.CharField(max_length=20, blank=True, editable=False)
    legacy_id = models.PositiveIntegerField(null=True, blank=True, editable=False, db_index=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Contratista'
        verbose_name_plural = 'Contratistas'
        constraints = [
            # Único solo entre activos (borrado lógico libera el código).
            models.UniqueConstraint(
                models.functions.Lower('codigo'), 'empresa', condition=models.Q(is_deleted=False),
                name='empresas_contratista_codigo_unico',
            ),
        ]

    def __str__(self):
        return f'{self.nombre} ({self.codigo})'

    def save(self, *args, **kwargs):
        self.codigo = (self.codigo or '').strip().upper()
        super().save(*args, **kwargs)


class Sede(models.Model):
    """Sede (oficina, base o ciudad) de una empresa. Cada miembro puede pertenecer a una; es opcional."""

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='sedes')
    nombre = models.CharField('Nombre', max_length=80)
    activo = models.BooleanField('Activa', default=True)
    # Geocerca para verificar el inicio de jornada (Jornadas). Sin coordenadas, la presencia no se puede verificar.
    lat = models.DecimalField('Latitud', max_digits=9, decimal_places=6, null=True, blank=True)
    lon = models.DecimalField('Longitud', max_digits=9, decimal_places=6, null=True, blank=True)
    radio_m = models.PositiveSmallIntegerField('Radio (m)', default=80,
                                               help_text='Distancia máxima al punto de la sede para marcar jornada.')
    precision_max_m = models.PositiveSmallIntegerField('Precisión GPS máxima (m)', default=50,
                                                       help_text='Se rechaza una lectura de GPS menos precisa que esto.')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Sede'
        verbose_name_plural = 'Sedes'
        constraints = [
            models.UniqueConstraint(models.functions.Lower('nombre'), 'empresa', name='empresas_sede_nombre_unico'),
        ]

    def __str__(self):
        return self.nombre

    @property
    def tiene_geocerca(self):
        return self.lat is not None and self.lon is not None
