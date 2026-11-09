"""Certificado de pago: rellena la plantilla .xlsx de la empresa (hoja «PL» consolidada + una hoja por persona).

La geometría de la plantilla (filas y columnas) es la de skylog y se mantiene: una planilla de personal de 12
personas y un mes de 30 días, más tres planillas de alimentación (La Paz, Cochabamba, Santa Cruz). Se insertan o
quitan filas según el número real de personas y de días del período."""
import calendar as _cal
import io
from copy import copy
from datetime import date, datetime, time, timedelta

from django.db.models import F
from django.utils import timezone

from cuentas.roles import RolBase
from jor_diario.models import Ausencia, Jornada, NotaCalendario
from jor_empleados.models import ConfigJornadas, Perfil

from .xlsx_util import copiar_estilo as _copiar_estilo, redimensionar as _redimensionar, texto as _texto

T_DAYS = 30           # filas de días en las hojas de persona (10..39)
T_PERSONAS = 12       # filas de personas en PL (14..25) y hojas '1'..'12'
E_FIRST_ROW = 10      # primera fila de datos en la hoja de persona
PL_FIRST_ROW = 14     # primera fila de personas en PL
MAX_DAYS = 31         # columnas de días disponibles en PL (F..AJ)
T_CATERING = {'LPZ': 3, 'CBA': 3, 'SCZ': 6}      # filas de personas por ciudad en la plantilla base
DATE_FMT = 'dd-mm-yyyy'
PRECIO_ALIMENTACION = 25
TRABAJADAS = {Ausencia.Tipo.PERMISO, Ausencia.Tipo.VACACION}     # cuentan como día trabajado en la planilla de personal
ROLES_CERTIFICADO = (RolBase.COORDINADOR, RolBase.ESPECIALISTA, RolBase.MIEMBRO)


class CertificadoError(Exception):
    pass


def _fecha(ws, row, col, value):
    cell = ws.cell(row=row, column=col)
    cell.value = value
    cell.number_format = DATE_FMT


def _celda_dia(ws, row, d, value):
    """Celda del día d (1..31) en PL. La columna del día 31 (AJ) viene vacía: hereda el estilo del día 30."""
    col = 5 + d
    if d == 31:
        ws.cell(row=row, column=col)._style = copy(ws.cell(row=row, column=col - 1)._style)
    ws.cell(row=row, column=col).value = value        # asignación directa: cell(value=None) no limpia


def _hoja_persona(ws, item, perfil, fechas, jornadas, obs_ausencias, obs_notas):
    ndias = len(fechas)
    _redimensionar(ws, E_FIRST_ROW, T_DAYS, ndias, max_col=8)
    ws['B4'] = item
    _texto(ws, 5, 2, perfil.nombre)
    _texto(ws, 6, 2, perfil.cargo_completo)
    ws['B7'] = float(perfil.haber_basico or 0)
    for i, dia in enumerate(fechas):
        r = E_FIRST_ROW + i
        j = jornadas.get((perfil.pk, dia))
        _fecha(ws, r, 1, dia)
        ws.cell(row=r, column=2, value=f'=+A{r}')
        if j:
            ini = timezone.localtime(j.inicio)
            fin = timezone.localtime(j.fin) if j.fin else None
            entrada, salida, refrigerio = time(ini.hour, ini.minute), (fin and time(fin.hour, fin.minute)), 1
        else:
            entrada = salida = refrigerio = None
        ws.cell(row=r, column=3).value = entrada
        ws.cell(row=r, column=4).value = salida
        ws.cell(row=r, column=5).value = refrigerio
        ws.cell(row=r, column=6, value=f'=+(D{r}-C{r})*24-E{r}')
        ws.cell(row=r, column=7, value=f'=+IF(C{r}>0.333333333333333,+(C{r}-0.333333333333333)*24*60,"0")')
        marcas = ['No cerró jornada'] if (j and j.cierre_auto) else []
        obs = ' · '.join(marcas + obs_ausencias.get((perfil.pk, dia), []) + obs_notas.get(dia, []))
        _texto(ws, r, 8, obs)
    ultima = E_FIRST_ROW + ndias - 1
    ws.cell(row=ultima + 1, column=3, value=f'=+COUNT(C{E_FIRST_ROW}:C{ultima})')
    ws.cell(row=ultima + 2, column=3, value=f'=SUM(F{E_FIRST_ROW}:F{ultima})')
    ws.cell(row=ultima + 3, column=3, value=f'=SUM(G{E_FIRST_ROW}:G{ultima})')


def _hoja_pl(ws, perfiles, fechas, valor_periodo, tipos_ausencia, config):
    n = len(perfiles)
    ndias = len(fechas)
    primero = PL_FIRST_ROW
    ws.cell(row=1, column=39).value = timezone.localdate()
    ws.cell(row=1, column=39).number_format = DATE_FMT
    ws['Y3'] = valor_periodo

    def cabecera_dias(row):
        for d in range(1, MAX_DAYS + 1):
            _celda_dia(ws, row, d, fechas[d - 1].day if d <= ndias else None)

    def fila_persona(r, item, perfil, pu=None, modo='personal'):
        ws.cell(row=r, column=1, value=item)
        _texto(ws, r, 2, perfil.nombre)
        _texto(ws, r, 3, perfil.cargo_completo)
        _fecha(ws, r, 4, fechas[0])
        ws.cell(row=r, column=5, value=float(perfil.haber_basico or 0) if pu is None else pu)
        for d in range(1, MAX_DAYS + 1):
            v = None
            if d <= ndias:
                tipos = tipos_ausencia.get((perfil.pk, fechas[d - 1]), set())
                formula = f'=+IF(\'{item}\'!F{E_FIRST_ROW + d - 1}>1,"SI","NO")'
                if modo == 'alimentacion':
                    v = 'NO' if tipos else formula                     # cualquier ausencia excluye el día
                else:
                    v = 'SI' if (tipos & TRABAJADAS) else formula      # permiso/vacación cuentan como trabajado
            _celda_dia(ws, r, d, v)
        ws.cell(row=r, column=37, value=f'=+COUNTIF(F{r}:AJ{r},"SI")')

    # Planilla de personal (plantilla: filas 14..25, subtotal 26)
    _redimensionar(ws, primero, T_PERSONAS, n, max_col=39)
    cabecera_dias(primero - 1)
    for idx, p in enumerate(perfiles, start=1):
        r = primero + idx - 1
        fila_persona(r, idx, p)
        ws.cell(row=r, column=38, value=f'=+AK{r}/$AB$5*E{r}')
        ws.cell(row=r, column=39, value=f'=+AL{r}/{config.tipo_cambio_certificado}')
    pl_sub = primero + n
    ws.cell(row=pl_sub, column=39, value=f'=SUM(AM{primero}:AM{pl_sub - 1})' if n else 0)

    desplazo = n - T_PERSONAS

    # Pasajes y viáticos / equipos (plantilla: filas 32..37)
    t_first = 32 + desplazo
    base = fechas[0]
    dim = _cal.monthrange(base.year, base.month)[1]
    ida, regreso = date(base.year, base.month, min(22, dim)), date(base.year, base.month, min(23, dim))
    for off in (1, 4):
        _fecha(ws, t_first + off, 4, ida)
        _fecha(ws, t_first + off, 5, regreso)
    for i in range(5):
        r = t_first + i
        ws.cell(row=r, column=14, value=f'=+F{r}*H{r}' if i == 4 else f'=+K{r}*H{r}')
        ws.cell(row=r, column=16, value=f'=+N{r}*1.25')
    viaticos_sub = t_first + 5
    ws.cell(row=viaticos_sub, column=16, value=f'=SUM(P{t_first}:S{t_first + 4})')
    for off in (0, 2):
        r = t_first + off
        ws.cell(row=r, column=39, value=f'=+AL{r}*AJ{r}')
    equipos_sub = t_first + 4
    ws.cell(row=equipos_sub, column=39, value=f'=SUM(AM{t_first}:AM{t_first + 3})')

    # Planillas de alimentación por ciudad
    def alimentacion(titulo_r, antiguas, personas_ciudad):
        primera = titulo_r + 4
        _redimensionar(ws, primera, antiguas, len(personas_ciudad), max_col=39)
        cabecera_dias(titulo_r + 3)
        for i, (item, p) in enumerate(personas_ciudad):
            r = primera + i
            fila_persona(r, item, p, pu=PRECIO_ALIMENTACION, modo='alimentacion')
            ws.cell(row=r, column=38, value=f'=+AK{r}*E{r}')
            ws.cell(row=r, column=39, value=f'=+AL{r}*$AM${titulo_r}')
        sub = primera + len(personas_ciudad)
        ws.cell(row=sub, column=39, value=f'=SUM(AM{primera}:AM{sub - 1})' if personas_ciudad else 0)
        return sub

    por_ciudad = {c: [(i, p) for i, p in enumerate(perfiles, start=1) if p.ciudad_catering == c] for c in T_CATERING}
    lpz = alimentacion(39 + desplazo, T_CATERING['LPZ'], por_ciudad['LPZ'])
    cba = alimentacion(lpz + 2, T_CATERING['CBA'], por_ciudad['CBA'])
    scz = alimentacion(cba + 2, T_CATERING['SCZ'], por_ciudad['SCZ'])

    total = scz + 2
    ws.cell(row=total, column=38, value=f'=+AM{pl_sub}+P{viaticos_sub}+AM{equipos_sub}+AM{lpz}+AM{cba}+AM{scz}')
    ws.cell(row=total + 2, column=23, value=f'="Son : " & TEXT(AL{total},"#,##0.00") & " {config.moneda_certificado}"')


def perfiles_certificado(empresa):
    Perfil.asegurar_de(empresa)
    return list(Perfil.objects.filter(membresia__empresa=empresa, membresia__activa=True, activo=True,
                                      membresia__rol__rol_base__in=ROLES_CERTIFICADO)
                .select_related('membresia__user', 'membresia__rol')
                .order_by(F('numero_item').asc(nulls_last=True), 'membresia__user__first_name', 'membresia__user__email'))


def periodo_certificado(modo, anio=None, mes=None, desde=None, hasta=None, hoy=None):
    """(fechas, valor de la celda PERIODO, etiqueta del archivo). El rango se limita a 31 días."""
    hoy = hoy or timezone.localdate()
    if modo == 'range' and desde and hasta:
        hasta = max(hasta, desde)
        if (hasta - desde).days >= MAX_DAYS:
            hasta = desde + timedelta(days=MAX_DAYS - 1)
        valor = f'{desde:%d-%m-%Y} — {hasta:%d-%m-%Y}'
        etiqueta = f'{desde:%d-%m-%Y}__{hasta:%d-%m-%Y}'
    else:
        anio, mes = anio or hoy.year, mes or hoy.month
        if not 1 <= mes <= 12:
            anio, mes = hoy.year, hoy.month
        desde, hasta = date(anio, mes, 1), date(anio, mes, _cal.monthrange(anio, mes)[1])
        valor, etiqueta = desde, f'{anio}-{mes:02d}'
    return [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)], valor, etiqueta


def _leer_plantilla(config):
    import openpyxl
    try:
        with config.plantilla_certificado.open('rb') as f:
            return openpyxl.load_workbook(io.BytesIO(f.read()))
    except Exception:
        raise CertificadoError('No se pudo leer la plantilla del reporte.')


def generar(empresa, fechas, valor_periodo, usuario=None):
    """Bytes del .xlsx del período. Tres caminos según la plantilla de la empresa:
    · sin plantilla subida → la plantilla base con variables (`plantilla_base`);
    · plantilla con variables `{{ … }}` → el motor (`plantilla_motor`);
    · plantilla sin variables (formato skylog: hojas «PL» y «1»…) → el generador clásico de geometría fija."""
    from . import plantilla_base, plantilla_motor, variables
    config = ConfigJornadas.de(empresa)
    wb = _leer_plantilla(config) if config.plantilla_certificado else plantilla_base.construir()
    if plantilla_motor.tiene_variables(wb):
        errores = plantilla_motor.validar(wb)
        if errores:
            raise CertificadoError('La plantilla tiene errores: ' + '; '.join(errores[:5]))
        plantilla_motor.renderizar(wb, variables.contexto(empresa, fechas, usuario))
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    return _generar_clasico(empresa, fechas, valor_periodo, wb, config)


def _generar_clasico(empresa, fechas, valor_periodo, wb, config):
    perfiles = perfiles_certificado(empresa)
    ini = timezone.make_aware(datetime.combine(fechas[0], time.min))
    fin = timezone.make_aware(datetime.combine(fechas[-1], time.max))

    jornadas = {}
    for j in Jornada.objects.computables().filter(perfil__in=perfiles, empresa=empresa, inicio__range=(ini, fin),
                                    estado__in=[Jornada.Estado.COMPLETADA, Jornada.Estado.INCOMPLETA]):
        jornadas[(j.perfil_id, timezone.localtime(j.inicio).date())] = j

    obs_ausencias, tipos_ausencia = {}, {}
    for a in Ausencia.objects.filter(empresa=empresa, perfil__in=perfiles, estado=Ausencia.Estado.APROBADA,
                                     desde__lte=fechas[-1], hasta__gte=fechas[0]):
        d = max(a.desde, fechas[0])
        while d <= min(a.hasta, fechas[-1]):
            texto = (a.nota or '') if a.tipo == Ausencia.Tipo.OTRO else a.get_tipo_display() + (f' ({a.nota})' if a.nota else '')
            if texto:
                obs_ausencias.setdefault((a.perfil_id, d), []).append(texto)
            tipos_ausencia.setdefault((a.perfil_id, d), set()).add(a.tipo)
            d += timedelta(days=1)

    obs_notas = {}
    for nota in NotaCalendario.objects.filter(empresa=empresa, fecha__range=(fechas[0], fechas[-1])):
        obs_notas.setdefault(nota.fecha, []).append(f'{nota.get_tipo_display()}: {nota.texto}')

    n = len(perfiles)
    for s in range(n + 1, T_PERSONAS + 1):
        if str(s) in wb.sheetnames:
            wb.remove(wb[str(s)])
    for s in range(T_PERSONAS + 1, n + 1):
        wb.copy_worksheet(wb['1']).title = str(s)

    _hoja_pl(wb['PL'], perfiles, fechas, valor_periodo, tipos_ausencia, config)
    for idx, p in enumerate(perfiles, start=1):
        _hoja_persona(wb[str(idx)], idx, p, fechas, jornadas, obs_ausencias, obs_notas)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
