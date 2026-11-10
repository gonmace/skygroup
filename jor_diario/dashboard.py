"""Datos del resumen de Jornadas (solo administración/observación): estado del equipo hoy, horas, ausencias,
proyectos y actividades. Siempre acotado a la empresa."""
from collections import Counter
from datetime import datetime, timedelta

from django.core.cache import cache
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from cuentas.models import Membresia
from cuentas.roles import RolBase as R
from jor_actividades.models import ItemActividad
from jor_actividades.servicios import categorias

from .models import Ausencia, Jornada, NotaCalendario

CACHE_TTL = 60
# Quienes fichan por defecto (capacidad `jor.fichar`): el Observador no cuenta como «sin iniciar».
FICHAN = (R.COORDINADOR, R.ESPECIALISTA, R.MIEMBRO)
LIMITE = 6

# Clases completas (Tailwind las detecta al escanear este archivo).
ESTADOS = (
    ('en_curso', 'En curso', 'fill-success', 'bg-success'),
    ('termino', 'Terminaron', 'fill-info', 'bg-info'),
    ('ausente', 'Ausentes', 'fill-warning', 'bg-warning'),
    ('sin_iniciar', 'Sin iniciar', 'fill-error', 'bg-error'),
    ('descanso', 'Sin jornada (día no laboral)', 'fill-base-content/25', 'bg-base-content/25'),
)


def hhmm(minutos):
    return f'{int(minutos) // 60}h {int(minutos) % 60:02d}m'


def _delta(actual, previo):
    return round((actual - previo) * 100 / previo) if previo else None


def _dia_dt(dia):
    return timezone.make_aware(datetime.combine(dia, datetime.min.time()))


def _calcular(empresa):
    ahora = timezone.localtime()
    hoy = ahora.date()
    ini_hoy = _dia_dt(hoy)
    hace30, hace60 = hoy - timedelta(days=30), hoy - timedelta(days=60)

    miembros = [m for m in Membresia.objects.filter(
        empresa=empresa, activa=True, user__is_active=True, user__is_superuser=False, rol__rol_base__in=FICHAN)
        .exclude(user__empresas_administradas=empresa)
        .select_related('user', 'rol', 'perfil_jor').order_by('user__first_name', 'user__email')
        if getattr(m, 'perfil_jor', None) is None or m.perfil_jor.activo]
    feriado = NotaCalendario.objects.filter(empresa=empresa, fecha=hoy, tipo=NotaCalendario.Tipo.FERIADO).exists()
    laboral = hoy.weekday() < 5 and not feriado

    de_hoy = {}
    for j in Jornada.objects.filter(empresa=empresa, inicio__gte=ini_hoy).exclude(
            estado_verificacion=Jornada.Verificacion.RECHAZADA).select_related('proyecto').order_by('inicio'):
        de_hoy[j.perfil_id] = j   # la última del día
    ausentes = set(Ausencia.objects.filter(empresa=empresa, estado=Ausencia.Estado.APROBADA,
                                           desde__lte=hoy, hasta__gte=hoy).values_list('perfil_id', flat=True))

    cuenta, en_curso, sin_iniciar = Counter(), [], []
    for m in miembros:
        perfil = getattr(m, 'perfil_jor', None)
        j = de_hoy.get(perfil.pk) if perfil else None
        if perfil and perfil.pk in ausentes:
            estado = 'ausente'
        elif j and j.abierta:
            estado = 'en_curso'
            en_curso.append({
                'nombre': str(m.user), 'cargo': perfil.cargo_completo if perfil else m.rol.nombre, 'desde': timezone.localtime(j.inicio),
                'minutos': hhmm((ahora - j.inicio).total_seconds() // 60),
                'proyecto': j.proyecto.nombre if j.proyecto_id else '',
                'url': reverse('jor_diario:persona', args=[m.pk]),
            })
        elif j:
            estado = 'termino'
        elif laboral:
            estado = 'sin_iniciar'
            entrada = perfil.hora_entrada if perfil else None
            sin_iniciar.append({
                'nombre': str(m.user), 'cargo': perfil.cargo_completo if perfil else m.rol.nombre, 'entrada': entrada,
                'tarde': bool(entrada and ahora.time() > entrada), 'url': reverse('jor_diario:persona', args=[m.pk]),
            })
        else:
            estado = 'descanso'
        cuenta[estado] += 1
    total = len(miembros)
    estados, x = [], 0.0
    for codigo, nombre, fill, bg in ESTADOS:
        n = cuenta.get(codigo, 0)
        if codigo == 'descanso' and not n:
            continue
        pct = n * 100 / total if total else 0
        estados.append({'label': nombre, 'count': n, 'pct': round(pct), 'x': f'{x:.1f}', 'w': f'{pct:.1f}',
                        'fill': fill, 'bg': bg})
        x += pct
    sin_iniciar.sort(key=lambda p: (not p['tarde'], p['nombre']))

    # Horas del equipo: últimos 30 días contra los 30 previos, y serie diaria de los últimos 14.
    completas = Jornada.objects.computables().filter(empresa=empresa).exclude(duracion_min=None)
    min_30 = completas.filter(inicio__gte=_dia_dt(hace30)).aggregate(s=Sum('duracion_min'))['s'] or 0
    min_prev = completas.filter(inicio__gte=_dia_dt(hace60), inicio__lt=_dia_dt(hace30)).aggregate(
        s=Sum('duracion_min'))['s'] or 0
    sin_cerrar = Jornada.objects.filter(empresa=empresa, cierre_auto=True, inicio__gte=_dia_dt(hace30))
    n_sin_cerrar = sin_cerrar.count()
    pendientes_qs = Ausencia.objects.filter(empresa=empresa, estado=Ausencia.Estado.PENDIENTE)
    n_pendientes = pendientes_qs.count()
    presentes = cuenta['en_curso'] + cuenta['termino']

    desde14 = hoy - timedelta(days=13)
    por_dia = {r['d']: r['m'] for r in completas.filter(inicio__gte=_dia_dt(desde14))
               .annotate(d=TruncDate('inicio')).values('d').annotate(m=Sum('duracion_min'))}
    serie = [{'fecha': desde14 + timedelta(days=i), 'minutos': por_dia.get(desde14 + timedelta(days=i), 0)}
             for i in range(14)]
    tope = max((s['minutos'] for s in serie), default=0) or 1
    alto_max, margen, ancho, paso = 32, 4, 5, 100 / 14
    for i, s in enumerate(serie):
        alto = round(s['minutos'] / tope * alto_max)
        s.update(label=f"{s['fecha']:%d/%m}", horas=hhmm(s['minutos']), finde=s['fecha'].weekday() >= 5,
                 x=f'{i * paso + (paso - ancho) / 2:.1f}', y=str(margen + alto_max - alto), h=str(alto), w=str(ancho))

    # Por proyecto (horas) y por categoría de actividad, últimos 30 días.
    proyectos = [{'label': r['proyecto__nombre'] or 'Sin proyecto', 'minutos': r['m'] or 0, 'count': f"{(r['m'] or 0) / 60:.0f}h"}
                 for r in completas.filter(inicio__gte=_dia_dt(hace30)).values('proyecto__nombre')
                 .annotate(m=Sum('duracion_min')).order_by('-m')[:8]]
    cats = {c.codigo: c for c in categorias(empresa)}
    por_cat = list(ItemActividad.objects.filter(
        empresa=empresa, tipo=ItemActividad.Tipo.HECHO, reporte__jornada__inicio__gte=_dia_dt(hace30))
        .values('categoria').annotate(n=Count('id')).order_by('-n')[:8])
    for lista, clave in ((proyectos, 'minutos'), (por_cat, 'n')):
        mayor = max((r[clave] for r in lista), default=0) or 1
        for r in lista:
            r['pct'] = round(100 * r[clave] / mayor)
    actividades = [{'label': cats[r['categoria']].etiqueta if r['categoria'] in cats else r['categoria'],
                    'color': cats[r['categoria']].color if r['categoria'] in cats else '#64748b',
                    'count': r['n'], 'pct': r['pct']} for r in por_cat]

    pendientes = [{
        'nombre': str(a.perfil.membresia.user), 'tipo': a.get_tipo_display(), 'desde': a.desde, 'hasta': a.hasta,
        'nota': a.nota,
    } for a in pendientes_qs.select_related('perfil__membresia__user').order_by('desde')[:LIMITE]]
    proximos = [{'fecha': n.fecha, 'texto': n.texto, 'tipo': n.get_tipo_display()}
                for n in NotaCalendario.objects.filter(empresa=empresa, fecha__gte=hoy,
                                                       fecha__lte=hoy + timedelta(days=14))[:LIMITE]]
    futuras = [{'fecha': a.desde, 'texto': f"{a.perfil.membresia.user} · hasta {a.hasta:%d/%m}",
                'tipo': a.get_tipo_display()}
               for a in Ausencia.objects.filter(empresa=empresa, estado=Ausencia.Estado.APROBADA, desde__gt=hoy,
                                                desde__lte=hoy + timedelta(days=14))
               .select_related('perfil__membresia__user').order_by('desde')[:LIMITE]]
    proximos = sorted(proximos + futuras, key=lambda p: p['fecha'])[:LIMITE]

    return {
        'hoy': hoy, 'laboral': laboral, 'total': total,
        'kpis': {
            'presentes': presentes, 'en_curso': cuenta['en_curso'], 'termino': cuenta['termino'],
            'ausentes': cuenta['ausente'], 'sin_iniciar': cuenta['sin_iniciar'] if laboral else 0,
            'horas_30': hhmm(min_30), 'delta_horas': _delta(min_30, min_prev),
            'sin_cerrar': n_sin_cerrar, 'pendientes': n_pendientes,
        },
        'estados': estados, 'en_curso': en_curso, 'sin_iniciar': sin_iniciar[:8], 'serie': serie,
        'proyectos': proyectos, 'actividades': actividades, 'pendientes': pendientes, 'proximos': proximos,
    }


def calcular(empresa):
    try:
        return cache.get_or_set(f'jor:resumen:{empresa.pk}', lambda: _calcular(empresa), CACHE_TTL)
    except Exception:
        return _calcular(empresa)
