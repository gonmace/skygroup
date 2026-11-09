"""Datos del panel de Construcción en el inicio de Registros (KPIs, estados, contratistas, mapa, actividad).

Todo respeta el alcance de la persona (`reg_base.alcance.registros_visibles`) y se cachea unos minutos por
empresa y alcance (todo / contratista / persona).
"""
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Count, Min, OuterRef, Prefetch, Subquery
from django.urls import reverse
from django.utils import timezone

from cuentas.capacidades import membresia_activa, tiene_capacidad
from proyectos.models import Proyecto, ProyectoUbicacion
from reg_base.alcance import registros_visibles

from .models import RegConstruccion

CACHE_TTL = 120   # segundos
CACHE_TTL_ACTIVIDAD = 30
DIAS_SIN_VISITA = 14   # una obra en construcción sin visita hace más días que esto requiere atención

# Clases completas (Tailwind las detecta al escanear este archivo). Los colores coinciden con los de
# `proyectos/_badge_estado.html` y `static/js/proyectos-mapa.js`.
COLOR_ESTADO = {
    Proyecto.Estado.INGENIERIA: 'bg-violeta',
    Proyecto.Estado.CONSTRUCCION: 'bg-azul',
    Proyecto.Estado.PARALIZADO: 'bg-warning',
    Proyecto.Estado.CONCLUIDO: 'bg-success',
    Proyecto.Estado.CANCELADO: 'bg-error',
}
FILL_ESTADO = {
    Proyecto.Estado.INGENIERIA: 'fill-violeta',
    Proyecto.Estado.CONSTRUCCION: 'fill-azul',
    Proyecto.Estado.PARALIZADO: 'fill-warning',
    Proyecto.Estado.CONCLUIDO: 'fill-success',
    Proyecto.Estado.CANCELADO: 'fill-error',
}


# ── Alcance y caché ──────────────────────────────────────────────────────────

def _alcance(user, empresa):
    if user.is_superuser or tiene_capacidad(user, 'reg.alcance.todo', empresa):
        return 'todo'
    if tiene_capacidad(user, 'reg.alcance.contratista', empresa):
        m = membresia_activa(user, empresa)
        if m is not None and m.contratista_id:
            return f'c{m.contratista_id}'
    return f'u{user.pk}'


def cached(prefijo, user, empresa, calcular, ttl=CACHE_TTL):
    """Cachea el resultado por empresa y alcance; si la caché falla, calcula directo."""
    try:
        return cache.get_or_set(f'reg:panel:{empresa.pk}:{prefijo}:{_alcance(user, empresa)}', calcular, ttl)
    except Exception:
        return calcular()


def visitas_del_alcance(user, empresa):
    return registros_visibles(user, empresa, RegConstruccion.objects.all())


def _url_proyecto(proyecto_id):
    return f"{reverse('reg_construccion:lista')}?proyecto={proyecto_id}"


def _promedio(valores):
    return round(sum(valores) / len(valores), 1) if valores else 0


def _proyectos_con_ultima_visita(user, empresa):
    """Un dict por proyecto con visitas visibles, con el resumen de su última visita."""
    base = visitas_del_alcance(user, empresa)
    ultima = base.filter(proyecto_id=OuterRef('proyecto_id')).order_by('-fecha', '-id')
    filas = (base.exclude(proyecto__isnull=True).order_by()
             .values('proyecto_id', 'proyecto__codigo', 'proyecto__nombre', 'proyecto__estado')
             .annotate(n_visitas=Count('id'), primera_fecha=Min('fecha'),
                       ultima_fecha=Subquery(ultima.values('fecha')[:1]),
                       ultimo_avance=Subquery(ultima.values('avance_pct')[:1]),
                       contratista_id=Subquery(ultima.values('contratista_id')[:1]),
                       contratista_nombre=Subquery(ultima.values('contratista__nombre')[:1]),
                       contratista_codigo=Subquery(ultima.values('contratista__codigo')[:1])))
    resultado = []
    for f in filas:
        f['avance'] = float(f['ultimo_avance'] or 0)
        f['estado'] = f['proyecto__estado']
        f['url'] = _url_proyecto(f['proyecto_id'])
        resultado.append(f)
    return resultado


# ── Panel principal ──────────────────────────────────────────────────────────

def _calcular_panel(user, empresa):
    hoy = timezone.localdate()
    hace30, hace60 = hoy - timedelta(days=30), hoy - timedelta(days=60)
    umbral = hoy - timedelta(days=DIAS_SIN_VISITA)
    filas = _proyectos_con_ultima_visita(user, empresa)
    visitas = visitas_del_alcance(user, empresa)
    visitas_30 = visitas.filter(fecha__gt=hace30).count()
    visitas_prev = visitas.filter(fecha__gt=hace60, fecha__lte=hace30).count()
    visitas_30_por_contratista = dict(
        visitas.filter(fecha__gt=hace30).order_by().values_list('contratista_id').annotate(c=Count('id')))

    total = len(filas)
    estados = []
    x = 0.0
    for codigo, nombre in Proyecto.Estado.choices:
        n = sum(1 for f in filas if f['estado'] == codigo)
        pct = round(n * 100 / total, 1) if total else 0
        estados.append({'codigo': codigo, 'nombre': nombre, 'n': n, 'pct': pct, 'x': round(x, 1),
                        'barra': COLOR_ESTADO[codigo], 'fill': FILL_ESTADO[codigo]})
        x += pct
    rangos = []
    for etiqueta, desde, hasta in (('0–25 %', 0, 25), ('25–50 %', 25, 50), ('50–75 %', 50, 75), ('75–100 %', 75, 101)):
        n = sum(1 for f in filas if desde <= f['avance'] < hasta)
        rangos.append({'etiqueta': etiqueta, 'n': n, 'pct': round(n * 100 / total) if total else 0})

    en_obra = [f for f in filas if f['estado'] == Proyecto.Estado.CONSTRUCCION]
    sin_visita = sorted((f for f in en_obra if f['ultima_fecha'] and f['ultima_fecha'] < umbral),
                        key=lambda f: f['ultima_fecha'])
    for f in sin_visita:
        f['dias_sin_visita'] = (hoy - f['ultima_fecha']).days
    menor_avance = sorted(en_obra, key=lambda f: f['avance'])
    for f in menor_avance:
        f['dias_en_obra'] = (hoy - f['primera_fecha']).days if f['primera_fecha'] else None
    sin_concluir = visitas.filter(concluido=False).count()

    grupos = {}
    for f in filas:
        g = grupos.setdefault(f['contratista_id'], {
            'id': f['contratista_id'], 'nombre': f['contratista_nombre'] or 'Sin contratista',
            'codigo': f['contratista_codigo'] or '', 'proyectos': 0, 'en_obra': 0, 'concluidos': 0, 'avances': [],
        })
        g['proyectos'] += 1
        g['en_obra'] += f['estado'] == Proyecto.Estado.CONSTRUCCION
        g['concluidos'] += f['estado'] == Proyecto.Estado.CONCLUIDO
        g['avances'].append(f['avance'])
    contratistas = []
    for g in grupos.values():
        g['avance'] = _promedio(g.pop('avances'))
        g['visitas_30'] = visitas_30_por_contratista.get(g['id'], 0)
        contratistas.append(g)
    contratistas.sort(key=lambda g: (-g['proyectos'], g['nombre']))

    return {
        'kpis': {
            'proyectos': total,
            'en_obra': len(en_obra),
            'concluidos': sum(1 for f in filas if f['estado'] == Proyecto.Estado.CONCLUIDO),
            'avance_en_obra': _promedio([f['avance'] for f in en_obra]),
            'avance_global': _promedio([f['avance'] for f in filas]),
            'visitas_30': visitas_30,
            'delta_visitas': round((visitas_30 - visitas_prev) * 100 / visitas_prev) if visitas_prev else None,
            'total_visitas': visitas.count(),
            'sin_visita': len(sin_visita),
            'sin_concluir': sin_concluir,
            'atencion': len(sin_visita) + sin_concluir,
        },
        'estados': estados,
        'rangos': rangos,
        'contratistas': contratistas,
        'menor_avance': menor_avance[:6],
        'sin_visita_reciente': sin_visita[:6],
    }


def panel(user, empresa):
    return cached('panel', user, empresa, lambda: _calcular_panel(user, empresa))


# ── Actividad reciente y pendientes ──────────────────────────────────────────

def _items(qs, limite):
    items = []
    for r in qs.select_related('proyecto', 'user', 'contratista')[:limite]:
        items.append({
            'proyecto': r.proyecto.nombre if r.proyecto else '—',
            'codigo': r.proyecto.codigo if r.proyecto else '',
            'usuario': r.responsable_nombre,
            'contratista': r.contratista.codigo if r.contratista else '',
            'fecha': r.fecha, 'actualizado': r.updated_at, 'avance': float(r.avance_pct or 0),
            'estado': 'concluido' if r.concluido else ('en_proceso' if r.has_widgets else 'vacio'),
            'url': reverse('reg_construccion:detalle', args=[r.pk]),
        })
    return items


def actividad_reciente(user, empresa, limite=8):
    return cached('actividad', user, empresa,
                  lambda: _items(visitas_del_alcance(user, empresa).with_estado().order_by('-updated_at'), limite),
                  CACHE_TTL_ACTIVIDAD)


def pendientes(user, empresa, limite=6):
    """Visitas sin concluir, las más antiguas primero."""
    return cached('pendientes', user, empresa,
                  lambda: _items(visitas_del_alcance(user, empresa).filter(concluido=False)
                                 .with_estado().order_by('fecha'), limite),
                  CACHE_TTL_ACTIVIDAD)


# ── Mapa ─────────────────────────────────────────────────────────────────────

def _coordenadas(proyecto):
    """Ubicación «Construcción», luego «Ingeniería», luego la primera."""
    ubicaciones = list(proyecto.ubicaciones.all())
    por_etiqueta = {u.etiqueta.lower(): u for u in ubicaciones}
    for clave in ('construcción', 'construccion', 'ingeniería', 'ingenieria'):
        if clave in por_etiqueta:
            return por_etiqueta[clave]
    return ubicaciones[0] if ubicaciones else None


def _calcular_puntos(user, empresa):
    por_id = {f['proyecto_id']: f for f in _proyectos_con_ultima_visita(user, empresa)}
    proyectos = (Proyecto.objects.filter(pk__in=por_id)
                 .select_related('tipo')
                 .prefetch_related(Prefetch('ubicaciones', queryset=ProyectoUbicacion.objects.order_by('pk'))))
    sin_tipo = empresa.termino_proyecto_singular
    puntos = []
    for p in proyectos:
        u = _coordenadas(p)
        if u is None:
            continue
        f = por_id[p.pk]
        detalle = [f'{f["avance"]:.0f} % de avance']
        if f['contratista_nombre']:
            detalle.append(f['contratista_nombre'])
        if f['ultima_fecha']:
            detalle.append(f'última visita {f["ultima_fecha"]:%d/%m/%Y}')
        puntos.append({
            'id': p.pk, 'lat': float(u.lat), 'lon': float(u.lon), 'nombre': p.nombre, 'codigo': p.codigo,
            'estado': p.estado, 'estado_txt': p.get_estado_display(),
            'tipo': p.tipo.nombre if p.tipo_id else sin_tipo,
            'url': f['url'], 'detalle': ' · '.join(detalle),
        })
    return puntos


def puntos_mapa(user, empresa):
    return cached('mapa', user, empresa, lambda: _calcular_puntos(user, empresa))


def contexto_inicio(user, empresa):
    """Contexto del panel de «Construcción» en el Resumen de Registros (ver `reg_base.views.inicio`)."""
    from django.urls import reverse
    ctx = dict(
        panel(user, empresa),
        actividad=actividad_reciente(user, empresa),
        pendientes=pendientes(user, empresa),
        puntos=puntos_mapa(user, empresa),
        dias_sin_visita=DIAS_SIN_VISITA,
    )
    acciones = [{'url': reverse('reg_construccion:lista'), 'texto': 'Ver obras', 'icono': 'hardhat', 'primaria': True}]
    if tiene_capacidad(user, 'reg.activar', empresa):
        acciones.append({'url': reverse('reg_construccion:activar'), 'texto': 'Activar registro', 'icono': 'plus'})
    ctx['acciones'] = acciones
    return ctx
