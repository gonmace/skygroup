from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.cache import cache
from django.db import models
from django.db.models.functions import Lower

from empresas.models import Modulo

from .roles import RolBase


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _crear(self, email, password, **extra):
        if not email:
            raise ValueError('El correo es obligatorio.')
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault('is_staff', False)
        extra.setdefault('is_superuser', False)
        return self._crear(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        if not extra['is_staff'] or not extra['is_superuser']:
            raise ValueError('El superusuario debe tener is_staff=True e is_superuser=True.')
        return self._crear(email, password, **extra)


class User(AbstractUser):
    """Usuario único de la plataforma. Se identifica por correo (sin username).

    El rol NO vive aquí: es por empresa (ver `Membresia`). `is_superuser` es el
    administrador global de la plataforma.
    """

    username = None
    email = models.EmailField('Correo', unique=True)
    telefono = models.CharField('Teléfono', max_length=30, blank=True)
    # Borrado lógico: la cuenta no entra ni aparece en las listas, pero conserva todo su historial y el superusuario la restaura.
    is_deleted = models.BooleanField('Eliminado', default=False, db_index=True)
    eliminado_en = models.DateTimeField('Eliminado el', null=True, blank=True)
    nextcloud_uid = models.CharField('Usuario Nextcloud', max_length=150, blank=True, db_index=True)
    # Trazabilidad para los futuros importadores (reg / skydesk / skylog).
    legacy_source = models.CharField(max_length=20, blank=True, editable=False)
    legacy_id = models.PositiveIntegerField(null=True, blank=True, editable=False, db_index=True)
    # Administrador de sistema: se define en Plataforma (no es un cargo RACI). Gestiona estas empresas aunque no
    # sea miembro. El superusuario (`is_superuser`) abarca todas.
    empresas_administradas = models.ManyToManyField(
        'empresas.Empresa', blank=True, related_name='administradores', verbose_name='Administra')

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'
        constraints = [
            models.UniqueConstraint(Lower('email'), name='cuentas_user_email_ci_unique'),
        ]

    def __str__(self):
        return self.get_full_name() or self.email

    @property
    def iniciales(self):
        """Inicial del nombre y del apellido («Ana María Pérez Soto» → «AP»). Si falta alguno usa el que haya;
        sin nombre ni apellido, la primera letra del correo."""
        partes = [(p.split() or [''])[0][:1] for p in (self.first_name, self.last_name)]
        return (''.join(partes) or (self.email or '?')[:1]).upper()

    def save(self, *args, **kwargs):
        self.email = (self.email or '').strip().lower()
        super().save(*args, **kwargs)


class RolEmpresa(models.Model):
    """Cargo: nombre definido por el administrador de la empresa («ITO», «Supervisor»…),
    colgado de un nivel de acceso (rol base RACI) que fija la semántica y los permisos por defecto."""

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='roles')
    nombre = models.CharField('Nombre', max_length=60)
    rol_base = models.CharField('Nivel de acceso', max_length=20, choices=RolBase.choices)
    descripcion = models.CharField('Descripción', max_length=200, blank=True)
    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['empresa', 'orden', 'nombre']
        verbose_name = 'Cargo'
        verbose_name_plural = 'Cargos'
        constraints = [
            models.UniqueConstraint(Lower('nombre'), 'empresa', name='cuentas_rolempresa_nombre_unico'),
        ]

    def __str__(self):
        return f'{self.nombre} ({self.get_rol_base_display()})'

    @property
    def jerarquia(self):
        """0-3: peso del rol base según RACI (0 = Coordinador, el más alto; 3 = Observador). Fija el color de
        insignias y avatares (clase `badge-rol-N` en styles.css): un color por rol, en orden de espectro."""
        return {'COORDINADOR': 0, 'MIEMBRO': 1, 'ESPECIALISTA': 2}.get(self.rol_base, 3)

    @property
    def tono(self):
        """0-3: intensidad del avatar dentro del color de su rol base (clase `tono-N`). Distingue los cargos que
        comparten nivel de acceso sin cambiar el color: se reparte por orden entre los cargos del mismo nivel."""
        clave = f'rol_tonos:{self.empresa_id}:{self.rol_base}'
        orden = cache.get(clave)
        if orden is None:
            orden = list(RolEmpresa.objects.filter(empresa_id=self.empresa_id, rol_base=self.rol_base)
                         .order_by('orden', 'nombre', 'pk').values_list('pk', flat=True))
            cache.set(clave, orden, 300)
        try:
            return orden.index(self.pk) % 4
        except ValueError:
            return 0


class Membresia(models.Model):
    """Pertenencia de un usuario a una empresa, con un rol de esa empresa."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='membresias')
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='membresias')
    rol = models.ForeignKey(RolEmpresa, on_delete=models.PROTECT, related_name='membresias')
    contratista = models.ForeignKey(
        'empresas.Contratista', null=True, blank=True, on_delete=models.PROTECT, related_name='membresias',
        verbose_name='Contratista', help_text='Vacío = personal de la propia empresa (sin contratista).',
    )
    sede = models.ForeignKey(
        'empresas.Sede', null=True, blank=True, on_delete=models.PROTECT, related_name='membresias',
        verbose_name='Sede', help_text='Opcional: la sede de la empresa a la que pertenece.',
    )
    activa = models.BooleanField(default=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Membresía'
        verbose_name_plural = 'Membresías'
        constraints = [
            models.UniqueConstraint(fields=['user', 'empresa'], name='cuentas_membresia_unica'),
        ]

    def __str__(self):
        return f'{self.user} @ {self.empresa} · {self.rol.nombre}'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.rol_id and self.empresa_id and self.rol.empresa_id != self.empresa_id:
            raise ValidationError({'rol': 'El rol pertenece a otra empresa.'})
        if self.contratista_id and self.empresa_id and self.contratista.empresa_id != self.empresa_id:
            raise ValidationError({'contratista': 'El contratista pertenece a otra empresa.'})
        if self.sede_id and self.empresa_id and self.sede.empresa_id != self.empresa_id:
            raise ValidationError({'sede': 'La sede pertenece a otra empresa.'})


class DominioPermitido(models.Model):
    """Dominio de correo cuyas personas pueden darse de alta solas en la empresa (acceso automático),
    con el cargo indicado. Nunca puede ser Coordinador ni un dominio público (gmail.com…)."""

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='dominios_permitidos')
    dominio = models.CharField('Dominio', max_length=100, help_text='Sin @, por ejemplo: tekon.com')
    rol = models.ForeignKey(RolEmpresa, on_delete=models.PROTECT, related_name='+', verbose_name='Cargo asignado')
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Dominio permitido'
        verbose_name_plural = 'Dominios permitidos'
        ordering = ['dominio']
        constraints = [
            models.UniqueConstraint(Lower('dominio'), 'empresa', name='cuentas_dominio_unico'),
        ]

    def __str__(self):
        return f'@{self.dominio}'

    def clean(self):
        from django.core.exceptions import ValidationError
        from .registro import DOMINIOS_PUBLICOS, normalizar_dominio
        self.dominio = normalizar_dominio(self.dominio)
        errores = {}
        if not self.dominio or '.' not in self.dominio or ' ' in self.dominio or '@' in self.dominio:
            errores['dominio'] = 'Indica un dominio válido, por ejemplo tekon.com.'
        elif self.dominio in DOMINIOS_PUBLICOS:
            errores['dominio'] = 'Es un dominio de correo público: cualquiera podría registrarse.'
        if self.rol_id and self.empresa_id:
            if self.rol.empresa_id != self.empresa_id:
                errores['rol'] = 'El cargo pertenece a otra empresa.'
            elif self.rol.rol_base == RolBase.COORDINADOR:
                errores['rol'] = 'El alta automática no puede asignar un cargo de Coordinador.'
        if errores:
            raise ValidationError(errores)


class CorreoBloqueado(models.Model):
    """Correo que no puede darse de alta solo en la empresa, aunque su dominio esté permitido."""

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='correos_bloqueados')
    email = models.EmailField('Correo')
    motivo = models.CharField('Motivo', max_length=200, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Correo bloqueado'
        verbose_name_plural = 'Correos bloqueados'
        ordering = ['email']
        constraints = [
            models.UniqueConstraint(Lower('email'), 'empresa', name='cuentas_correo_bloqueado_unico'),
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = (self.email or '').strip().lower()
        super().save(*args, **kwargs)


class AccesoModulo(models.Model):
    """Ajuste por módulo de una membresía: deshabilitarlo o usar otro rol solo ahí."""

    membresia = models.ForeignKey(Membresia, on_delete=models.CASCADE, related_name='accesos')
    modulo = models.CharField(max_length=3, choices=Modulo.choices)
    habilitado = models.BooleanField(default=True)
    rol_override = models.ForeignKey(
        RolEmpresa, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
        help_text='Vacío = el rol de la membresía.',
    )

    class Meta:
        verbose_name = 'Acceso por módulo'
        verbose_name_plural = 'Accesos por módulo'
        constraints = [
            models.UniqueConstraint(fields=['membresia', 'modulo'], name='cuentas_acceso_modulo_unico'),
        ]


class RolPermiso(models.Model):
    """Diferencia respecto al default del rol base para una capacidad en un rol de empresa."""

    rol_empresa = models.ForeignKey(RolEmpresa, on_delete=models.CASCADE, related_name='permisos')
    capacidad = models.CharField(max_length=80)
    habilitado = models.BooleanField()

    class Meta:
        verbose_name = 'Permiso de rol'
        verbose_name_plural = 'Permisos de rol'
        constraints = [
            models.UniqueConstraint(fields=['rol_empresa', 'capacidad'], name='cuentas_rolpermiso_unico'),
        ]


class UsuarioPermiso(models.Model):
    """Excepción por persona (prevalece sobre el rol)."""

    membresia = models.ForeignKey(Membresia, on_delete=models.CASCADE, related_name='excepciones')
    capacidad = models.CharField(max_length=80)
    habilitado = models.BooleanField()

    class Meta:
        verbose_name = 'Permiso de usuario'
        verbose_name_plural = 'Permisos de usuario'
        constraints = [
            models.UniqueConstraint(fields=['membresia', 'capacidad'], name='cuentas_usuariopermiso_unico'),
        ]
