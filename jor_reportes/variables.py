"""Variables disponibles en las plantillas del reporte de personal y construcción de su contexto.

`CATALOGO` es la fuente única: valida las plantillas subidas, genera la hoja `_Variables` de la plantilla base y la
tabla de la pantalla de Configuración. Un nombre con `N` (p. ej. `persona.horas.N`) vale para N = 1…31."""
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from jor_diario.models import Jornada, NotaCalendario
from jor_empleados.models import CIUDADES, ConfigJornadas

from . import periodo as per, servicios

MAX_DIAS = 31

# Un espacio `alimentacion_<ciudad>` por cada ciudad de alimentación: las mismas personas y campos que `persona.*`,
# pero solo las de esa ciudad (una fila por persona, para las planillas de alimentación por ciudad).
ESPACIOS_ALIMENTACION = {f'alimentacion_{c.lower()}': (c, nombre) for c, nombre in CIUDADES if c != 'NONE'}

G_PERSONA = 'Persona (una fila por persona; o una hoja por persona si el título de la hoja la usa)'
G_DIA = 'Día (una fila por día, dentro de una hoja por persona)'
G_ALIMENTACION = 'Alimentación por ciudad (una fila por persona de esa ciudad)'
G_PROYECTO = 'Proyecto (una fila por proyecto; globales o, en una hoja por persona, de esa persona)'

# (grupo, nombre, descripción, ejemplo)
CATALOGO = [
    ('General', 'empresa.nombre', 'Nombre de la empresa', 'Embol S.A.'),
    ('General', 'reporte.nombre', 'Nombre que la empresa da a este reporte', 'Reporte de personal'),
    ('General', 'periodo.etiqueta', 'Período en texto', 'Octubre 2026'),
    ('General', 'periodo.desde', 'Primer día del período', '01-10-2026'),
    ('General', 'periodo.hasta', 'Último día del período', '31-10-2026'),
    ('General', 'periodo.dias', 'Cantidad de días del período', '31'),
    ('General', 'periodo.dias_habiles', 'Días hábiles: lunes a viernes sin feriados del calendario', '22'),
    ('General', 'periodo.dia.N', 'Número de día de la columna N (vacío si N supera el período): cabecera de la matriz', '1 … 31'),
    ('General', 'reporte.moneda', 'Moneda del reporte (Configuración)', 'Bolivianos'),
    ('General', 'reporte.tipo_cambio', 'Tipo de cambio del reporte (Configuración)', '0.4613'),
    ('General', 'generado.fecha', 'Fecha y hora en que se generó', '07-11-2026 17:30'),
    ('General', 'generado.por', 'Quién lo generó', 'Ana Pérez'),
    ('Totales', 'total.personas', 'Cantidad de personas del reporte', '12'),
    ('Totales', 'total.dias_trabajados', 'Suma de días trabajados', '240'),
    ('Totales', 'total.horas_netas', 'Suma de horas netas (número, sin el refrigerio)', '1820.5'),
    ('Totales', 'total.atraso_min', 'Suma de minutos de atraso', '95'),
    ('Totales', 'total.ausencias', 'Suma de días de ausencia aprobada', '8'),
    ('Totales', 'total.sin_cerrar', 'Suma de jornadas que no se cerraron', '3'),
    (G_PERSONA, 'persona.item', 'Número de orden', '1'),
    (G_PERSONA, 'persona.nombre', 'Nombre', 'Ana Pérez'),
    (G_PERSONA, 'persona.cargo', 'Cargo de la empresa', 'Supervisor'),
    (G_PERSONA, 'persona.puesto', 'Especialidad o detalle del cargo', 'Civil'),
    (G_PERSONA, 'persona.cargo_completo', '«Cargo - Puesto»', 'Supervisor - Civil'),
    (G_PERSONA, 'persona.haber_basico', 'Haber básico', '9500'),
    (G_PERSONA, 'persona.ciudad', 'Ciudad de alimentación (vacío si no tiene)', 'La Paz'),
    (G_PERSONA, 'persona.email', 'Correo', 'ana@empresa.com'),
    (G_PERSONA, 'persona.dias_trabajados', 'Días con jornada', '22'),
    (G_PERSONA, 'persona.horas_netas', 'Horas netas del período (número)', '176.5'),
    (G_PERSONA, 'persona.horas_netas_hhmm', 'Horas netas como HH:MM', '176:30'),
    (G_PERSONA, 'persona.atraso_min', 'Minutos de atraso', '15'),
    (G_PERSONA, 'persona.ausencias', 'Días de ausencia aprobada', '1'),
    (G_PERSONA, 'persona.sin_cerrar', 'Jornadas que no se cerraron', '0'),
    (G_PERSONA, 'persona.horas.N', 'Horas netas del día N (vacío si no trabajó): matriz persona × día', '8.5'),
    (G_PERSONA, 'persona.pagado.N', 'SI / NO: día pagado (hubo jornada, o permiso/vacación aprobados)', 'SI'),
    (G_PERSONA, 'persona.alimentacion.N', 'SI / NO: día con alimentación (hubo jornada y ninguna ausencia aprobada)', 'SI'),
    (G_PERSONA, 'persona.dias_pagados', 'Días pagados', '22'),
    (G_PERSONA, 'persona.dias_alimentacion', 'Días con alimentación', '20'),
    (G_PERSONA, 'persona.asistio.N', 'SI / NO: si hubo jornada el día N', 'SI'),
    (G_DIA, 'dia.fecha', 'Fecha', '05-10-2026'),
    (G_DIA, 'dia.dia_semana', 'Día de la semana', 'lunes'),
    (G_DIA, 'dia.ingreso', 'Hora de ingreso', '08:10'),
    (G_DIA, 'dia.salida', 'Hora de salida', '17:00'),
    (G_DIA, 'dia.ingreso_hora', 'Hora de ingreso como hora de Excel (para fórmulas)', '08:10'),
    (G_DIA, 'dia.salida_hora', 'Hora de salida como hora de Excel (para fórmulas)', '17:00'),
    (G_DIA, 'dia.refrigerio', 'Horas de refrigerio: 1 si hubo jornada, vacío si no', '1'),
    (G_DIA, 'dia.horas_netas', 'Horas netas del día (número)', '7.83'),
    (G_DIA, 'dia.horas_netas_hhmm', 'Horas netas como HH:MM', '07:50'),
    (G_DIA, 'dia.atraso_min', 'Minutos de atraso del día', '10'),
    (G_DIA, 'dia.observaciones', 'Ausencias, notas del calendario y «No cerró jornada»', 'Permiso (trámite)'),
    (G_DIA, 'dia.sin_cerrar', 'SI si la jornada no se cerró, vacío si no', ''),
    (G_DIA, 'dia.fin_semana', 'SI si es sábado o domingo, vacío si no', 'SI'),
    (G_ALIMENTACION, 'alimentacion_lpz.*', 'Mismos campos que persona.* (p. ej. {{ alimentacion_lpz.nombre }}), solo las personas con alimentación en La Paz', 'alimentacion_lpz.nombre'),
    (G_ALIMENTACION, 'alimentacion_cba.*', 'Mismos campos que persona.* (p. ej. {{ alimentacion_cba.nombre }}), solo las personas con alimentación en Cochabamba', 'alimentacion_cba.nombre'),
    (G_ALIMENTACION, 'alimentacion_scz.*', 'Mismos campos que persona.* (p. ej. {{ alimentacion_scz.nombre }}), solo las personas con alimentación en Santa Cruz', 'alimentacion_scz.nombre'),
    (G_PROYECTO, 'proyecto.nombre', 'Nombre del proyecto («Sin proyecto» si la jornada no tiene)', 'Pozo PPA09'),
    (G_PROYECTO, 'proyecto.codigo', 'Código del proyecto', 'CMT.CBB.MQ.2614A'),
    (G_PROYECTO, 'proyecto.jornadas', 'Jornadas del período', '12'),
    (G_PROYECTO, 'proyecto.horas', 'Horas de las jornadas (número; no descuenta el refrigerio)', '96.5'),
    (G_PROYECTO, 'proyecto.horas_hhmm', 'Horas como HH:MM', '96:30'),
]


def nombres_validos():
    """Todos los nombres que una plantilla puede usar, con `N` expandido a 1…31."""
    nombres, de_persona = set(), []
    for _, nombre, _, _ in CATALOGO:
        if nombre.endswith('.*'):                     # espacio completo (alimentacion_*): se expande abajo
            continue
        if nombre.endswith('.N'):
            nombres.update(f'{nombre[:-1]}{n}' for n in range(1, MAX_DIAS + 1))
        else:
            nombres.add(nombre)
        if nombre.startswith('persona.'):
            de_persona.append(nombre.split('.', 1)[1])
    campos = [c2 for c in de_persona
              for c2 in ([f'{c[:-1]}{n}' for n in range(1, MAX_DIAS + 1)] if c.endswith('.N') else [c])]
    for espacio in ESPACIOS_ALIMENTACION:
        nombres.update(f'{espacio}.{c}' for c in campos)
    return nombres


def catalogo_agrupado():
    """[(grupo, [(nombre, descripción, ejemplo), …]), …] en el orden del catálogo (para mostrarlo)."""
    grupos = {}
    for grupo, nombre, descripcion, ejemplo in CATALOGO:
        grupos.setdefault(grupo, []).append((nombre, descripcion, ejemplo))
    return list(grupos.items())


def _horas(minutos):
    return None if minutos is None else round(minutos / 60, 2)


def _etiqueta_periodo(fechas):
    d, h = fechas[0], fechas[-1]
    mes_completo = d.day == 1 and h.month == d.month and h.year == d.year and (h + timedelta(days=1)).day == 1
    if mes_completo:
        return f'{per.MESES[d.month - 1].capitalize()} {d.year}'
    return f'{d:%d/%m/%Y} — {h:%d/%m/%Y}'


def _proyectos_por_persona(empresa, perfiles, fechas):
    ini = timezone.make_aware(datetime.combine(fechas[0], time.min))
    fin = timezone.make_aware(datetime.combine(fechas[-1], time.max))
    filas = (Jornada.objects.computables()
             .filter(empresa=empresa, perfil__in=perfiles, inicio__range=(ini, fin),
                     estado__in=[Jornada.Estado.COMPLETADA, Jornada.Estado.INCOMPLETA])
             .exclude(duracion_min=None)
             .values('perfil_id', 'proyecto__nombre', 'proyecto__codigo')
             .annotate(n=Count('id'), minutos=Sum('duracion_min')))
    por_persona = defaultdict(list)
    for f in filas:
        por_persona[f['perfil_id']].append(_proyecto(f['proyecto__nombre'], f['proyecto__codigo'], f['n'], f['minutos'] or 0))
    for lista in por_persona.values():
        lista.sort(key=lambda p: (-p['_min'], p['nombre'].lower()))
    return por_persona


def _proyecto(nombre, codigo, jornadas, minutos):
    return {'nombre': nombre or 'Sin proyecto', 'codigo': codigo or '', 'jornadas': jornadas, 'horas': _horas(minutos),
            'horas_hhmm': servicios.hhmm(minutos), '_min': minutos}


def contexto(empresa, fechas, usuario=None):
    """Datos para renderizar una plantilla: todo lo que `CATALOGO` promete, ya calculado."""
    from .certificado import TRABAJADAS, perfiles_certificado
    config = ConfigJornadas.de(empresa)
    perfiles = perfiles_certificado(empresa)
    orden = {p.membresia_id: i for i, p in enumerate(perfiles)}
    periodo = per.Periodo('range', fechas[0], fechas[-1], _etiqueta_periodo(fechas))
    datos = sorted(servicios.asistencia(empresa, periodo, membresia_ids=list(orden)), key=lambda d: orden[d['membresia_id']])
    proyectos_de = _proyectos_por_persona(empresa, perfiles, fechas)

    personas, globales = [], defaultdict(lambda: [None, 0, 0])
    for item, d in enumerate(datos, start=1):
        perfil = d['perfil']
        horas, asistio, pagado, alimentacion, dias = {}, {}, {}, {}, []
        for i in range(MAX_DIAS):
            fila = d['filas'][i] if i < len(d['filas']) else None
            horas[str(i + 1)] = _horas(fila['neto_min']) if fila else None
            asistio[str(i + 1)] = ('SI' if fila['neto_min'] is not None else 'NO') if fila else None
            if fila:
                trabajo = fila['neto_min'] is not None
                pagado[str(i + 1)] = 'SI' if trabajo or fila['tipos_ausencia'] & TRABAJADAS else 'NO'
                alimentacion[str(i + 1)] = 'SI' if trabajo and not fila['tipos_ausencia'] else 'NO'      # toda ausencia excluye el día
                obs = (['No cerró jornada'] if fila['no_cerro'] else []) + fila['comentarios']
                dias.append({'fecha': fila['fecha'], 'dia_semana': fila['dia'], 'ingreso': fila['ingreso'] or None,
                             'salida': fila['salida'] or None, 'ingreso_hora': fila['ingreso_t'], 'salida_hora': fila['salida_t'],
                             'refrigerio': 1 if trabajo else None, 'horas_netas': horas[str(i + 1)],
                             'horas_netas_hhmm': fila['horas'] or None, 'atraso_min': fila['atraso_min'],
                             'observaciones': ' · '.join(obs), 'sin_cerrar': 'SI' if fila['no_cerro'] else '',
                             'fin_semana': 'SI' if fila['fin_semana'] else ''})
        proyectos = proyectos_de.get(perfil.pk, [])
        for p in proyectos:
            g = globales[(p['nombre'], p['codigo'])]
            g[1] += p['jornadas']
            g[2] += p['_min']
        personas.append({
            'item': item, 'nombre': perfil.nombre, 'cargo': perfil.membresia.rol.nombre, 'puesto': perfil.cargo,
            'cargo_completo': perfil.cargo_completo, 'haber_basico': float(perfil.haber_basico or 0),
            'ciudad': perfil.get_ciudad_catering_display() if perfil.ciudad_catering != 'NONE' else '',
            '_ciudad': perfil.ciudad_catering, 'email': perfil.membresia.user.email,
            'dias_trabajados': d['dias'], 'horas_netas': _horas(d['neto_min']), 'horas_netas_hhmm': d['horas'],
            'atraso_min': d['atraso_min'], 'ausencias': d['ausencias'], 'sin_cerrar': d['no_cerro'],
            'horas': horas, 'asistio': asistio, 'pagado': pagado, 'alimentacion': alimentacion,
            'dias_pagados': sum(v == 'SI' for v in pagado.values()),
            'dias_alimentacion': sum(v == 'SI' for v in alimentacion.values()),
            'dias': dias, 'proyectos': proyectos})

    lista_proyectos = sorted((_proyecto(n, c, j, m) for (n, c), (_, j, m) in globales.items()),
                             key=lambda p: (-p['_min'], p['nombre'].lower()))
    feriados = set(NotaCalendario.objects.filter(empresa=empresa, tipo=NotaCalendario.Tipo.FERIADO,
                                                 fecha__range=(fechas[0], fechas[-1])).values_list('fecha', flat=True))
    habiles = sum(1 for f in fechas if f.weekday() < 5 and f not in feriados)
    return {
        'empresa': {'nombre': empresa.nombre},
        'reporte': {'nombre': empresa.nombre_certificado, 'moneda': config.moneda_certificado,
                    'tipo_cambio': config.tipo_cambio_certificado},
        'periodo': {'etiqueta': periodo.etiqueta, 'desde': fechas[0], 'hasta': fechas[-1], 'dias': len(fechas),
                    'dias_habiles': habiles,
                    'dia': {str(i + 1): (fechas[i].day if i < len(fechas) else None) for i in range(MAX_DIAS)}},
        'generado': {'fecha': timezone.localtime().replace(tzinfo=None, microsecond=0, second=0),
                     'por': str(usuario) if usuario else ''},
        'total': {'personas': len(personas), 'dias_trabajados': sum(p['dias_trabajados'] for p in personas),
                  'horas_netas': round(sum(p['horas_netas'] or 0 for p in personas), 2),
                  'atraso_min': sum(p['atraso_min'] for p in personas), 'ausencias': sum(p['ausencias'] for p in personas),
                  'sin_cerrar': sum(p['sin_cerrar'] for p in personas)},
        'personas': personas, 'proyectos': lista_proyectos,
        **{espacio: [p for p in personas if p['_ciudad'] == ciudad] for espacio, (ciudad, _) in ESPACIOS_ALIMENTACION.items()},
    }
