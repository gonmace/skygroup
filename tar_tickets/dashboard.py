"""Datos del dashboard de Tareas: KPIs con comparación, estado, prioridad, carga, tiempos y listas de seguimiento
(vencidos, próximos a vencer, por aprobar, actividad reciente). Siempre acotado a la empresa."""
from datetime import timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import TruncWeek
from django.urls import reverse
from django.utils import timezone

from .models import Asignacion, Evento, Ticket

E = Ticket.Estado
DIAS_PROXIMOS = 7
LIMITE = 6

# Clases completas (Tailwind las detecta al escanear este archivo).
FILL = {'neutral': 'fill-neutral/50', 'info': 'fill-info', 'warning': 'fill-warning', 'success': 'fill-success',
        'error': 'fill-error', 'ghost': 'fill-base-content/25'}
BG = {'neutral': 'bg-base-content/40', 'info': 'bg-info', 'warning': 'bg-warning', 'success': 'bg-success',
      'error': 'bg-error', 'ghost': 'bg-base-content/25'}


def con_porcentaje(items):
    """Agrega 'pct' (0-100) a cada fila según su 'count' relativo al mayor de la lista."""
    tope = max((i['count'] for i in items), default=0) or 1
    for i in items:
        i['pct'] = round(100 * i['count'] / tope)
    return items


def _delta(actual, previo):
    return round((actual - previo) * 100 / previo) if previo else None


def _nombre(first, last, email):
    return f'{first} {last}'.strip() or email


def _item(t, hoy):
    return {
        'pk': t.pk, 'clave': t.clave, 'titulo': t.titulo, 'url': reverse('tar_tickets:detalle', args=[t.pk]),
        'proyecto': t.proyecto.nombre if t.proyecto_id else '', 'vence': t.vence,
        'dias': (hoy - t.vence).days if t.vence else None,   # >0 atraso, <0 días que faltan
        'prioridad': t.get_prioridad_display(), 'color_prioridad': t.color_prioridad,
        'estado': t.get_estado_display(),
    }


def calcular(empresa):
    from .views import _fmt_delta
    hoy = timezone.localdate()
    hace30, hace60 = hoy - timedelta(days=30), hoy - timedelta(days=60)
    activos = Ticket.objects.filter(empresa=empresa, archivado_en__isnull=True, dividido_en__isnull=True)
    abiertos = activos.exclude(estado=E.CONCLUIDO)
    por_estado = {r['estado']: r['n'] for r in activos.values('estado').annotate(n=Count('id'))}

    vencidos_qs = abiertos.filter(vence__lt=hoy)
    proximos_qs = abiertos.filter(vence__gte=hoy, vence__lte=hoy + timedelta(days=DIAS_PROXIMOS))
    por_aprobar_qs = activos.filter(pk__in=Asignacion.objects.filter(
        tipo=Asignacion.Tipo.EJECUTOR, estado=E.CONCLUIDO, aprobado_en__isnull=True, ticket__empresa=empresa,
    ).values('ticket_id'))
    concluidos_30 = activos.filter(estado=E.CONCLUIDO, cerrado_en__date__gt=hace30).count()
    concluidos_prev = activos.filter(estado=E.CONCLUIDO, cerrado_en__date__gt=hace60,
                                     cerrado_en__date__lte=hace30).count()
    creados_30 = activos.filter(creado__date__gt=hace30).count()
    creados_prev = activos.filter(creado__date__gt=hace60, creado__date__lte=hace30).count()
    n_abiertos, n_vencidos = abiertos.count(), vencidos_qs.count()

    kpis = {
        'activos': activos.count(), 'abiertos': n_abiertos,
        'en_progreso': por_estado.get(E.EN_PROGRESO, 0), 'por_hacer': por_estado.get(E.POR_HACER, 0),
        'entrada': por_estado.get(E.ENTRADA, 0),
        'vencidos': n_vencidos, 'proximos': proximos_qs.count(), 'por_aprobar': por_aprobar_qs.count(),
        'concluidos_30': concluidos_30, 'delta_concluidos': _delta(concluidos_30, concluidos_prev),
        'creados_30': creados_30, 'delta_creados': _delta(creados_30, creados_prev),
        'pct_vencidos': round(n_vencidos * 100 / n_abiertos) if n_abiertos else 0,
    }

    total = sum(por_estado.values())
    estados, x = [], 0.0
    for valor, etiqueta in E.choices:
        n = por_estado.get(valor, 0)
        pct = n * 100 / total if total else 0
        color = Ticket(estado=valor).color_estado
        estados.append({'label': etiqueta, 'count': n, 'pct': round(pct), 'x': f'{x:.1f}', 'w': f'{pct:.1f}',
                        'fill': FILL[color], 'bg': BG[color]})
        x += pct

    por_prio = {r['prioridad']: r['n'] for r in abiertos.values('prioridad').annotate(n=Count('id'))}
    prioridades = con_porcentaje([
        {'label': l, 'count': por_prio.get(v, 0), 'color': Ticket(prioridad=v).color_prioridad}
        for v, l in Ticket.Prioridad.choices])

    carga = (Asignacion.objects.filter(tipo=Asignacion.Tipo.EJECUTOR, ticket__empresa=empresa,
                                       ticket__archivado_en__isnull=True, ticket__dividido_en__isnull=True)
             .exclude(ticket__estado=E.CONCLUIDO)
             .values('user__email', 'user__first_name', 'user__last_name')
             .annotate(n=Count('ticket', distinct=True),
                       atrasados=Count('ticket', distinct=True, filter=Q(ticket__vence__lt=hoy)))
             .order_by('-n')[:8])
    por_asignado = con_porcentaje([
        {'label': _nombre(r['user__first_name'], r['user__last_name'], r['user__email']), 'count': r['n'],
         'atrasados': r['atrasados'], 'color': 'neutral'} for r in carga])
    por_proyecto = con_porcentaje([
        {'label': f"{r['proyecto__codigo']} · {r['proyecto__nombre']}" if r['proyecto__codigo'] else r['proyecto__nombre'],
         'count': r['n'], 'color': 'neutral'}
        for r in abiertos.filter(proyecto__isnull=False).values('proyecto__codigo', 'proyecto__nombre')
        .annotate(n=Count('id')).order_by('-n')[:8]])

    prom = Asignacion.objects.filter(tipo=Asignacion.Tipo.EJECUTOR, estado=E.CONCLUIDO, ticket__empresa=empresa
                                     ).aggregate(en_progreso=Avg('tiempo_en_progreso'), por_hacer=Avg('tiempo_por_hacer'))
    resolucion = activos.filter(estado=E.CONCLUIDO, cerrado_en__isnull=False).aggregate(
        prom=Avg(ExpressionWrapper(F('cerrado_en') - F('creado'), output_field=DurationField())))['prom']
    tiempos = [
        {'label': 'Tiempo medio en progreso', 'value': _fmt_delta(prom['en_progreso'])},
        {'label': 'Tiempo medio en Por hacer', 'value': _fmt_delta(prom['por_hacer'])},
        {'label': 'Tiempo medio de resolución', 'value': _fmt_delta(resolucion)},
    ]

    # Creados y concluidos por semana (últimas 8). La geometría del SVG va como str: con LANGUAGE_CODE='es'
    # Django formatea los floats con coma y rompería los atributos numéricos.
    desde = hoy - timedelta(weeks=8)
    concl = {r['semana'].date(): r['n'] for r in activos.filter(estado=E.CONCLUIDO, cerrado_en__date__gte=desde)
             .annotate(semana=TruncWeek('cerrado_en')).values('semana').annotate(n=Count('id'))}
    creados = {r['semana'].date(): r['n'] for r in activos.filter(creado__date__gte=desde)
               .annotate(semana=TruncWeek('creado')).values('semana').annotate(n=Count('id'))}
    lunes = hoy - timedelta(days=hoy.weekday())
    serie = []
    for i in range(7, -1, -1):
        semana = lunes - timedelta(weeks=i)
        serie.append({'label': semana.strftime('%d/%m'), 'concluidos': concl.get(semana, 0),
                      'creados': creados.get(semana, 0)})
    tope = max((max(w['concluidos'], w['creados']) for w in serie), default=0) or 1
    ancho, grupo, alto_max, margen = 5, 12.5, 32, 4
    for idx, w in enumerate(serie):
        for clave, dx in (('creados', 1), ('concluidos', 1 + ancho + 0.5)):
            alto = round(w[clave] / tope * alto_max)
            w[f'{clave}_g'] = {'x': f'{idx * grupo + dx:.1f}', 'y': str(margen + alto_max - alto),
                               'h': str(alto), 'w': str(ancho)}

    sel = ('proyecto',)
    vencidos = [_item(t, hoy) for t in vencidos_qs.select_related(*sel).order_by('vence')[:LIMITE]]
    proximos = [_item(t, hoy) for t in proximos_qs.select_related(*sel).order_by('vence')[:LIMITE]]
    por_aprobar = [_item(t, hoy) for t in por_aprobar_qs.select_related(*sel).order_by('cerrado_en', 'pk')[:LIMITE]]
    actividad = [{
        'ticket': e.ticket.clave, 'url': reverse('tar_tickets:detalle', args=[e.ticket_id]), 'detalle': e.detalle,
        'actor': (e.actor.get_full_name().strip() or e.actor.email) if e.actor_id else '—', 'creado': e.creado,
        'titulo': e.ticket.titulo,
    } for e in Evento.objects.filter(ticket__empresa=empresa).select_related('ticket', 'actor').order_by('-creado')[:8]]

    return {
        'hoy': hoy, 'kpis': kpis, 'estados': estados, 'prioridades': prioridades, 'por_asignado': por_asignado,
        'por_proyecto': por_proyecto, 'tiempos': tiempos, 'serie': serie, 'vencidos': vencidos,
        'proximos': proximos, 'por_aprobar': por_aprobar, 'actividad': actividad, 'dias_proximos': DIAS_PROXIMOS,
    }

