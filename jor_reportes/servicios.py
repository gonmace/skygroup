"""Cálculo del reporte de asistencia y de las estadísticas de actividades (sin HTTP)."""
from collections import Counter, defaultdict
from calendar import monthrange
from datetime import date, timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from cuentas.roles import RolBase
from jor_actividades.models import Etiqueta, ItemActividad
from jor_actividades.servicios import categorias
from jor_diario.models import Ausencia, Jornada, NotaCalendario
from jor_empleados.models import ConfigJornadas, Perfil

from .periodo import DIAS, Periodo


def hhmm(minutos):
    return f'{minutos // 60:02d}:{minutos % 60:02d}'


# ── Asistencia ───────────────────────────────────────────────────────────────────────────────────
def asistencia(empresa, periodo, membresia_id=None, membresia_ids=None):
    """Por persona y por día: ingreso, salida, horas netas, atraso y comentarios. Una persona con varias
    jornadas el mismo día se agrega (primer ingreso, última salida, minutos sumados)."""
    refrigerio = ConfigJornadas.de(empresa).descuento_refrigerio_min
    Perfil.asegurar_de(empresa)
    perfiles = (Perfil.objects.filter(membresia__empresa=empresa, membresia__activa=True, activo=True)
                .select_related('membresia__user', 'membresia__rol')
                .order_by('membresia__user__first_name', 'membresia__user__last_name', 'membresia__user__email'))
    if membresia_id:
        perfiles = perfiles.filter(membresia_id=membresia_id)
    if membresia_ids is not None:                       # población acotada (p. ej. la del reporte de control de personal)
        perfiles = perfiles.filter(membresia_id__in=membresia_ids)
    perfiles = list(perfiles)
    ids = [p.pk for p in perfiles]

    por_dia = defaultdict(list)
    for j in Jornada.objects.computables().filter(
            empresa=empresa, perfil_id__in=ids, estado__in=[Jornada.Estado.COMPLETADA, Jornada.Estado.INCOMPLETA],
            inicio__range=(periodo.inicio_dt, periodo.fin_dt)).order_by('inicio'):
        por_dia[(j.perfil_id, timezone.localtime(j.inicio).date())].append(j)

    ausencias = defaultdict(list)
    tipos = defaultdict(set)                            # (perfil, día) → tipos de ausencia aprobada
    for a in Ausencia.objects.filter(empresa=empresa, perfil_id__in=ids, estado=Ausencia.Estado.APROBADA,
                                     desde__lte=periodo.hasta, hasta__gte=periodo.desde):
        d = max(a.desde, periodo.desde)
        while d <= min(a.hasta, periodo.hasta):
            ausencias[(a.perfil_id, d)].append(a.get_tipo_display() + (f' ({a.nota})' if a.nota else ''))
            tipos[(a.perfil_id, d)].add(a.tipo)
            d += timedelta(days=1)
    notas = defaultdict(list)
    for n in NotaCalendario.objects.filter(empresa=empresa, fecha__range=(periodo.desde, periodo.hasta)):
        notas[n.fecha].append(f'{n.get_tipo_display()}: {n.texto}')

    resultado = []
    for p in perfiles:
        ref = p.hora_entrada.hour * 60 + p.hora_entrada.minute
        filas, dias_trab, total, atraso_total, abiertas = [], 0, 0, 0, 0
        for dia in periodo.dias():
            js = por_dia.get((p.pk, dia))
            fila = {'fecha': dia, 'dia': DIAS[dia.weekday()], 'fin_semana': dia.weekday() >= 5,
                    'ingreso': '', 'salida': '', 'ingreso_t': None, 'salida_t': None, 'tipos_ausencia': tipos.get((p.pk, dia), set()),
                    'neto_min': None, 'horas': '', 'atraso_min': None, 'no_cerro': False,
                    'comentarios': ausencias.get((p.pk, dia), []) + notas.get(dia, [])}
            if js:
                ini = timezone.localtime(js[0].inicio)
                fin = timezone.localtime(js[-1].fin) if js[-1].fin else None
                neto = max(0, sum(j.duracion_min or 0 for j in js) - refrigerio)
                atraso = max(0, ini.hour * 60 + ini.minute - ref)
                fila.update(ingreso=f'{ini:%H:%M}', salida=f'{fin:%H:%M}' if fin else '—', neto_min=neto,
                            ingreso_t=ini.time().replace(second=0, microsecond=0),
                            salida_t=fin.time().replace(second=0, microsecond=0) if fin else None,
                            horas=hhmm(neto), atraso_min=atraso, no_cerro=any(j.cierre_auto for j in js))
                dias_trab += 1
                total += neto
                atraso_total += atraso
                abiertas += fila['no_cerro']
            filas.append(fila)
        resultado.append({'perfil': p, 'membresia_id': p.membresia_id, 'nombre': p.nombre, 'cargo': p.cargo_completo,
                          'filas': filas, 'dias': dias_trab, 'neto_min': total, 'horas': hhmm(total),
                          'atraso_min': atraso_total, 'no_cerro': abiertas,
                          'ausencias': sum(1 for f in filas if (p.pk, f['fecha']) in ausencias)})
    return resultado


# ── Estadísticas ─────────────────────────────────────────────────────────────────────────────────
ROLES = dict(RolBase.choices)


def _top_etiquetas(items, tipo, limite=12):
    """Top de etiquetas de un tipo, agrupando variantes en su canónica, con el desglose por categoría
    (`por_cat`: {codigo: n}) para dibujar cada barra segmentada."""
    conteo, por_cat = Counter(), defaultdict(Counter)
    nombres = {}
    for r in (items.filter(etiquetas__tipo=tipo, etiquetas__ignorada=False)
              .values('etiquetas__id', 'etiquetas__nombre', 'etiquetas__canonica_id', 'etiquetas__canonica__nombre', 'categoria')
              .annotate(n=Count('id', distinct=True))):
        cid = r['etiquetas__canonica_id'] or r['etiquetas__id']
        nombres[cid] = r['etiquetas__canonica__nombre'] or r['etiquetas__nombre']
        conteo[cid] += r['n']
        por_cat[cid][r['categoria']] += r['n']
    return [{'id': cid, 'nombre': nombres[cid], 'n': n, 'por_cat': dict(por_cat[cid])}
            for cid, n in sorted(conteo.items(), key=lambda kv: (-kv[1], nombres[kv[0]].lower()))[:limite]]


GRANULARIDADES = ('auto', 'week', 'month', 'quarter', 'year')


def _clave_tramo(d, gran):
    if gran == 'week':
        return (d - timedelta(days=d.weekday())).isoformat()
    if gran == 'quarter':
        return f'{d.year}-T{(d.month - 1) // 3 + 1}'
    if gran == 'year':
        return f'{d.year}'
    return f'{d:%Y-%m}'


def limites_tramo(clave, gran):
    """(desde, hasta) de un tramo de la evolución a partir de su clave."""
    if gran == 'week':
        desde = date.fromisoformat(clave)
        return desde, desde + timedelta(days=6)
    if gran == 'quarter':
        anio, _, q = clave.partition('-T')
        mes = (int(q) - 1) * 3 + 1
        desde = date(int(anio), mes, 1)
        fin = date(int(anio), mes + 2, 1)
        return desde, fin.replace(day=monthrange(fin.year, fin.month)[1])
    if gran == 'year':
        return date(int(clave), 1, 1), date(int(clave), 12, 31)
    anio, mes = int(clave[:4]), int(clave[5:7])
    return date(anio, mes, 1), date(anio, mes, monthrange(anio, mes)[1])


def _granularidad(gran, desde, hasta):
    """Resuelve 'auto' según la amplitud real de los datos: pocas semanas → semanas, años de historial → trimestres/años."""
    if gran in ('week', 'month', 'quarter', 'year'):
        return gran
    dias = (hasta - desde).days + 1 if desde and hasta else 1
    return 'week' if dias <= 92 else 'month' if dias <= 1100 else 'quarter' if dias <= 3700 else 'year'


def _periodo_anterior(periodo):
    """Ventana comparable previa: mismo tramo del mes anterior (modo mes) o igual longitud inmediatamente antes (rango)."""
    if periodo.modo not in ('month', 'range') or not (periodo.desde and periodo.hasta):
        return None
    if periodo.modo == 'month':
        fin_prev = periodo.desde - timedelta(days=1)
        desde = fin_prev.replace(day=1)
        hasta = min(fin_prev, desde + (periodo.hasta - periodo.desde))
    else:
        hasta = periodo.desde - timedelta(days=1)
        desde = hasta - (periodo.hasta - periodo.desde)
    return Periodo('range', desde, hasta, '')


def estadisticas(empresa, periodo, tipo=ItemActividad.Tipo.HECHO, rol_base='', membresia_id=None, granularidad='month',
                 cargo_id=None):
    if tipo not in ItemActividad.Tipo.values:
        tipo = ItemActividad.Tipo.HECHO
    if granularidad not in GRANULARIDADES:
        granularidad = 'month'
    cats = list(categorias(empresa))
    codigos = [c.codigo for c in cats]

    def base(desde_dt, hasta_dt, con_persona=True):
        qs = ItemActividad.objects.filter(empresa=empresa, tipo=tipo)
        if desde_dt:
            qs = qs.filter(reporte__jornada__inicio__gte=desde_dt)
        if hasta_dt:
            qs = qs.filter(reporte__jornada__inicio__lte=hasta_dt)
        if rol_base in ROLES:
            qs = qs.filter(reporte__jornada__perfil__membresia__rol__rol_base=rol_base)
        if cargo_id:
            qs = qs.filter(reporte__jornada__perfil__membresia__rol_id=cargo_id)
        if con_persona and membresia_id:
            qs = qs.filter(reporte__jornada__perfil__membresia_id=membresia_id)
        return qs

    ini, fin = periodo.inicio_dt, periodo.fin_dt
    if periodo.modo == 'last':
        ultimo = base(None, None).order_by('-reporte__jornada__inicio').values_list('reporte__jornada__inicio', flat=True).first()
        if ultimo:
            dia = timezone.localtime(ultimo).date()
            periodo.desde = periodo.hasta = dia
            ini, fin = periodo.inicio_dt, periodo.fin_dt
            periodo.etiqueta = f'Último día con datos: {dia:%d/%m/%Y}'

    items = base(ini, fin)
    # Una única lectura de ítems del período SIN filtro de persona: de ella salen el total, las personas, la
    # referencia por nivel de acceso (que debe ignorar el filtro) y la evolución.
    todas = [(cat, mid, rid, timezone.localtime(inicio).date(), rb) for cat, mid, rid, inicio, rb in
             base(ini, fin, con_persona=False).values_list(
                 'categoria', 'reporte__jornada__perfil__membresia_id', 'reporte_id', 'reporte__jornada__inicio',
                 'reporte__jornada__perfil__membresia__rol_id')]
    filas = [f for f in todas if f[1] == membresia_id] if membresia_id else todas

    total = len(filas)
    por_cat, por_persona, reportes_persona, ultima = Counter(), defaultdict(Counter), defaultdict(set), {}
    reportes, dias = set(), set()
    for cat, mid, rid, dia, _ in filas:
        por_cat[cat] += 1
        por_persona[mid][cat] += 1
        reportes_persona[mid].add(rid)
        reportes.add(rid)
        dias.add(dia)
        if mid not in ultima or dia > ultima[mid]:
            ultima[mid] = dia

    from cuentas.models import Membresia, RolEmpresa
    membresias = {m.pk: m for m in Membresia.objects.filter(pk__in=list(por_persona)).select_related('user', 'rol')}
    personas = []
    for mid, ctr in por_persona.items():
        m = membresias[mid]
        personas.append({
            'id': mid, 'nombre': str(m.user), 'rol': m.rol.nombre, 'rol_id': m.rol_id, 'rol_base': m.rol.rol_base,
            'total': sum(ctr.values()), 'reportes': len(reportes_persona[mid]),
            'promedio': round(sum(ctr.values()) / len(reportes_persona[mid]), 1),
            'ultimo': ultima[mid], 'top': max(ctr, key=ctr.get),
            'segundo': next((c for c, _ in ctr.most_common(2)[1:]), ''), 'n_cats': len(ctr),
            'pct_global': round(100 * sum(ctr.values()) / len(todas), 1) if todas else 0,
            'por_cat': [ctr.get(c, 0) for c in codigos]})
    personas.sort(key=lambda p: (-p['total'], p['nombre']))

    # Promedio por persona de cada cargo (referencia para comparar a alguien contra su grupo): TODO el grupo.
    ref = defaultdict(Counter)
    ref_reportes = defaultdict(set)
    roles_m = {}
    for cat, mid, rid, _, rb in todas:
        ref[mid][cat] += 1
        ref_reportes[mid].add(rid)
        roles_m[mid] = rb
    por_rol = defaultdict(lambda: {'personas': 0, 'total': 0, 'reportes': 0, 'cats': Counter()})
    for mid, ctr in ref.items():
        r = por_rol[roles_m[mid]]
        r['personas'] += 1
        r['total'] += sum(ctr.values())
        r['reportes'] += len(ref_reportes[mid])
        r['cats'].update(ctr)
    nombres_cargo = dict(RolEmpresa.objects.filter(pk__in=list(por_rol)).values_list('pk', 'nombre'))
    roles = [{'rol': nombres_cargo.get(k, str(k)), 'rol_id': k, 'personas': v['personas'], 'total': v['total'],
              'promedio': round(v['total'] / v['personas'], 1),
              'prom_reportes': round(v['reportes'] / v['personas'], 1),
              'prom_por_reporte': round(v['total'] / v['reportes'], 1) if v['reportes'] else 0,
              'top': max(v['cats'], key=v['cats'].get) if v['cats'] else '',
              'segundo': next((c for c, _ in v['cats'].most_common(2)[1:]), ''), 'n_cats': len(v['cats']),
              'por_cat': [round(v['cats'].get(c, 0) / v['personas'], 1) for c in codigos],
              'pct_cat': [round(100 * v['cats'].get(c, 0) / v['total'], 1) if v['total'] else 0 for c in codigos]}
             for k, v in sorted(por_rol.items(), key=lambda kv: (-kv[1]['total'], nombres_cargo.get(kv[0], '').lower()))]
    por_cat_global = Counter(f[0] for f in todas)          # todas las personas del período (referencia al filtrar una)

    categorias_res = [{'codigo': c.codigo, 'etiqueta': c.etiqueta, 'color': c.color, 'n': por_cat.get(c.codigo, 0),
                       'pct': round(100 * por_cat.get(c.codigo, 0) / total, 1) if total else 0} for c in cats]
    desconocidas = sorted(set(por_cat) - set(codigos))           # categorías borradas que aún tienen ítems
    for codigo in desconocidas:
        categorias_res.append({'codigo': codigo, 'etiqueta': codigo, 'color': '#64748b', 'n': por_cat[codigo],
                               'pct': round(100 * por_cat[codigo] / total, 1)})

    # Evolución: tramos semanales, mensuales, trimestrales o anuales (automático según la amplitud de los datos).
    granularidad = _granularidad(granularidad, min(dias) if dias else None, max(dias) if dias else None)
    evo = defaultdict(Counter)
    for cat, _, _, dia, _ in filas:
        evo[_clave_tramo(dia, granularidad)][cat] += 1
    evolucion = [{'clave': k, 'total': sum(v.values()), 'por_cat': [v.get(c, 0) for c in codigos],
                  'desde': limites_tramo(k, granularidad)[0], 'hasta': limites_tramo(k, granularidad)[1]}
                 for k, v in sorted(evo.items())]

    horas_proyecto = [
        {'nombre': r['proyecto__nombre'] or 'Sin proyecto', 'sin_proyecto': not r['proyecto__nombre'], 'jornadas': r['n'],
         'horas': hhmm(r['min'] or 0), 'minutos': r['min'] or 0, 'horas_enteras': ((r['min'] or 0) + 30) // 60}
        for r in (Jornada.objects.computables().filter(empresa=empresa).exclude(duracion_min=None)
                  .filter(**({'inicio__gte': ini} if ini else {}), **({'inicio__lte': fin} if fin else {}),
                          **({'perfil__membresia_id': membresia_id} if membresia_id else {}),
                          **({'perfil__membresia__rol__rol_base': rol_base} if rol_base in ROLES else {}),
                          **({'perfil__membresia__rol_id': cargo_id} if cargo_id else {}))
                  .values('proyecto__nombre').annotate(n=Count('id'), min=Sum('duracion_min')).order_by('-min'))]

    anterior = _periodo_anterior(periodo)
    total_anterior = base(anterior.inicio_dt, anterior.fin_dt).count() if anterior else None
    variacion = round(100 * (total - total_anterior) / total_anterior) if total_anterior else None

    return {
        'periodo': periodo, 'tipo': tipo, 'total': total, 'reportes': len(reportes), 'codigos': codigos,
        'promedio_por_reporte': round(total / len(reportes), 1) if reportes else 0, 'dias_con_datos': len(dias),
        'total_anterior': total_anterior, 'variacion': variacion,
        'categorias': categorias_res, 'total_global': len(todas), 'por_cat_global': dict(por_cat_global), 'personas': personas, 'roles': roles, 'evolucion': evolucion,
        'proyectos': _top_etiquetas(items, Etiqueta.Tipo.PROYECTO),
        'ubicaciones': _top_etiquetas(items, Etiqueta.Tipo.UBICACION),
        'entregables': _top_etiquetas(items, Etiqueta.Tipo.ENTREGABLE),
        'horas_proyecto': horas_proyecto, 'granularidad': granularidad,
        'etiquetas_categoria': {c['codigo']: c['etiqueta'] for c in categorias_res},
    }
