"""Panel de «Supervisión Campo» en el Resumen de Registros: visitas de la semana, hallazgos por severidad, vencidos,
días promedio de cierre, últimas visitas y mapa. Respeta el alcance de la persona y se cachea unos minutos."""
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Count, Prefetch, Q
from django.urls import reverse
from django.utils import timezone

from cuentas.capacidades import membresia_activa, tiene_capacidad
from proyectos.models import Proyecto, ProyectoUbicacion
from reg_base.alcance import registros_visibles

from .models import Hallazgo, RegConstruccionBase

CACHE_TTL = 120   # segundos
Estado = Hallazgo.Estado


def _alcance(user, empresa):
    if user.is_superuser or tiene_capacidad(user, 'reg.alcance.todo', empresa):
        return 'todo'
    if tiene_capacidad(user, 'reg.alcance.contratista', empresa):
        m = membresia_activa(user, empresa)
        if m is not None and m.contratista_id:
            return f'c{m.contratista_id}'
    return f'u{user.pk}'


def _cached(prefijo, user, empresa, calcular):
    try:
        return cache.get_or_set(f'regcb:panel:{empresa.pk}:{prefijo}:{_alcance(user, empresa)}', calcular, CACHE_TTL)
    except Exception:
        return calcular()


def _visitas(user, empresa):
    """Visitas vigentes dentro del alcance."""
    return registros_visibles(user, empresa, RegConstruccionBase.objects.all()).filter(rev_vigente=True)


def _calcular(user, empresa):
    visitas = _visitas(user, empresa)
    hoy = timezone.localdate()
    semana = hoy - timedelta(days=hoy.weekday())   # lunes
    hallazgos = Hallazgo.objects.filter(empresa=empresa, is_deleted=False, visita__in=visitas)
    abiertos = hallazgos.exclude(estado=Estado.CERRADO)
    por_sev = {r['severidad']: r['n'] for r in abiertos.values('severidad').annotate(n=Count('pk'))}
    cerrados = list(hallazgos.filter(estado=Estado.CERRADO, cerrado_fecha__isnull=False)
                    .values_list('visita__fecha', 'cerrado_fecha'))
    dias = [(c - v).days for v, c in cerrados]
    return {
        'kpis': {
            'visitas_semana': visitas.filter(fecha__gte=semana).count(),
            'visitas_total': visitas.count(),
            'proyectos': visitas.exclude(proyecto__isnull=True).values('proyecto_id').distinct().count(),
            'abiertos': abiertos.count(),
            'criticos': por_sev.get(Hallazgo.Severidad.CRITICA, 0),
            'mayores': por_sev.get(Hallazgo.Severidad.MAYOR, 0),
            'menores': por_sev.get(Hallazgo.Severidad.MENOR, 0),
            'vencidos': abiertos.filter(plazo__lt=hoy).count(),
            'dias_cierre': round(sum(dias) / len(dias), 1) if dias else None,
            'borradores': visitas.filter(concluido=False).count(),
        },
    }


def _ultimas(user, empresa, limite=8):
    qs = (_visitas(user, empresa).select_related('proyecto', 'user')
          .annotate(n_abiertos=Count('hallazgos', filter=Q(hallazgos__is_deleted=False) & ~Q(hallazgos__estado='cerrado'),
                                     distinct=True))
          .order_by('-fecha', '-id')[:limite])
    return [{'url': reverse('reg_construccion_base:detalle', args=[v.pk]), 'proyecto': v.proyecto.nombre if v.proyecto else '—',
             'codigo': v.proyecto.codigo if v.proyecto else '', 'numero': v.numero, 'fecha': v.fecha,
             'usuario': v.responsable_nombre, 'emitida': v.concluido, 'abiertos': v.n_abiertos} for v in qs]


def _criticos(user, empresa, limite=6):
    qs = (Hallazgo.objects.filter(empresa=empresa, is_deleted=False, visita__in=_visitas(user, empresa),
                                  severidad=Hallazgo.Severidad.CRITICA)
          .exclude(estado=Estado.CERRADO).select_related('proyecto').order_by('plazo', 'numero')[:limite])
    return [{'url': reverse('reg_construccion_base:hallazgo_detalle', args=[h.pk]), 'codigo': h.codigo,
             'proyecto': h.proyecto.nombre if h.proyecto else '—', 'descripcion': h.descripcion, 'plazo': h.plazo,
             'vencido': h.vencido} for h in qs]


def _ubicacion(proyecto):
    """Ubicación «Construcción», luego «Ingeniería», luego la primera."""
    ubicaciones = list(proyecto.ubicaciones.all())
    por_etiqueta = {u.etiqueta.lower(): u for u in ubicaciones}
    for clave in ('construcción', 'construccion', 'ingeniería', 'ingenieria'):
        if clave in por_etiqueta:
            return por_etiqueta[clave]
    return ubicaciones[0] if ubicaciones else None


def _puntos(user, empresa):
    visitas = _visitas(user, empresa).exclude(proyecto__isnull=True)
    ultima = {}
    for v in visitas.order_by('fecha', 'id'):
        ultima[v.proyecto_id] = v   # la última por fecha
    abiertos = dict(Hallazgo.objects.filter(empresa=empresa, is_deleted=False, visita__in=visitas)
                    .exclude(estado=Estado.CERRADO).values_list('proyecto_id').annotate(n=Count('pk')))
    proyectos = (Proyecto.objects.filter(pk__in=ultima).select_related('tipo')
                 .prefetch_related(Prefetch('ubicaciones', queryset=ProyectoUbicacion.objects.order_by('pk'))))
    sin_tipo = empresa.termino_proyecto_singular
    puntos = []
    for p in proyectos:
        u = _ubicacion(p)
        if u is None:
            continue
        v = ultima[p.pk]
        detalle = [f'última visita {v.fecha:%d/%m/%Y}']
        if abiertos.get(p.pk):
            detalle.append(f'{abiertos[p.pk]} hallazgo{"s" if abiertos[p.pk] != 1 else ""} abierto{"s" if abiertos[p.pk] != 1 else ""}')
        puntos.append({
            'id': p.pk, 'lat': float(u.lat), 'lon': float(u.lon), 'nombre': p.nombre, 'codigo': p.codigo,
            'estado': p.estado, 'estado_txt': p.get_estado_display(), 'tipo': p.tipo.nombre if p.tipo_id else sin_tipo,
            'url': reverse('reg_construccion_base:detalle', args=[v.pk]), 'detalle': ' · '.join(detalle),
        })
    return puntos


def contexto_inicio(user, empresa):
    """Contexto del panel de «Supervisión Campo» en el Resumen de Registros (ver `reg_base.views.inicio`)."""
    ctx = dict(_cached('kpis', user, empresa, lambda: _calcular(user, empresa)))
    ctx['ultimas'] = _ultimas(user, empresa)
    ctx['criticos'] = _criticos(user, empresa)
    ctx['puntos_cb'] = _cached('mapa', user, empresa, lambda: _puntos(user, empresa))
    ctx['puntos'] = ctx['puntos_cb']
    acciones = [{'url': reverse('reg_construccion_base:lista'), 'texto': 'Ver visitas', 'icono': 'building', 'primaria': True},
                {'url': reverse('reg_construccion_base:hallazgos'), 'texto': 'Hallazgos', 'icono': 'eye'}]
    if tiene_capacidad(user, 'reg.activar', empresa):
        acciones.append({'url': reverse('reg_construccion_base:nueva'), 'texto': 'Nueva visita', 'icono': 'plus'})
    ctx['acciones'] = acciones
    return ctx
