"""Reglas de negocio de las jornadas (sin HTTP): las usan las vistas web y los comandos."""
from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Jornada, ReporteDiario
from .verificacion import MOTIVOS, verificar_presencia

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


def _evaluar(perfil, dispositivo, lecturas):
    """Identidad (passkey ya verificada por la vista) + presencia. → (resultado, motivos)."""
    if dispositivo is None or not dispositivo.activo or dispositivo.perfil_id != perfil.pk:
        raise ErrorJornada('Vincula tu celular para poder marcar tu jornada.', dispositivo_requerido=True)
    res = verificar_presencia(perfil.membresia.sede, lecturas)
    return res, list(res['motivos'])


def _texto_motivos(motivos):
    return ' '.join(MOTIVOS[m] for m in motivos if m in MOTIVOS)


def _coords(res):
    if res['lat'] is None:
        return None, None
    return round(res['lat'], 6), round(res['lon'], 6)


def iniciar(perfil, dispositivo, lecturas, proyecto=None, motivo='', ip=None, origen=''):
    """Se inicia con el passkey del celular vinculado, firmando en el propio celular o desde un computador (QR);
    en ambos casos la ubicación es obligatoria. `origen` ('pc'|'celular') solo informa a quien revisa."""
    if not perfil.activo or not perfil.membresia.activa:
        raise ErrorJornada('Tu acceso a Asistencia está deshabilitado.')
    if proyecto is not None and proyecto.empresa_id != perfil.empresa_id:
        raise ErrorJornada('El proyecto no pertenece a esta empresa.')
    res, motivos = _evaluar(perfil, dispositivo, lecturas)
    if res['lat'] is None:   # sin ubicación no se inicia, ni siquiera como excepción
        raise ErrorJornada('No se pudo leer tu ubicación. Revisa el permiso del navegador e inténtalo de nuevo.',
                           ubicacion_requerida=True)
    motivo = (motivo or '').strip()[:300]
    estado_v = Jornada.Verificacion.VERIFICADA
    if motivos:
        if not perfil.puede_excepcion:
            raise ErrorJornada(f'No se pudo verificar tu presencia. {_texto_motivos(motivos)}')
        if not motivo:
            raise ErrorJornada(f'No se pudo verificar tu presencia. {_texto_motivos(motivos)} '
                               'Indica el motivo para enviarla a revisión.', motivo_requerido=True)
        estado_v = Jornada.Verificacion.EXCEPCION_PENDIENTE
    lat, lon = _coords(res)
    try:
        with transaction.atomic():
            j = Jornada.objects.create(
                empresa_id=perfil.empresa_id, perfil=perfil, proyecto=proyecto, inicio=timezone.now(),
                lat_inicio=lat, lon_inicio=lon, precision_inicio=res['precision_m'], ip_inicio=ip or None,
                dispositivo=dispositivo, estado_verificacion=estado_v, motivo_excepcion=motivo if motivos else '',
                verificacion={'inicio': {k: res[k] for k in ('motivos', 'avisos', 'distancia_m', 'precision_m')}
                              | {'motivos': motivos, 'origen': origen}})
    except IntegrityError:
        raise ErrorJornada('Ya tienes una jornada activa.')
    if estado_v == Jornada.Verificacion.EXCEPCION_PENDIENTE:
        _avisar_excepcion(j)
    return j


def _avisar_excepcion(jornada):
    from cuentas.capacidades import usuarios_con_capacidad
    from notificaciones.services import notificar_a_varios
    revisores = [u for u in usuarios_con_capacidad(jornada.empresa, 'jor.excepciones.gestionar')
                 if u.pk != jornada.perfil.user.pk]
    notificar_a_varios(
        revisores, jornada.empresa, actor=jornada.perfil.user, url='/jornadas/excepciones/',
        mensaje=f'{jornada.perfil.nombre} inició su jornada fuera de la sede y pide aprobación: {jornada.motivo_excepcion}')


MIN_PALABRAS_REALIZADO, MIN_PALABRAS_PLANIFICADO = 10, 3  # con reporte obligatorio


@transaction.atomic
def finalizar(jornada_id, perfil, dispositivo, lecturas, realizado='', planificado='', ip=None):
    """Cierra la jornada. Exige identidad (passkey) y ubicación legible; el resultado de la presencia al
    terminar queda registrado para quien revisa, pero no cambia el estado de verificación del inicio."""
    realizado, planificado = (realizado or '').strip(), (planificado or '').strip()
    sin_dispositivo = dispositivo is None
    if sin_dispositivo:
        # Desde un computador o sin celular vinculado se puede cerrar (nunca iniciar) sin passkey, pero la
        # ubicación es obligatoria; lo que no cuadre (fuera de sede, etc.) queda registrado para quien revisa.
        res = verificar_presencia(perfil.membresia.sede, lecturas)
        motivos = ['sin_passkey', *res['motivos']]
    else:
        res, motivos = _evaluar(perfil, dispositivo, lecturas)
    if res['lat'] is None:
        raise ErrorJornada('No se pudo leer tu ubicación. Revisa el permiso del navegador e inténtalo de nuevo.',
                           ubicacion_requerida=True)
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
    jornada.lat_fin, jornada.lon_fin = _coords(res)
    jornada.precision_fin, jornada.ip_fin = res['precision_m'], ip or None
    jornada.verificacion = {**jornada.verificacion, 'fin': {
        'motivos': motivos, 'avisos': res['avisos'], 'distancia_m': res['distancia_m'], 'precision_m': res['precision_m']}}
    jornada.save()
    if realizado or planificado:
        reporte = ReporteDiario.objects.create(jornada=jornada, realizado=realizado, planificado=planificado)
        from jor_actividades.servicios import sincronizar_sin_fallar
        sincronizar_sin_fallar(reporte)
    return jornada


@transaction.atomic
def decidir_excepcion(jornada_id, empresa, revisor, aprobar):
    """Un coordinador aprueba o rechaza una jornada iniciada fuera de la sede."""
    j = (Jornada.objects.select_for_update().select_related('perfil__membresia__user', 'empresa')
         .filter(pk=jornada_id, empresa=empresa, estado_verificacion=Jornada.Verificacion.EXCEPCION_PENDIENTE).first())
    if j is None:
        raise ErrorJornada('Esa excepción ya no está pendiente.')
    if j.perfil.user.pk == revisor.pk:
        raise ErrorJornada('No puedes decidir tu propia excepción.')
    j.estado_verificacion = Jornada.Verificacion.EXCEPCION_APROBADA if aprobar else Jornada.Verificacion.RECHAZADA
    j.revisada_por, j.revisada_en = revisor, timezone.now()
    campos = ['estado_verificacion', 'revisada_por', 'revisada_en']
    if not aprobar and j.estado == Jornada.Estado.EN_CURSO:
        # Una jornada rechazada no puede quedar abierta bloqueando que la persona marque de nuevo.
        j.fin, j.estado, j.duracion_min = timezone.now(), Jornada.Estado.INCOMPLETA, 0
        campos += ['fin', 'estado', 'duracion_min']
    j.save(update_fields=campos)
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
