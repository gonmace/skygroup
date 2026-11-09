import datetime

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models


def quitar_cargo(puesto, cargo):
    """El puesto no repite el cargo: «Supervisor Civil» con cargo «Supervisor» queda en «Civil»."""
    puesto = ' '.join((puesto or '').split())
    cargo = (cargo or '').strip()
    if cargo and puesto.casefold().startswith(cargo.casefold()):
        resto = puesto[len(cargo):]
        if not resto or not resto[0].isalnum():   # no cortar «Supervisores» por tener «Supervisor» al inicio
            return resto.lstrip(' -–—·:')
    return puesto


def unir_cargo(cargo, puesto):
    """«Supervisor - Civil»: cargo de la empresa y, si lo hay, el puesto (sin repetir el cargo)."""
    puesto = quitar_cargo(puesto, cargo)
    return f'{cargo} - {puesto}' if puesto else cargo


CIUDADES = [('NONE', 'Sin alimentación'), ('LPZ', 'La Paz'), ('CBA', 'Cochabamba'), ('SCZ', 'Santa Cruz')]


def almacenamiento_privado():
    from django.core.files.storage import storages
    return storages['privado']


def ruta_plantilla(instance, filename):
    return f'{instance.empresa_id}/jor/certificado/plantilla.xlsx'


class Perfil(models.Model):
    """Datos de Jornadas de una persona en una empresa (el «Employee» de skylog), colgados de su Membresía.
    Se crea al primer uso (`Perfil.de`). Los permisos NO viven aquí: son capacidades `jor.*`."""

    membresia = models.OneToOneField('cuentas.Membresia', on_delete=models.CASCADE, related_name='perfil_jor')
    cargo = models.CharField('Puesto', max_length=150, blank=True,
                             help_text='Especialidad o detalle del cargo, sin repetirlo: «Civil» para el cargo «Supervisor» '
                                       'se muestra como «Supervisor - Civil».')
    hora_entrada = models.TimeField('Hora de entrada', default=datetime.time(8, 0),
                                    help_text='Hora de referencia para calcular atrasos.')
    puede_excepcion = models.BooleanField('Puede marcar fuera de la sede', default=True,
                                          help_text='Si la ubicación no valida, la jornada queda «pendiente» y la '
                                                    'revisa un coordinador. Apágalo para rechazar esas marcaciones.')
    exige_reporte = models.BooleanField('Reporte diario obligatorio', default=True,
                                        help_text='Exige completar «Realizado» y «Planificado» para finalizar la jornada. '
                                                  'Apágalo en roles que no reportan (p. ej. bodega).')
    # Datos del certificado de pago (ver jor_reportes.certificado).
    haber_basico = models.DecimalField('Haber básico', max_digits=12, decimal_places=2, default=0)
    ciudad_catering = models.CharField('Ciudad (alimentación)', max_length=4, choices=CIUDADES, default='NONE',
                                       help_text='Planilla de alimentación del certificado en la que figura.')
    numero_item = models.PositiveSmallIntegerField('N.º de ítem', null=True, blank=True,
                                                   help_text='Orden en el certificado; vacío = al final, por nombre.')
    activo = models.BooleanField('Puede fichar jornadas', default=True)
    legacy_source = models.CharField(max_length=20, blank=True, editable=False)
    legacy_id = models.PositiveIntegerField(null=True, blank=True, editable=False, db_index=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Perfil de jornadas'
        verbose_name_plural = 'Perfiles de jornadas'

    def __str__(self):
        return self.nombre

    @classmethod
    def de(cls, membresia):
        return cls.objects.get_or_create(membresia=membresia)[0]

    @classmethod
    def asegurar_de(cls, empresa):
        """Crea el perfil de quien aún no lo tiene (se crean al primer uso, pero los reportes deben listar a todos)."""
        faltan = empresa.membresias.filter(activa=True, perfil_jor__isnull=True)
        cls.objects.bulk_create([cls(membresia=m) for m in faltan], ignore_conflicts=True)

    @property
    def user(self):
        return self.membresia.user

    @property
    def empresa_id(self):
        return self.membresia.empresa_id

    @property
    def nombre(self):
        return str(self.membresia.user)

    @property
    def cargo_completo(self):
        """«Cargo - Puesto» (p. ej. «Supervisor - Civil»); solo el cargo si no hay puesto."""
        return unir_cargo(self.membresia.rol.nombre, self.cargo)


class DispositivoMarcacion(models.Model):
    """Celular (passkey WebAuthn) con el que una persona marca su jornada. Solo uno activo por perfil;
    para cambiarlo, un administrador lo libera (queda el registro, `activo=False`)."""

    perfil = models.ForeignKey(Perfil, on_delete=models.CASCADE, related_name='dispositivos')
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.PositiveBigIntegerField(default=0)
    nombre = models.CharField('Nombre', max_length=80, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    ultimo_uso = models.DateTimeField(null=True, blank=True)
    liberado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='+')
    liberado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado']
        verbose_name = 'Dispositivo de marcación'
        verbose_name_plural = 'Dispositivos de marcación'
        constraints = [
            models.UniqueConstraint(fields=['perfil'], condition=models.Q(activo=True), name='jor_un_dispositivo_activo'),
        ]

    def __str__(self):
        return f'{self.perfil} — {self.nombre or "celular"}'


class ConfigJornadas(models.Model):
    """Configuración de Jornadas de una empresa (una fila por empresa, creada al primer uso)."""

    empresa = models.OneToOneField('empresas.Empresa', on_delete=models.CASCADE, related_name='config_jornadas')
    descuento_refrigerio_min = models.PositiveSmallIntegerField(
        'Refrigerio descontado (min)', default=60, validators=[MaxValueValidator(240)],
        help_text='Se descuenta una vez por día de las horas trabajadas en el reporte de asistencia.')
    plantilla_certificado = models.FileField(
        'Plantilla del reporte de personal (.xlsx)', upload_to=ruta_plantilla, storage=almacenamiento_privado,
        blank=True, max_length=300, help_text='Libro con la hoja «PL» y las hojas «1»…«12». Sin ella no se genera el reporte.')
    tipo_cambio_certificado = models.DecimalField('Tipo de cambio del reporte', max_digits=18, decimal_places=12,
                                                  default='0.461310893326')
    moneda_certificado = models.CharField('Moneda del reporte', max_length=30, default='Bolivianos')

    class Meta:
        verbose_name = 'Configuración de jornadas'
        verbose_name_plural = 'Configuraciones de jornadas'

    @classmethod
    def de(cls, empresa):
        return cls.objects.get_or_create(empresa=empresa)[0]
