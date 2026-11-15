"""Correo por cierres automáticos repetidos de jornada. Corre dentro del cron (sin request)."""
import logging

from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone

from cuentas.correos import _remitente
from cuentas.models import CorreoConfig

log = logging.getLogger(__name__)

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
         'noviembre', 'diciembre']


def enviar_aviso_cierre_auto(jornada, n):
    """Avisa a la persona (con copia a RR. HH.) que su jornada se cerró sola por n-ésima vez en el mes.
    Un fallo de envío se registra y no interrumpe el cierre de las demás jornadas."""
    user = jornada.perfil.membresia.user
    if not user.email:
        return
    inicio = timezone.localtime(jornada.inicio)
    contexto = {'nombre': user.get_full_name() or user.email, 'fecha': f'{inicio:%d/%m/%Y}', 'n': n,
                'mes': f'{MESES[inicio.month - 1]} {inicio.year}'}
    asunto = ' '.join(render_to_string('jor_diario/email/cierre_auto_asunto.txt', contexto).split())
    cuerpo = render_to_string('jor_diario/email/cierre_auto.txt', contexto)
    copia = CorreoConfig.de().copia_rrhh_cierre_auto
    cc = [copia] if copia else []
    try:
        EmailMessage(asunto, cuerpo, _remitente(jornada.empresa), [user.email], cc=cc).send()
    except Exception:
        log.exception('No se pudo enviar el aviso de cierre automático a %s', user.email)
