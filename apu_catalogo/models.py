import copy
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apu_motor import PerfilInvalido, validar_perfil


class Tipo(models.TextChoices):
    """Grupos de insumos; coinciden con los grupos del motor (`apu_motor.perfil.GRUPOS`)."""
    MATERIAL = 'MAT', 'Material'
    MANO_OBRA = 'MO', 'Mano de obra'
    EQUIPO = 'EQ', 'Equipo'


class Insumo(models.Model):
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='apu_insumos')
    codigo = models.CharField('Código', max_length=30)
    descripcion = models.CharField('Descripción', max_length=200)
    unidad = models.CharField('Unidad', max_length=20)
    tipo = models.CharField('Tipo', max_length=3, choices=Tipo.choices)
    activo = models.BooleanField('Activo', default=True)

    class Meta:
        ordering = ['tipo', 'codigo']
        verbose_name = 'Insumo'
        verbose_name_plural = 'Insumos'
        constraints = [models.UniqueConstraint(fields=['empresa', 'codigo'], name='apu_insumo_codigo_unico')]

    def __str__(self):
        return f'{self.codigo} · {self.descripcion}'

    def precio_vigente(self, region='', fecha=None):
        """Último precio con fecha ≤ `fecha` en la región; si no hay, el nacional (región vacía). None si no hay."""
        qs = self.precios.all()
        if fecha:
            qs = qs.filter(fecha__lte=fecha)
        if region:
            propio = qs.filter(region__iexact=region).order_by('-fecha').first()
            if propio:
                return propio
        return qs.filter(region='').order_by('-fecha').first()


class PrecioInsumo(models.Model):
    """Precio de un insumo en una región y fecha. Región vacía = precio nacional (respaldo de las demás)."""
    insumo = models.ForeignKey(Insumo, on_delete=models.CASCADE, related_name='precios')
    region = models.CharField('Región o ciudad', max_length=80, blank=True)
    fecha = models.DateField('Vigente desde')
    precio = models.DecimalField('Precio', max_digits=16, decimal_places=4)
    moneda = models.CharField('Moneda', max_length=3, help_text='Código ISO, p. ej. BOB o CLP.')
    estimado = models.BooleanField('Estimado por IA', default=False,
                                   help_text='Recomendación de la IA aceptada tal cual; conviene confirmarla con un precio real.')
    fuente = models.CharField('Fuente', max_length=200, blank=True)

    class Meta:
        ordering = ['insumo', 'region', '-fecha']
        verbose_name = 'Precio de insumo'
        verbose_name_plural = 'Precios de insumos'
        constraints = [
            models.UniqueConstraint(fields=['insumo', 'region', 'fecha'], name='apu_precio_unico'),
            models.CheckConstraint(condition=Q(precio__gte=0), name='apu_precio_no_negativo'),
        ]

    def __str__(self):
        return f'{self.insumo.codigo} {self.region or "nacional"} {self.fecha}: {self.precio} {self.moneda}'


class ItemModelo(models.Model):
    """Ítem del catálogo («Muro de ladrillo 6H e=12 cm [m²]») con su composición."""
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.CASCADE, related_name='apu_items')
    codigo = models.CharField('Código', max_length=30)
    descripcion = models.CharField('Descripción', max_length=250)
    unidad = models.CharField('Unidad', max_length=20)
    categoria = models.CharField('Categoría', max_length=80, blank=True, help_text='Obra gruesa, acabados…')
    activo = models.BooleanField('Activo', default=True)
    proyecto = models.ForeignKey('proyectos.Proyecto', null=True, blank=True, on_delete=models.PROTECT,
                                 related_name='apu_items',
                                 help_text='Proyecto al que pertenece el APU. Vacío solo en sub-análisis cargados por admin.')
    origen = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='copias',
                               help_text='APU del que se copió al reutilizarlo en otro proyecto.')
    creado_por = models.ForeignKey('cuentas.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        ordering = ['codigo']
        verbose_name = 'APU'
        verbose_name_plural = 'APU'
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'proyecto', 'codigo'], name='apu_item_codigo_unico',
                                    condition=Q(proyecto__isnull=False)),
            models.UniqueConstraint(fields=['empresa', 'codigo'], name='apu_item_codigo_sin_proyecto_unico',
                                    condition=Q(proyecto__isnull=True)),
        ]

    def __str__(self):
        return f'{self.codigo} · {self.descripcion} [{self.unidad}]'

    def depende_de(self, otro):
        """True si `otro` aparece en algún nivel de la composición de este ítem (sub-análisis recursivos)."""
        vistos, pendientes = set(), [self.pk]
        while pendientes:
            actual = pendientes.pop()
            if actual in vistos:
                continue
            vistos.add(actual)
            if actual == otro.pk:
                return True
            pendientes += list(LineaComposicion.objects.filter(item_id=actual, subitem__isnull=False)
                               .values_list('subitem_id', flat=True))
        return False


class LineaComposicion(models.Model):
    """Una línea de la composición: un insumo, o un sub-análisis (otro ítem, p. ej. hormigón o mortero).
    `cantidad` es la forma canónica: cantidad de insumo (o de sub-ítem) por UNA unidad del ítem."""
    item = models.ForeignKey(ItemModelo, on_delete=models.CASCADE, related_name='lineas')
    insumo = models.ForeignKey(Insumo, null=True, blank=True, on_delete=models.PROTECT, related_name='usos')
    subitem = models.ForeignKey(ItemModelo, null=True, blank=True, on_delete=models.PROTECT, related_name='usado_en')
    cantidad = models.DecimalField('Cantidad por unidad', max_digits=16, decimal_places=6)
    desperdicio_pct = models.DecimalField('Desperdicio (%)', max_digits=5, decimal_places=2, default=Decimal('0'))
    ayuda = models.JSONField('Ayuda de captura', blank=True, default=dict,
                             help_text='Cómo se obtuvo la cantidad, p. ej. {"cuadrilla": 3, "rendimiento": 12}.')
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['item', 'orden', 'pk']
        verbose_name = 'Línea de composición'
        verbose_name_plural = 'Líneas de composición'
        constraints = [
            models.CheckConstraint(
                condition=(Q(insumo__isnull=False, subitem__isnull=True) | Q(insumo__isnull=True, subitem__isnull=False)),
                name='apu_linea_insumo_o_subitem'),
            models.CheckConstraint(condition=Q(cantidad__gte=0), name='apu_linea_cantidad_no_negativa'),
        ]

    def __str__(self):
        return f'{self.item.codigo}: {self.insumo or self.subitem} × {self.cantidad}'

    def clean(self):
        if bool(self.insumo_id) == bool(self.subitem_id):
            raise ValidationError('Elige un insumo o un sub-ítem, no ambos.')
        if self.item_id:
            empresa = self.item.empresa_id
            otro = self.insumo or self.subitem
            if otro.empresa_id != empresa:
                raise ValidationError('El insumo o sub-ítem es de otra empresa.')
            if self.subitem_id and (self.subitem_id == self.item_id or self.subitem.depende_de(self.item)):
                raise ValidationError('El sub-ítem crearía un ciclo: ese ítem ya usa a este.')


class PerfilCalculo(models.Model):
    """Perfil de cálculo (recargos de un país o de una entidad contratante). `empresa` vacía = plantilla de la
    plataforma, que cada empresa copia y ajusta. `datos` sigue el esquema de `apu_motor.perfil`."""
    empresa = models.ForeignKey('empresas.Empresa', null=True, blank=True, on_delete=models.CASCADE,
                                related_name='apu_perfiles', help_text='Vacía = plantilla de la plataforma.')
    nombre = models.CharField('Nombre', max_length=100)
    pais = models.CharField('País', max_length=2, blank=True, help_text='Código ISO, p. ej. BO o CL.')
    moneda = models.CharField('Moneda', max_length=3)
    datos = models.JSONField('Líneas y redondeo')
    activo = models.BooleanField('Activo', default=True)

    class Meta:
        ordering = ['empresa_id', 'nombre']
        verbose_name = 'Perfil de cálculo'
        verbose_name_plural = 'Perfiles de cálculo'
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'nombre'], name='apu_perfil_nombre_unico'),
            # Las plantillas (empresa vacía) tampoco repiten nombre: la unicidad anterior no las cubre (NULL ≠ NULL).
            models.UniqueConstraint(fields=['nombre'], condition=Q(empresa__isnull=True), name='apu_perfil_plantilla_unica'),
        ]

    def __str__(self):
        return self.nombre if self.empresa_id else f'{self.nombre} (plantilla)'

    @classmethod
    def propios(cls, empresa):
        """Los perfiles de la empresa (únicos por empresa; las plantillas de la plataforma no se usan directamente)."""
        return cls.objects.filter(empresa=empresa, activo=True)

    @classmethod
    def para_empresa(cls, empresa, pk):
        """Un perfil usable por `empresa`: el propio, o —si es una plantilla— su copia en la empresa (se crea una sola
        vez; si ya la tiene con ese nombre, se reutiliza). None si no existe o es de otra empresa."""
        perfil = cls.objects.filter(Q(empresa=empresa) | Q(empresa__isnull=True), pk=pk or 0, activo=True).first()
        if perfil is None or perfil.empresa_id:
            return perfil
        return cls.objects.filter(empresa=empresa, nombre=perfil.nombre).first() or perfil.copiar_a(empresa)

    @property
    def es_plantilla(self):
        return self.empresa_id is None

    def clean(self):
        try:
            validar_perfil(self.datos)
        except PerfilInvalido as e:
            raise ValidationError({'datos': str(e)})

    def validado(self):
        """El perfil normalizado listo para `apu_motor.calcular`."""
        return validar_perfil({**self.datos, 'perfil': self.nombre, 'moneda': self.moneda})

    def filas(self):
        """Las líneas del perfil como filas legibles (para mostrar su estructura): código, concepto, cálculo, nivel."""
        perfil = self.validado()
        etiquetas = {'MAT': 'materiales', 'MO': 'mano de obra', 'EQ': 'equipos'}

        def pct(valor):
            return format((valor * 100).normalize(), 'f')

        filas = []
        for l in perfil['lineas']:
            if l['tipo'] == 'suma':
                calculo = f"Σ {etiquetas[l['grupo']]}"
                if l['factor'] != 1:
                    calculo += f" × {format(l['factor'].normalize(), 'f')}"
            elif l['tipo'] == 'subtotal':
                calculo = ' + '.join(l['base'])
            else:
                base = ' + '.join(l['base'])
                base = f'({base})' if len(l['base']) > 1 else base
                calculo = (f"{pct(l['pct'])} % sobre el precio de venta de {base}" if l['modo'] == 'sobre_precio'
                           else f"{pct(l['pct'])} % × {base}")
            filas.append({'cod': l['cod'], 'nombre': l['nombre'], 'calculo': calculo, 'nivel': l['nivel'],
                          'total': l['total'], 'seccion': 'insumos' if l['tipo'] == 'suma' else l['nivel']})
        return filas

    def copiar_a(self, empresa):
        """Copia esta plantilla (o perfil) a `empresa` con un nombre libre. Devuelve la copia."""
        nombre, n = self.nombre, 1
        while PerfilCalculo.objects.filter(empresa=empresa, nombre=nombre).exists():
            n += 1
            nombre = f'{self.nombre} ({n})'
        return PerfilCalculo.objects.create(empresa=empresa, nombre=nombre, pais=self.pais, moneda=self.moneda,
                                            datos=self.datos)


class ProyectoAPU(models.Model):
    """Incidencias de un proyecto: el perfil de cálculo base y los ajustes propios (p. ej. Gastos generales 12 %
    en vez de 10 %). Todos los APU del proyecto se calculan con `perfil_efectivo()`; el precio no se guarda."""
    proyecto = models.OneToOneField('proyectos.Proyecto', on_delete=models.CASCADE, related_name='apu')
    perfil = models.ForeignKey(PerfilCalculo, on_delete=models.PROTECT, related_name='proyectos')
    region = models.CharField('Región o ciudad de los precios', max_length=80, blank=True,
                              help_text='Precios vigentes de esa región (con respaldo nacional). Vacío = precios nacionales.')
    ajustes = models.JSONField('Ajustes', blank=True, default=dict,
                               help_text='{código de línea: valor}. Porcentaje (0.12 = 12 %) o factor, según la línea.')

    class Meta:
        verbose_name = 'Incidencias del proyecto'
        verbose_name_plural = 'Incidencias de proyectos'

    def __str__(self):
        return f'{self.proyecto} · {self.perfil.nombre}'

    def datos_efectivos(self):
        """`datos` del perfil base con los ajustes aplicados (sin validar). Un código que ya no existe se ignora."""
        datos = copy.deepcopy(self.perfil.datos)
        for linea in datos.get('lineas', []):
            if linea.get('cod') in self.ajustes:
                clave = 'factor' if linea.get('tipo') == 'suma' else 'pct'
                if linea.get('tipo') in ('suma', 'porcentaje'):
                    linea[clave] = self.ajustes[linea['cod']]
        return datos

    def perfil_efectivo(self):
        """El perfil con los ajustes, validado y listo para `apu_motor.calcular`."""
        return validar_perfil({**self.datos_efectivos(), 'perfil': self.perfil.nombre, 'moneda': self.perfil.moneda})

    def ajustes_huerfanos(self):
        """Códigos con ajuste que el perfil base ya no tiene (o que no admiten ajuste)."""
        validos = {l['cod'] for l in self.perfil.datos.get('lineas', []) if l.get('tipo') in ('suma', 'porcentaje')}
        return sorted(set(self.ajustes) - validos)

    def clean(self):
        try:
            self.perfil_efectivo()
        except PerfilInvalido as e:
            raise ValidationError({'ajustes': str(e)})
