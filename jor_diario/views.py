import calendar
import json
from datetime import date, datetime

from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from cuentas.capacidades import administra, tiene_capacidad, usuarios_con_capacidad
from cuentas.roles import RolBase
from empresas.acceso import acceso_modulo
from jor_actividades.models import ItemActividad
from jor_empleados import passkeys
from jor_empleados.models import Perfil
from notificaciones.services import notificar, notificar_a_varios
from proyectos.models import Proyecto

from . import servicios
from .estado import estado_del_dia
from .forms import AusenciaForm, NotaForm, ReporteForm
from .models import Ausencia, Jornada, NotaCalendario


def _membresia(request):
    return request.user.membresias.filter(empresa=request.empresa, activa=True).first()


def _perfil_propio(request):
    """Perfil de jornadas de quien navega (None si es un superusuario sin membresía en la empresa)."""
    m = _membresia(request)
    return Perfil.de(m) if m else None


def _mes(request):
    """(año, mes) de `?mes=YYYY-MM`; por defecto el actual."""
    hoy = timezone.localdate()
    try:
        a, m = (int(x) for x in request.GET.get('mes', '').split('-'))
        date(a, m, 1)
    except (ValueError, TypeError):
        a, m = hoy.year, hoy.month
    return a, m


def _rango_mes(a, m):
    ini = timezone.make_aware(datetime(a, m, 1))
    fin_dia = calendar.monthrange(a, m)[1]
    return ini, timezone.make_aware(datetime(a, m, fin_dia, 23, 59, 59)), date(a, m, 1), date(a, m, fin_dia)


def _mes_nav(a, m):
    ant = (a - 1, 12) if m == 1 else (a, m - 1)
    sig = (a + 1, 1) if m == 12 else (a, m + 1)
    return {'actual': f'{a}-{m:02d}', 'anterior': f'{ant[0]}-{ant[1]:02d}', 'siguiente': f'{sig[0]}-{sig[1]:02d}'}


# ── Resumen (administración y observación) ──────────────────────────────────────────────────────
@acceso_modulo('jor', 'jor.dashboard.view')
def resumen(request):
    from . import dashboard
    return render(request, 'jor_diario/resumen.html', {
        **dashboard.calcular(request.empresa),
        'puede_ver_equipo': tiene_capacidad(request.user, 'jor.equipo.ver', request.empresa),
        'puede_aprobar': tiene_capacidad(request.user, 'jor.ausencias.gestionar', request.empresa),
    })


# ── Mi jornada ───────────────────────────────────────────────────────────────────────────────────
@acceso_modulo('jor', 'jor.fichar')
def inicio(request):
    perfil = _perfil_propio(request)
    if perfil is None and tiene_capacidad(request.user, 'jor.dashboard.view', request.empresa):
        return redirect('jor_diario:resumen')
    if perfil is None and tiene_capacidad(request.user, 'jor.equipo.ver', request.empresa):
        return redirect('jor_diario:equipo')   # superusuario sin membresía: no tiene jornada propia, su inicio es el equipo
    en_curso = servicios.jornada_en_curso(perfil) if perfil else None
    hoy = timezone.localdate()
    ini = timezone.make_aware(datetime.combine(hoy, datetime.min.time()))
    jornadas_hoy = list(perfil.jornadas.filter(inicio__gte=ini).select_related('reporte', 'proyecto')) if perfil else []
    estado, ultima = estado_del_dia(jornadas_hoy)
    return render(request, 'jor_diario/inicio.html', {
        'perfil': perfil, 'en_curso': en_curso, 'form': ReporteForm(),
        'estado_hoy': estado, 'jornada_hoy': ultima,
        'proyectos': Proyecto.objects.de_empresa(request.empresa).activos().order_by('nombre') if perfil else [],
        'hoy': jornadas_hoy,
        'exige_reporte': bool(perfil and perfil.exige_reporte),
        'dispositivo': passkeys.dispositivo_activo(perfil) if perfil else None,
        'sede': _membresia(request).sede if perfil else None,
    })


def _ip(request):
    """IP del cliente (nginx sobrescribe X-Real-IP): solo se guarda como auditoría, no valida nada."""
    return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR') or None


def _json(request):
    """Cuerpo de las marcaciones: campos de formulario con `credencial` y `lecturas` en JSON."""
    try:
        return json.loads(request.POST.get('credencial') or 'null'), json.loads(request.POST.get('lecturas') or '[]')
    except ValueError:
        raise servicios.ErrorJornada('La verificación enviada no es válida.')


def _responder_marca(request, hacer, ok_msg):
    """Verifica el passkey y ejecuta `hacer(dispositivo, lecturas)`; responde JSON para el script del celular."""
    perfil = _perfil_propio(request)
    if perfil is None:
        raise PermissionDenied
    try:
        credencial, lecturas = _json(request)
        dispositivo = passkeys.verificar_aserto(request, perfil, credencial)
        hacer(perfil, dispositivo, lecturas)
    except passkeys.ErrorPasskey as e:
        return JsonResponse({'ok': False, 'error': str(e), 'reintentar': True}, status=400)
    except (servicios.ErrorJornada, ValueError) as e:
        extra = e.extra if isinstance(e, servicios.ErrorJornada) else {}
        return JsonResponse({'ok': False, 'error': str(e) if isinstance(e, servicios.ErrorJornada) else 'Jornada no válida.',
                             **extra}, status=400)
    messages.success(request, ok_msg)
    return JsonResponse({'ok': True, 'url': reverse('jor_diario:inicio')})


@acceso_modulo('jor', 'jor.fichar')
@require_POST
def desafio(request):
    """Opciones WebAuthn (challenge de un solo uso) para marcar con el celular vinculado."""
    perfil = _perfil_propio(request)
    if perfil is None:
        raise PermissionDenied
    try:
        return JsonResponse({'ok': True, 'opciones': passkeys.opciones_autenticacion(request, perfil)})
    except passkeys.ErrorPasskey as e:
        return JsonResponse({'ok': False, 'error': str(e), 'dispositivo_requerido': True}, status=400)


@acceso_modulo('jor', 'jor.fichar')
@require_POST
def vincular_opciones(request):
    perfil = _perfil_propio(request)
    if perfil is None:
        raise PermissionDenied
    try:
        return JsonResponse({'ok': True, 'opciones': passkeys.opciones_registro(request, perfil)})
    except passkeys.ErrorPasskey as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)


@acceso_modulo('jor', 'jor.fichar')
@require_POST
def vincular(request):
    perfil = _perfil_propio(request)
    if perfil is None:
        raise PermissionDenied
    try:
        passkeys.registrar(request, perfil, json.loads(request.POST.get('credencial') or 'null'),
                           request.POST.get('nombre', ''))
    except (passkeys.ErrorPasskey, ValueError) as e:
        return JsonResponse({'ok': False, 'error': str(e) if isinstance(e, passkeys.ErrorPasskey) else 'Dato no válido.'},
                            status=400)
    messages.success(request, 'Celular vinculado. Ya puedes marcar tu jornada desde él.')
    return JsonResponse({'ok': True, 'url': reverse('jor_diario:inicio')})


@acceso_modulo('jor', 'jor.fichar')
@require_POST
def iniciar(request):
    proyecto = None
    if request.POST.get('proyecto'):
        proyecto = Proyecto.objects.de_empresa(request.empresa).activos().filter(pk=request.POST['proyecto'] if request.POST['proyecto'].isdigit() else 0).first()
        if proyecto is None:
            return JsonResponse({'ok': False, 'error': 'Ese proyecto no existe.'}, status=400)
    return _responder_marca(request, lambda perfil, disp, lecturas: servicios.iniciar(
        perfil, disp, lecturas, proyecto, request.POST.get('motivo', ''), _ip(request)), 'Jornada iniciada.')


@acceso_modulo('jor', 'jor.fichar')
@require_POST
def finalizar(request):
    form = ReporteForm(request.POST)
    form.is_valid()
    return _responder_marca(request, lambda perfil, disp, lecturas: servicios.finalizar(
        request.POST.get('jornada') or 0, perfil, disp, lecturas, form.cleaned_data.get('realizado'),
        form.cleaned_data.get('planificado'), _ip(request)),
        'Jornada finalizada. ¡Buen trabajo!')


def _puede_ver_mapa(user, empresa):
    """Solo superusuario y administradores de sistema de la empresa."""
    return user.is_superuser or administra(user, empresa.pk)


@acceso_modulo('jor', 'jor.equipo.ver')
def mapa_equipo(request):
    """Mapa con dónde marcó inicio y fin cada persona en un día. Solo superusuario y administradores."""
    from datetime import date, timedelta
    if not _puede_ver_mapa(request.user, request.empresa):
        raise PermissionDenied
    hoy = timezone.localdate()
    try:
        dia = min(date.fromisoformat(request.GET.get('fecha', '')), hoy)
    except ValueError:
        dia = hoy
    ini = timezone.make_aware(datetime.combine(dia, datetime.min.time()))
    puntos = []
    for j in (Jornada.objects.filter(empresa=request.empresa, inicio__gte=ini, inicio__lt=ini + timedelta(days=1))
              .select_related('perfil__membresia__user').order_by('inicio')):
        base = {'nombre': str(j.perfil.membresia.user), 'verificacion': j.get_estado_verificacion_display(),
                'url': reverse('jor_diario:persona', args=[j.perfil.membresia_id])}
        for tipo, lat, lon, hora, prec in (('inicio', j.lat_inicio, j.lon_inicio, j.inicio, j.precision_inicio),
                                           ('fin', j.lat_fin, j.lon_fin, j.fin, j.precision_fin)):
            if lat is not None and lon is not None:
                puntos.append({**base, 'tipo': tipo, 'lat': float(lat), 'lon': float(lon),
                               'hora': timezone.localtime(hora).strftime('%H:%M'),
                               'precision': round(prec) if prec is not None else None})
    return render(request, 'jor_diario/mapa.html', {
        'puntos': puntos, 'dia': dia, 'es_hoy': dia == hoy, 'anterior': dia - timedelta(days=1),
        'siguiente': dia + timedelta(days=1) if dia < hoy else None})


# ── Excepciones: jornadas iniciadas fuera de la sede, pendientes de aprobación ──────────────────
@acceso_modulo('jor', 'jor.excepciones.gestionar')
def excepciones(request):
    qs = Jornada.objects.filter(empresa=request.empresa).select_related('perfil__membresia__user', 'perfil__membresia__sede')
    recientes = (Jornada.Verificacion.EXCEPCION_APROBADA, Jornada.Verificacion.RECHAZADA)
    return render(request, 'jor_diario/excepciones.html', {
        'pendientes': qs.filter(estado_verificacion=Jornada.Verificacion.EXCEPCION_PENDIENTE).order_by('inicio'),
        'resueltas': qs.filter(estado_verificacion__in=recientes).select_related('revisada_por').order_by('-revisada_en')[:30]})


@acceso_modulo('jor', 'jor.excepciones.gestionar')
@require_POST
def excepcion_decidir(request, pk):
    aprobar = request.POST.get('decision') == 'aprobar'
    if request.POST.get('decision') not in ('aprobar', 'rechazar'):
        raise PermissionDenied
    try:
        servicios.decidir_excepcion(pk, request.empresa, request.user, aprobar)
        messages.success(request, 'Excepción aprobada.' if aprobar else 'Excepción rechazada.')
    except servicios.ErrorJornada as e:
        messages.error(request, str(e))
    return redirect('jor_diario:excepciones')


@acceso_modulo('jor', 'jor.fichar')
def historial(request):
    from django.db.models import Count, Sum
    perfil = _perfil_propio(request)
    qs = perfil.jornadas.select_related('reporte', 'proyecto') if perfil else Jornada.objects.none()
    resumen = qs.aggregate(n=Count('pk'), minutos=Sum('duracion_min'))
    pagina = Paginator(qs, 20).get_page(request.GET.get('p'))
    for j in pagina:
        j.duracion_txt = f'{j.duracion_min // 60}h {j.duracion_min % 60:02d}m' if j.duracion_min is not None else ''
    n, minutos = resumen['n'] or 0, resumen['minutos'] or 0
    return render(request, 'jor_diario/historial.html', {
        'pagina': pagina, 'total_jornadas': n, 'total_horas': f'{minutos // 60}h {minutos % 60:02d}m',
        'promedio': f'{minutos // n // 60}h {minutos // n % 60:02d}m' if n else '—'})


# ── Equipo ───────────────────────────────────────────────────────────────────────────────────────
@acceso_modulo('jor', 'jor.equipo.ver')
def equipo(request):
    """Estado de todo el equipo en un día (hoy por defecto; `?fecha=AAAA-MM-DD` para otro)."""
    from datetime import date, timedelta
    hoy = timezone.localdate()
    try:
        dia = date.fromisoformat(request.GET.get('fecha', ''))
    except ValueError:
        dia = hoy
    dia = min(dia, hoy)
    # Solo el nivel de acceso Ejecutor: quien ejecuta el trabajo y ficha jornada.
    miembros = list(request.empresa.membresias.filter(activa=True, user__is_active=True, rol__rol_base=RolBase.MIEMBRO)
                    .select_related('user', 'rol', 'perfil_jor').order_by('user__first_name', 'user__email'))
    ini = timezone.make_aware(datetime.combine(dia, datetime.min.time()))
    fin = ini + timedelta(days=1)
    de_dia = {}
    for j in Jornada.objects.filter(empresa=request.empresa, inicio__gte=ini, inicio__lt=fin).select_related('reporte').order_by('inicio'):
        de_dia[j.perfil_id] = j                      # la última del día
    ausentes = set(Ausencia.objects.filter(empresa=request.empresa, estado=Ausencia.Estado.APROBADA,
                                           desde__lte=dia, hasta__gte=dia).values_list('perfil_id', flat=True))
    filas = []
    for m in miembros:
        perfil = getattr(m, 'perfil_jor', None)
        j = de_dia.get(perfil.pk) if perfil else None
        if perfil and perfil.pk in ausentes:
            estado = 'ausente'
        elif j and j.abierta:
            estado = 'en_curso'
        elif j:
            estado = 'termino'
        else:
            estado = 'sin_iniciar'
        dur = f'{j.duracion_min // 60}h {j.duracion_min % 60:02d}m' if j and j.duracion_min is not None else ''
        rep = getattr(j, 'reporte', None) if j else None
        filas.append({'m': m, 'perfil': perfil, 'jornada': j, 'estado': estado, 'duracion': dur,
                      'hizo': rep.realizado if rep else '', 'planes': rep.planificado if rep else ''})
    orden = request.GET.get('orden', '')
    desc = request.GET.get('dir') == 'desc'
    claves = {'usuario': lambda f: str(f['m'].user).lower(),
              'cargo': lambda f: ((f['perfil'].cargo_completo if f['perfil'] else f['m'].rol.nombre).lower(),
                                  str(f['m'].user).lower())}
    if orden in claves:
        filas.sort(key=claves[orden], reverse=desc)
    else:
        orden = ''
    cabeceras = [{'clave': c, 'titulo': t, 'activa': orden == c, 'desc': orden == c and desc,
                  'url': f'?fecha={dia:%Y-%m-%d}&orden={c}&dir={"desc" if orden == c and not desc else "asc"}'}
                 for c, t in (('usuario', 'Usuario'), ('cargo', 'Cargo'))]
    ultimo = None
    if not de_dia:   # sin jornadas ese día: ofrecer el último día con datos
        previa = (Jornada.objects.filter(empresa=request.empresa, inicio__lt=ini).order_by('-inicio')
                  .values_list('inicio', flat=True).first())
        ultimo = timezone.localtime(previa).date() if previa else None
    return render(request, 'jor_diario/equipo.html', {
        'filas': filas, 'cabeceras': cabeceras, 'orden_qs': f'&orden={orden}&dir={"desc" if desc else "asc"}' if orden else '', 'en_curso': sum(f['estado'] == 'en_curso' for f in filas), 'dia': dia, 'es_hoy': dia == hoy,
        'anterior': dia - timedelta(days=1), 'siguiente': dia + timedelta(days=1) if dia < hoy else None,
        'con_jornada': sum(1 for f in filas if f['jornada']), 'ultimo_con_datos': ultimo,
        'completadas': sum(f['estado'] == 'termino' for f in filas), 'total_usuarios': len(filas),
        'actividades': ItemActividad.objects.filter(empresa=request.empresa, reporte__jornada__inicio__gte=ini,
                                                    reporte__jornada__inicio__lt=fin).count(),
        'puede_perfiles': tiene_capacidad(request.user, 'jor.perfiles.manage', request.empresa),
        'puede_mapa': _puede_ver_mapa(request.user, request.empresa)})


def _horas(minutos):
    return f'{minutos // 60} h {minutos % 60:02d} min'


@acceso_modulo('jor', 'jor.equipo.ver')
def persona(request, membresia_id):
    m = get_object_or_404(request.empresa.membresias.select_related('user', 'rol'), pk=membresia_id)
    perfil = Perfil.de(m)
    a, mes = _mes(request)
    ini, fin, d_ini, d_fin = _rango_mes(a, mes)
    jornadas = list(perfil.jornadas.filter(inicio__range=(ini, fin)).select_related('reporte').order_by('-inicio'))
    return render(request, 'jor_diario/persona.html', {
        'm': m, 'perfil': perfil, 'jornadas': jornadas, 'nav': _mes_nav(a, mes),
        'total_min': sum(j.duracion_min or 0 for j in jornadas),
        'total_txt': _horas(sum(j.duracion_min or 0 for j in jornadas)),
        'promedio_txt': _horas(sum(j.duracion_min or 0 for j in jornadas) // max(1, sum(1 for j in jornadas if j.duracion_min))),
        'con_reporte': sum(1 for j in jornadas if getattr(j, 'reporte', None)),
        'ausencias': perfil.ausencias.filter(desde__lte=d_fin, hasta__gte=d_ini),
        'dispositivo': passkeys.dispositivo_activo(perfil),
        'puede_perfiles': tiene_capacidad(request.user, 'jor.perfiles.manage', request.empresa)})


# ── Ausencias ────────────────────────────────────────────────────────────────────────────────────
def _gestiona_ausencias(request):
    return tiene_capacidad(request.user, 'jor.ausencias.gestionar', request.empresa)


@acceso_modulo('jor')
def ausencias(request):
    empresa, user = request.empresa, request.user
    gestiona = _gestiona_ausencias(request)
    puede_solicitar = tiene_capacidad(user, 'jor.ausencias.solicitar', empresa)
    propio = _perfil_propio(request)
    perfiles = None
    if gestiona:
        Perfil.asegurar_de(empresa)
        perfiles = Perfil.objects.filter(membresia__empresa=empresa, membresia__activa=True).select_related('membresia__user')
    form = None
    if gestiona or (puede_solicitar and propio):
        form = AusenciaForm(request.POST or None, perfiles=perfiles)
        if request.method == 'POST' and form.is_valid():
            a = form.save(commit=False)
            a.empresa, a.creada_por = empresa, user
            if gestiona:
                a.perfil = form.cleaned_data['perfil'] or propio
                a.estado = Ausencia.Estado.APROBADA
            else:
                a.perfil, a.estado = propio, Ausencia.Estado.PENDIENTE
            if a.perfil is None or a.perfil.empresa_id != empresa.pk:
                raise PermissionDenied
            a.save()
            if a.estado == Ausencia.Estado.PENDIENTE:
                notificar_a_varios(usuarios_con_capacidad(empresa, 'jor.ausencias.gestionar'), empresa,
                                   f'solicitó {a.get_tipo_display().lower()} '
                                   f'del {a.desde:%d/%m} al {a.hasta:%d/%m}.',
                                   url='/jornadas/ausencias/', actor=user)
            elif a.perfil.user.pk != user.pk:
                notificar(a.perfil.user, empresa, f'te registró una ausencia ({a.get_tipo_display().lower()}) '
                          f'del {a.desde:%d/%m} al {a.hasta:%d/%m}.',
                          url='/jornadas/ausencias/', actor=user)
            messages.success(request, 'Solicitud enviada.' if a.estado == Ausencia.Estado.PENDIENTE else 'Ausencia registrada.')
            return redirect('jor_diario:ausencias')
    qs = Ausencia.objects.filter(empresa=empresa).select_related('perfil__membresia__user')
    mias = qs.filter(perfil=propio) if propio else qs.none()
    return render(request, 'jor_diario/ausencias.html', {
        'form': form, 'gestiona': gestiona, 'mias': mias,
        'pendientes': qs.filter(estado=Ausencia.Estado.PENDIENTE) if gestiona else [],
        'proximas': qs.filter(estado=Ausencia.Estado.APROBADA, hasta__gte=timezone.localdate()).order_by('desde') if gestiona else []})


@acceso_modulo('jor', 'jor.ausencias.gestionar')
@require_POST
def ausencia_decidir(request, pk):
    a = get_object_or_404(Ausencia.objects.select_related('perfil__membresia__user'), pk=pk, empresa=request.empresa,
                          estado=Ausencia.Estado.PENDIENTE)
    aprobar = request.POST.get('decision') == 'aprobar'
    a.estado = Ausencia.Estado.APROBADA if aprobar else Ausencia.Estado.RECHAZADA
    a.decidida_por, a.decidida_en = request.user, timezone.now()
    a.save(update_fields=['estado', 'decidida_por', 'decidida_en'])
    notificar(a.perfil.user, request.empresa, f'{"aprobó" if aprobar else "rechazó"} tu solicitud de {a.get_tipo_display().lower()} '
              f'del {a.desde:%d/%m}.', url='/jornadas/ausencias/',
              actor=request.user)
    messages.success(request, 'Solicitud aprobada.' if aprobar else 'Solicitud rechazada.')
    return redirect('jor_diario:ausencias')


@acceso_modulo('jor')
@require_POST
def ausencia_eliminar(request, pk):
    """Quien gestiona borra cualquiera; el solicitante solo cancela la suya mientras está pendiente."""
    a = get_object_or_404(Ausencia, pk=pk, empresa=request.empresa)
    propia = a.perfil.membresia.user_id == request.user.pk and a.estado == Ausencia.Estado.PENDIENTE
    if not (_gestiona_ausencias(request) or propia):
        raise PermissionDenied
    a.delete()
    messages.success(request, 'Ausencia eliminada.')
    return redirect('jor_diario:ausencias')


# ── Calendario ───────────────────────────────────────────────────────────────────────────────────
@acceso_modulo('jor')
def calendario(request):
    puede = tiene_capacidad(request.user, 'jor.calendario.manage', request.empresa)
    form = None
    if puede:
        form = NotaForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            n = form.save(commit=False)
            n.empresa, n.creada_por = request.empresa, request.user
            n.save()
            messages.success(request, 'Nota agregada.')
            return redirect(f"{request.path}?mes={n.fecha:%Y-%m}")
    a, m = _mes(request)
    _, _, d_ini, d_fin = _rango_mes(a, m)
    hoy = timezone.localdate()
    dias = calendar.Calendar(firstweekday=0).monthdatescalendar(a, m)
    visibles = NotaCalendario.objects.filter(empresa=request.empresa, fecha__range=(dias[0][0], dias[-1][-1]))
    por_dia = {}
    for n in visibles:
        por_dia.setdefault(n.fecha, []).append(n)
    semanas = [[{'fecha': d, 'notas': por_dia.get(d, []), 'del_mes': d.month == m, 'hoy': d == hoy,
                 'finde': d.weekday() >= 5} for d in semana] for semana in dias]
    return render(request, 'jor_diario/calendario.html', {
        'notas': [n for n in visibles if d_ini <= n.fecha <= d_fin],
        'semanas': semanas, 'titulo_mes': date(a, m, 1), 'hoy_mes': f'{hoy:%Y-%m}',
        'form': form, 'nav': _mes_nav(a, m), 'puede': puede})


@acceso_modulo('jor', 'jor.calendario.manage')
@require_POST
def nota_eliminar(request, pk):
    n = get_object_or_404(NotaCalendario, pk=pk, empresa=request.empresa)
    mes = f'{n.fecha:%Y-%m}'
    n.delete()
    messages.success(request, 'Nota eliminada.')
    return redirect(f"{reverse('jor_diario:calendario')}?mes={mes}")
