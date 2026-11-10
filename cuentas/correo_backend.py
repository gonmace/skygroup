"""Envío de correo configurable desde la plataforma.

`EMAIL_BACKEND` apunta a `EmailBackend`: si el superusuario activó un servidor SMTP en Plataforma → Correo
(`CorreoConfig`) se envía por él; si no, por el backend base del servidor (`EMAIL_BACKEND_BASE`: SMTP del .env o
consola). La configuración se lee de la BD con caché y a prueba de fallos, igual que la de media."""
import logging
import smtplib
import socket
import ssl

from django.conf import settings
from django.core.cache import cache
from django.core.mail.backends.base import BaseEmailBackend
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)
CACHE_KEY = 'correo:config'
CACHE_TTL = 300
TIMEOUT = 15
_SIN_CONFIG = 'sin-config'      # marca de «no hay configuración activa» (distinta de «aún no cacheado»)


def invalidar_config():
    try:
        cache.delete(CACHE_KEY)
    except Exception:
        pass


def _a_dict(c):
    return {'host': c.host, 'puerto': c.puerto, 'seguridad': c.seguridad, 'usuario': c.usuario, 'password': c.password,
            'remitente': c.remitente, 'remitente_nombre': c.remitente_nombre}


def config_activa():
    """Configuración SMTP activa y completa (dict), o None. Cacheada; si la BD falla, None (se usa el .env)."""
    from django.db import DatabaseError, transaction
    try:
        valor = cache.get(CACHE_KEY)
    except Exception:
        valor = None
    if valor is not None:
        return None if valor == _SIN_CONFIG else valor
    from .models import CorreoConfig
    try:
        with transaction.atomic():
            c = CorreoConfig.objects.first()
    except DatabaseError:
        return None
    cfg = _a_dict(c) if (c is not None and c.activo and c.completa) else None
    try:
        cache.set(CACHE_KEY, cfg if cfg is not None else _SIN_CONFIG, CACHE_TTL)
    except Exception:
        pass
    return cfg


def formatear_remitente(cfg):
    nombre = (cfg.get('remitente_nombre') or '').replace('<', '').replace('>', '').replace('\n', ' ').strip()
    return f'{nombre} <{cfg["remitente"]}>' if nombre else cfg['remitente']


def remitente_por_defecto():
    """Remitente cuando la empresa no define uno propio: el de la configuración activa, o DEFAULT_FROM_EMAIL."""
    cfg = config_activa()
    return formatear_remitente(cfg) if cfg else settings.DEFAULT_FROM_EMAIL


def _backend_smtp(cfg, fail_silently=False):
    from django.core.mail.backends.smtp import EmailBackend as SMTP
    return SMTP(host=cfg['host'], port=cfg['puerto'], username=cfg.get('usuario') or '', password=cfg.get('password') or '',
                use_tls=cfg['seguridad'] == 'starttls', use_ssl=cfg['seguridad'] == 'ssl', timeout=TIMEOUT,
                fail_silently=fail_silently)


class EmailBackend(BaseEmailBackend):
    """Delega en el SMTP configurado en la plataforma o, si no hay, en `settings.EMAIL_BACKEND_BASE`."""

    def send_messages(self, email_messages):
        cfg = config_activa()
        if cfg is None:
            base = import_string(getattr(settings, 'EMAIL_BACKEND_BASE', 'django.core.mail.backends.console.EmailBackend'))
            return base(fail_silently=self.fail_silently).send_messages(email_messages)
        for m in email_messages:     # los correos con el remitente por defecto del servidor salen con el configurado
            if m.from_email == settings.DEFAULT_FROM_EMAIL:
                m.from_email = formatear_remitente(cfg)
        return _backend_smtp(cfg, self.fail_silently).send_messages(email_messages)


# ── Pruebas desde Plataforma → Correo ─────────────────────────────────────────────────────────────

def _explicar(e):
    """Mensaje claro para el error de una prueba SMTP."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return 'El servidor rechazó el usuario o la contraseña. Muchos proveedores piden una contraseña de aplicación.'
    if isinstance(e, smtplib.SMTPSenderRefused):
        return 'El servidor no acepta ese remitente. Usa un correo de su dominio.'
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return 'El servidor rechazó el destinatario.'
    if isinstance(e, (socket.timeout, TimeoutError)):
        return 'El servidor no respondió a tiempo. Revisa el servidor y el puerto (y que el VPS pueda salir a ese puerto).'
    if isinstance(e, ssl.SSLError):
        return 'Falló el cifrado. Prueba con otro tipo: STARTTLS suele ir con el puerto 587 y SSL/TLS con el 465.'
    if isinstance(e, smtplib.SMTPException):          # antes que OSError: SMTPException hereda de él
        return f'El servidor respondió con un error: {e}'
    if isinstance(e, (socket.gaierror, ConnectionRefusedError, OSError)):
        return 'No se pudo conectar. Revisa el nombre del servidor y el puerto.'
    return f'Error inesperado: {e}'


def probar_conexion(cfg):
    """Abre la conexión SMTP (cifrado + usuario/contraseña) SIN enviar nada. Devuelve (ok, mensaje)."""
    if not cfg.get('host'):
        return False, 'Falta el servidor SMTP.'
    backend = _backend_smtp(cfg)
    try:
        backend.open()
    except Exception as e:      # noqa: BLE001 — cualquier fallo de red/SMTP se explica a la persona
        logger.info('Prueba SMTP fallida: %s', e)
        return False, _explicar(e)
    finally:
        try:
            backend.close()
        except Exception:       # noqa: BLE001
            pass
    return True, 'Conexión correcta: el servidor aceptó el cifrado y las credenciales.'


def enviar_prueba(cfg, destino):
    """Envía un correo de prueba por la configuración dada. Devuelve (ok, mensaje)."""
    from django.core.mail import EmailMessage
    if not cfg.get('host') or not cfg.get('remitente'):
        return False, 'Falta el servidor SMTP o el correo del remitente.'
    mensaje = EmailMessage(
        'Prueba de correo de SkyGroup',
        'Si lees esto, el servidor SMTP de SkyGroup está bien configurado.\n\nEs solo un correo de prueba.',
        formatear_remitente(cfg), [destino], connection=_backend_smtp(cfg))
    try:
        mensaje.send()
    except Exception as e:      # noqa: BLE001
        logger.info('Prueba de envío SMTP fallida: %s', e)
        return False, _explicar(e)
    return True, f'Correo de prueba enviado a {destino}. Revisa la bandeja (y la carpeta de spam).'
