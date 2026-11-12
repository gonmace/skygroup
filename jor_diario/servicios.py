"""Reglas de negocio de las jornadas (sin HTTP): las usan las vistas web y los comandos."""
from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import Jornada, ReporteDiario
from .verificacion import MOTIVOS, mejor_lectura

HORA_CIERRE_AUTO = time(17, 0)


def lleva_jornada(user, empresa):
    """¿Esta persona inicia y finaliza su propia jornada en `empresa`? Los superusuarios y los administradores de
    sistema de la empresa administran la plataforma: no tienen jornada, ausencias ni reportes propios."""
    from cuentas.capacidades import administra
    return not (user.is_superuser or administra(user, getattr(empresa, 'pk', None)))


class ErrorJornada(Exception):
    """Mensaje apto para mostrar a la persona."""

    def __init__(self, mensaje, **extra):
        super().__init__(mensaje)
        self.extra = extra


def jornada_en_curso(perfil):
    return perfil.jornadas.filter(estado=Jornada.Estado.EN_CURSO).order_by('-inicio').first()


def _texto_motivos(motivos):
    return ' '.join(MOTIVOS[m] for m in motivos if m in MOTIVOS)


def _ubicacion(lecturas):
    """Ubicación opcional: la lectura más precisa (sin validar contra ninguna sede) o un valor vacío si no hay ninguna."""
    return mejor_lectura(lecturas) or {'lat': None, 'lon': None, 'precision_m': None, 'n_lecturas': 0}


def _coord(v):
    return None if v is None else round(v, 6)


def _exigir_dispositivo_permitido(perfil, movil, accion):
    if movil and not perfil.puede_movil:
        raise ErrorJornada(f'Solo puedes {accion} tu jornada desde la computadora.', solo_pc=True)


def _exigir_motivo_cambio(equipo, cambio_equipo, motivo):
    """Un cambio de equipo no se bloquea: se avisa y se pide un motivo; la jornada queda a revisión."""
    if cambio_equipo and not motivo:
        reg = equipo.habitual.creado
        raise ErrorJornada(
            f'Estás usando un equipo distinto al registrado (desde el {reg:%d/%m/%Y}). Si continúas, tu jornada '
            'quedará pendiente de revisión. Indica el motivo.', cambio_equipo=True, motivo_requerido=True)


def iniciar(perfil, lecturas, proyecto=None, motivo='', ip=None, movil=False, equipo=None, cambio_equipo=False):
    """Se inicia con la sesión de la persona y su ubicación (opcional, sin geocerca). Desde un celular solo si
    `perfil.puede_movil`. Marcar desde un equipo distinto al habitual queda pendiente de revisión."""
    if not perfil.activo or not perfil.membresia.activa:
        raise ErrorJornada('Tu acceso a Asistencia está deshabilitado.')
    if proyecto is not None and proyecto.empresa_id != perfil.empresa_id:
        raise ErrorJornada('El proyecto no pertenece a esta empresa.')
    _exigir_dispositivo_permitido(perfil, movil, 'iniciar')
    res = _ubicacion(lecturas)
    motivo = (motivo or '').strip()[:300]
    _exigir_motivo_cambio(equipo, cambio_equipo, motivo)
    motivos = ['cambio_equipo'] if cambio_equipo else []
    estado_v = Jornada.Verificacion.EXCEPCION_PENDIENTE if motivos else Jornada.Verificacion.VERIFICADA
    try:
        with transaction.atomic():
            j = Jornada.objects.create(
                empresa_id=perfil.empresa_id, perfil=perfil, proyecto=proyecto, inicio=timezone.now(),
                lat_inicio=_coord(res['lat']), lon_inicio=_coord(res['lon']), precision_inicio=res['precision_m'],
                ip_inicio=ip or None, equipo_inicio=equipo, estado_verificacion=estado_v,
                motivo_excepcion=motivo if motivos else '',
                verificacion={'inicio': {'motivos': motivos, 'avisos': [], 'precision_m': res['precision_m'],
                                         'n_lecturas': res['n_lecturas'], 'origen': 'celular' if movil else 'pc'}})
    except IntegrityError:
        raise ErrorJornada('Ya tienes una jornada activa.')
    if estado_v == Jornada.Verificacion.EXCEPCION_PENDIENTE:
        _avisar_excepcion(j)
    return j


def revisores_cambio_equipo(empresa):
    """Usuarios que revisan los cambios de equipo, según `ConfigJornadas.revisa_cambio_equipo`."""
    from cuentas.capacidades import administra, usuarios_con_capacidad
    from cuentas.models import User
    from jor_empleados.models import ConfigJornadas
    quien = ConfigJornadas.de(empresa).revisa_cambio_equipo
    usuarios = {}
    if quien in (ConfigJornadas.RevisaEquipo.ADMIN, ConfigJornadas.RevisaEquipo.AMBOS):
        for u in User.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(empresas_administradas=empresa)).distinct():
            usuarios[u.pk] = u
    if quien in (ConfigJornadas.RevisaEquipo.COORDINADOR, ConfigJornadas.RevisaEquipo.AMBOS):
        for u in usuarios_con_capacidad(empresa, 'jor.excepciones.gestionar'):
            if not (u.is_superuser or administra(u, empresa.pk)):     # los administradores son el otro grupo
                usuarios[u.pk] = u
    return list(usuarios.values())


def puede_revisar_equipo(user, empresa):
    return any(u.pk == user.pk for u in revisores_cambio_equipo(empresa))


def _avisar_excepcion(jornada):
    from notificaciones.services import notificar_a_varios
    revisores = [u for u in revisores_cambio_equipo(jornada.empresa) if u.pk != jornada.perfil.user.pk]
    notificar_a_varios(
        revisores, jornada.empresa, actor=jornada.perfil.user, url='/jornadas/excepciones/',
        mensaje=f'{jornada.perfil.nombre} marcó su jornada desde un equipo distinto al habitual: {jornada.motivo_excepcion}')


MIN_PALABRAS_REALIZADO, MIN_PALABRAS_PLANIFICADO = 10, 3  # con reporte obligatorio


@transaction.atomic
def finalizar(jornada_id, perfil, lecturas, realizado='', planificado='', ip=None, movil=False, equipo=None,
              cambio_equipo=False, motivo=''):
    """Cierra la jornada con la sesión de la persona y su ubicación (opcional, sin geocerca). Desde un celular
    solo si `perfil.puede_movil`. Cerrar desde un equipo distinto al habitual manda la jornada a revisión."""
    realizado, planificado = (realizado or '').strip(), (planificado or '').strip()
    _exigir_dispositivo_permitido(perfil, movil, 'finalizar')
    res = _ubicacion(lecturas)
    motivo = (motivo or '').strip()[:300]
    _exigir_motivo_cambio(equipo, cambio_equipo, motivo)
    motivos = ['cambio_equipo'] if cambio_equipo else []
    if perfil.exige_reporte:
        if not (realizado and planificado):
            raise ErrorJornada('Debes completar el reporte diario antes de finalizar.', reporte_requerido=True)
        if len(realizado.split()) < MIN_PALABRAS_REALIZADO:
            raise ErrorJornada(f'Las actividades realizadas deben tener al menos {MIN_PALABRAS_REALIZADO} palabras.',
                               reporte_requerido=True)
        if len(planificado.split()) < MIN_PALABRAS_PLANIFICADO:
            raise ErrorJornada(f'Las actividades planificadas deben tener al menos {MIN_PALABRAS_PLANIFICADO} palabras.',
                               reporte_requerido=True)
    jornada = (Jornada.objects.select_for_update()
               .filter(pk=jornada_id, perfil=perfil, estado=Jornada.Estado.EN_CURSO).first())
    if jornada is None:
        raise ErrorJornada('No se encontró la jornada activa.')
    fin = timezone.now()
    jornada.fin, jornada.estado = fin, Jornada.Estado.COMPLETADA
    jornada.duracion_min = int((fin - jornada.inicio).total_seconds() // 60)
    jornada.lat_fin, jornada.lon_fin = _coord(res['lat']), _coord(res['lon'])
    jornada.precision_fin, jornada.ip_fin, jornada.equipo_fin = res['precision_m'], ip or None, equipo
    jornada.verificacion = {**jornada.verificacion, 'fin': {
        'motivos': motivos, 'avisos': [], 'precision_m': res['precision_m'], 'n_lecturas': res['n_lecturas'],
        'origen': 'celular' if movil else 'pc'}}
    # Un cambio de equipo al cerrar se revisa aunque el inicio ya estuviera aprobado: la aprobación anterior no lo cubre.
    pendiente = bool(motivos) and jornada.estado_verificacion in (
        Jornada.Verificacion.VERIFICADA, Jornada.Verificacion.EXCEPCION_APROBADA)
    if pendiente:
        jornada.estado_verificacion = Jornada.Verificacion.EXCEPCION_PENDIENTE
        jornada.motivo_excepcion = f'Al finalizar: {motivo}'[:300]
        jornada.revisada_por, jornada.revisada_en = None, None
    jornada.save()
    if realizado or planificado:
        reporte = ReporteDiario.objects.create(jornada=jornada, realizado=realizado, planificado=planificado)
        from jor_actividades.servicios import sincronizar_sin_fallar
        sincronizar_sin_fallar(reporte)
    if pendiente:
        transaction.on_commit(lambda: _avisar_excepcion(jornada))
    return jornada


@transaction.atomic
def decidir_excepcion(jornada_id, empresa, revisor, aprobar, adoptar_equipo=False):
    """Un revisor aprueba o rechaza una jornada pendiente (cambio de equipo, o excepciones históricas de ubicación).
    Con `adoptar_equipo`, al aprobar, el equipo usado pasa a ser el habitual."""
    j = (Jornada.objects.select_for_update().select_related('perfil__membresia__user', 'empresa')
         .filter(pk=jornada_id, empresa=empresa, estado_verificacion=Jornada.Verificacion.EXCEPCION_PENDIENTE).first())
    if j is None:
        raise ErrorJornada('Esa excepción ya no está pendiente.')
    if j.perfil.user.pk == revisor.pk:
        raise ErrorJornada('No puedes decidir tu propia excepción.')
    cambio = 'cambio_equipo' in (j.verificacion.get('inicio', {}).get('motivos', []) + j.verificacion.get('fin', {}).get('motivos', []))
    if cambio and not puede_revisar_equipo(revisor, empresa):
        raise ErrorJornada('Los cambios de equipo los revisa quien se indicó en la configuración de Jornadas.')
    j.estado_verificacion = Jornada.Verificacion.EXCEPCION_APROBADA if aprobar else Jornada.Verificacion.RECHAZADA
    j.revisada_por, j.revisada_en = revisor, timezone.now()
    campos = ['estado_verificacion', 'revisada_por', 'revisada_en']
    if not aprobar and j.estado == Jornada.Estado.EN_CURSO:
        # Una jornada rechazada no puede quedar abierta bloqueando que la persona marque de nuevo.
        j.fin, j.estado, j.duracion_min = timezone.now(), Jornada.Estado.INCOMPLETA, 0
        campos += ['fin', 'estado', 'duracion_min']
    j.save(update_fields=campos)
    if aprobar and adoptar_equipo:
        from jor_empleados import equipos
        for eq in (j.equipo_fin, j.equipo_inicio):
            if eq is not None and not eq.activo:
                equipos.adoptar(eq)
                break
    from mje_mensajes.servicios import aviso_sistema
    aviso_sistema(j.empresa, j.perfil.user,
                  f'Tu jornada del {timezone.localtime(j.inicio):%d/%m/%Y} fue {"aprobada" if aprobar else "rechazada"} '
                  f'por {revisor}.', url='/jornadas/')
    return j


def cerrar_vencidas(ahora=None, empresa=None):
    """Cierra como INCOMPLETA toda jornada abierta que empezó antes del día actual: fin = 17:00 de su día
    (o un minuto después del inicio si empezó más tarde) y avisa a la persona. Devuelve cuántas cerró."""
    ahora = timezone.localtime(ahora or timezone.now())
    hoy_inicio = timezone.make_aware(datetime.combine(ahora.date(), time.min))
    qs = Jornada.objects.filter(estado=Jornada.Estado.EN_CURSO, inicio__lt=hoy_inicio).select_related(
        'perfil__membresia__user', 'empresa')
    if empresa is not None:
        qs = qs.filter(empresa=empresa)
    cerradas = 0
    for j in qs:
        with transaction.atomic():
            j = Jornada.objects.select_for_update().get(pk=j.pk)
            if j.estado != Jornada.Estado.EN_CURSO:
                continue
            inicio_local = timezone.localtime(j.inicio)
            fin = timezone.make_aware(datetime.combine(inicio_local.date(), HORA_CIERRE_AUTO))
            if j.inicio >= fin:
                fin = j.inicio + timedelta(minutes=1)
            j.fin, j.estado, j.cierre_auto = fin, Jornada.Estado.INCOMPLETA, True
            j.duracion_min = max(1, int((fin - j.inicio).total_seconds() // 60))
            j.save(update_fields=['fin', 'estado', 'cierre_auto', 'duracion_min'])
        from mje_mensajes.servicios import aviso_sistema
        aviso_sistema(j.empresa, j.perfil.membresia.user,
                      f'Tu jornada del {inicio_local:%d/%m/%Y} quedó abierta y se cerró automáticamente a las 17:00.',
                      url='/jornadas/')
        cerradas += 1
    return cerradas
