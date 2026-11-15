"""Cálculo de un APU: suma por grupo cantidad × (1 + desperdicio) × precio vigente, resuelve sub-ítems de forma
recursiva y aplica `apu_motor.calcular` con el perfil efectivo del proyecto. El precio no se guarda: se calcula al vuelo."""
from dataclasses import dataclass, field
from decimal import Decimal

from apu_motor import calcular

from .models import ProyectoAPU, Tipo

CERO = Decimal(0)
UNO = Decimal(1)


@dataclass
class Fila:
    """Una línea de la composición ya resuelta: un insumo (o un sub-ítem) con su costo por unidad del APU."""
    linea: object
    nombre: str
    unidad: str
    tipo: str            # MAT / MO / EQ, o '' si es un sub-ítem
    cantidad: Decimal
    desperdicio_pct: Decimal
    precio: Decimal | None
    moneda: str
    costo: Decimal
    sin_precio: bool = False
    subitem: bool = False
    estimado: bool = False
    pct: Decimal = CERO          # % del costo directo (se calcula en Analisis.secciones)


@dataclass
class Analisis:
    filas: list = field(default_factory=list)
    grupos: dict = field(default_factory=dict)      # {'MAT': Decimal, 'MO': ..., 'EQ': ...}
    sin_precio: list = field(default_factory=list)  # insumos sin precio vigente
    resultado: object = None                        # apu_motor.Resultado
    perfil: dict = None
    moneda: str = ''

    @property
    def total(self):
        return self.resultado.total if self.resultado else None

    @property
    def n_estimados(self):
        return sum(1 for f in self.filas if f.estimado)

    @property
    def directo(self):
        """Costo directo: la suma de todas las líneas de la composición, antes de los recargos del perfil."""
        return sum((f.costo for f in self.filas), CERO)

    @property
    def secciones(self):
        """La composición agrupada para mostrarla: materiales, mano de obra, equipos y sub-análisis, cada uno con su
        subtotal y su % del costo directo (y el % de cada fila). Solo las secciones que tienen filas."""
        directo = self.directo
        definicion = [('MAT', 'Materiales', 'layers'), ('MO', 'Mano de obra', 'hardhat'), ('EQ', 'Equipos', 'settings'),
                      ('SUB', 'Sub-análisis', 'list')]
        salida = []
        for clave, nombre, icono in definicion:
            filas = [f for f in self.filas if (f.subitem and clave == 'SUB') or (not f.subitem and f.tipo == clave)]
            if not filas:
                continue
            for f in filas:
                f.pct = (f.costo / directo * 100) if directo else CERO
            subtotal = sum((f.costo for f in filas), CERO)
            moneda = self.moneda or next((f.moneda for f in filas if f.moneda), '')
            salida.append({'clave': clave, 'nombre': nombre, 'icono': icono, 'filas': filas, 'subtotal': subtotal, 'moneda': moneda,
                           'pct': (subtotal / directo * 100) if directo else CERO})
        return salida


def _proyecto_apu(proyecto):
    return ProyectoAPU.objects.select_related('perfil').filter(proyecto=proyecto).first() if proyecto else None


def perfil_del_proyecto(proyecto):
    """Perfil efectivo del proyecto (base + ajustes) o None si el proyecto aún no está habilitado para APU."""
    pa = _proyecto_apu(proyecto)
    return pa.perfil_efectivo() if pa else None


def _sumar(item, region, fecha, acumulado, filas, sin_precio, factor=UNO, vistos=()):
    if item.pk in vistos:
        return
    for linea in item.lineas.select_related('insumo', 'subitem').all():
        cantidad = linea.cantidad * factor
        if linea.subitem_id:
            sub = linea.subitem
            local = {t: CERO for t in Tipo.values}
            _sumar(sub, region, fecha, local, [], sin_precio, cantidad * (UNO + linea.desperdicio_pct / 100),
                   vistos + (item.pk,))
            for t, v in local.items():
                acumulado[t] += v
            if factor == UNO:
                filas.append(Fila(linea, str(sub), sub.unidad, '', linea.cantidad, linea.desperdicio_pct, None, '',
                                  sum(local.values(), CERO), subitem=True))
            continue
        insumo = linea.insumo
        precio = insumo.precio_vigente(region, fecha)
        efectiva = cantidad * (UNO + linea.desperdicio_pct / 100)
        if precio is None:
            costo, valor, moneda = CERO, None, ''
            if insumo not in sin_precio:
                sin_precio.append(insumo)
        else:
            valor, moneda = precio.precio, precio.moneda
            costo = efectiva * valor
        acumulado[insumo.tipo] += costo
        if factor == UNO:
            filas.append(Fila(linea, insumo.descripcion, insumo.unidad, insumo.tipo, linea.cantidad,
                              linea.desperdicio_pct, valor, moneda, costo, sin_precio=precio is None,
                              estimado=bool(precio and precio.estimado)))


def analizar(item, region=None, fecha=None, perfil=None):
    """Analiza `item`. Por defecto usa el perfil efectivo de su proyecto y la región de precios del proyecto (`region`
    la reemplaza si se indica; vacía = nacional). `perfil` (ya validado) solo sirve para previsualizar incidencias."""
    pa = _proyecto_apu(item.proyecto)
    if perfil is None and pa:
        perfil = pa.perfil_efectivo()
    if region is None:
        region = pa.region if pa else ''
    acumulado = {t: CERO for t in Tipo.values}
    filas, sin_precio = [], []
    _sumar(item, region or '', fecha, acumulado, filas, sin_precio)
    analisis = Analisis(filas=filas, grupos=acumulado, sin_precio=sin_precio, perfil=perfil,
                        moneda=perfil['moneda'] if perfil else '')
    if perfil:
        analisis.resultado = calcular(perfil, acumulado)
    return analisis


def grupos_de(item, region=None, fecha=None, factor=UNO):
    """Totales por grupo de UNA unidad de `item` (× `factor`) y los insumos sin precio. Sirve para los sub-ítems."""
    acumulado = {t: CERO for t in Tipo.values}
    sin_precio = []
    _sumar(item, region or '', fecha, acumulado, [], sin_precio, factor)
    return acumulado, sin_precio


def desglose(perfil, resultado):
    """Las líneas del perfil con su valor calculado, para mostrar el desglose del precio unitario."""
    if not perfil or not resultado:
        return []
    return [{'cod': l['cod'], 'nombre': l['nombre'], 'tipo': l['tipo'], 'nivel': l['nivel'], 'total': l['total'],
             'valor': resultado.lineas.get(l['cod'])} for l in perfil['lineas'] if l['cod'] in resultado.lineas]
