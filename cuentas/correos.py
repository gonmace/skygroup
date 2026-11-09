"""Correos de alta de usuarios. Se arman DENTRO del request (así `reverse()` lleva el prefijo
`/<slug>/` de la empresa) y devuelven un callable para `transaction.on_commit`."""
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def _remitente(empresa):
    if empresa is not None and empresa.email_remitente:
        nombre = (empresa.email_remitente_nombre or '').replace('<', '').replace('>', '').replace('\n', ' ').strip()
        return f'{nombre} <{empresa.email_remitente}>' if nombre else empresa.email_remitente
    return settings.DEFAULT_FROM_EMAIL


def _enviar(request, plantilla, destino, empresa, extra):
    contexto = {
        'empresa': empresa,
        'site_name': empresa.marca if empresa is not None else 'SkyGroup',
        'dias_vigencia': settings.PASSWORD_RESET_TIMEOUT // 86400,
        **extra,
    }
    asunto = ' '.join(render_to_string(f'cuentas/email/{plantilla}_asunto.txt', contexto).split())
    cuerpo = render_to_string(f'cuentas/email/{plantilla}.txt', contexto)
    remitente = _remitente(empresa)
    return lambda: send_mail(asunto, cuerpo, remitente, [destino])


def preparar_invitacion(request, user, membresia):
    """Cuenta nueva: enlace para elegir contraseña. No usa PasswordResetForm: omite a los usuarios con
    contraseña inutilizable, que son justo los recién invitados."""
    enlace = request.build_absolute_uri(reverse('cuentas:password_reset_confirmar', kwargs={
        'uidb64': urlsafe_base64_encode(force_bytes(user.pk)), 'token': default_token_generator.make_token(user)}))
    return _enviar(request, 'invitacion', user.email, membresia.empresa, {
        'enlace': enlace, 'invitador': request.user.get_full_name() or request.user.email,
        'cargo': membresia.rol.nombre,
    })


def preparar_invitacion_admin(request, user, empresa):
    """Administrador de sistema nuevo (sin membresía): mismo enlace para elegir contraseña, con «Administrador» como cargo."""
    enlace = request.build_absolute_uri(reverse('cuentas:password_reset_confirmar', kwargs={
        'uidb64': urlsafe_base64_encode(force_bytes(user.pk)), 'token': default_token_generator.make_token(user)}))
    return _enviar(request, 'invitacion', user.email, empresa, {
        'enlace': enlace, 'invitador': request.user.get_full_name() or request.user.email, 'cargo': 'Administrador',
    })


def preparar_aviso_agregado(request, user, membresia):
    """Cuenta existente: se le avisa que fue agregada a la empresa."""
    return _enviar(request, 'agregado', user.email, membresia.empresa, {
        'enlace': request.build_absolute_uri(reverse('cuentas:login')),
        'invitador': request.user.get_full_name() or request.user.email, 'cargo': membresia.rol.nombre,
    })


def preparar_confirmacion_registro(request, email, empresa, token):
    enlace = request.build_absolute_uri(reverse('cuentas:registro_confirmar', kwargs={'token': token}))
    return _enviar(request, 'registro', email, empresa, {'enlace': enlace})
