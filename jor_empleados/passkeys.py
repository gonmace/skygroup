"""Passkey (WebAuthn) del celular con el que cada persona marca su jornada.

El celular guarda la clave privada y la desbloquea con huella/PIN del propio teléfono; al servidor solo llega la
clave pública y la firma de cada marcación. Cada «challenge» vive en la sesión, es de un solo uso y caduca."""
import time

from django.utils import timezone
from webauthn import (base64url_to_bytes, generate_authentication_options, generate_registration_options,
                      options_to_json, verify_authentication_response, verify_registration_response)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (AuthenticatorAttachment, AuthenticatorSelectionCriteria,
                                      PublicKeyCredentialDescriptor, ResidentKeyRequirement,
                                      UserVerificationRequirement)

from .models import DispositivoMarcacion

CLAVE_SESION = 'jor_passkey_challenge'
TTL_S = 90


class ErrorPasskey(Exception):
    """Mensaje apto para mostrar a la persona."""


def _rp(request):
    host = request.get_host()
    return host.split(':')[0], f'{"https" if request.is_secure() else "http"}://{host}'


def _guardar_challenge(request, challenge, uso):
    request.session[CLAVE_SESION] = {'c': bytes_to_base64url(challenge), 't': time.time(), 'u': uso}


def _tomar_challenge(request, uso):
    """Consume el challenge de la sesión (un solo uso)."""
    dato = request.session.pop(CLAVE_SESION, None)
    if not dato or dato.get('u') != uso or time.time() - dato.get('t', 0) > TTL_S:
        raise ErrorPasskey('La verificación caducó. Inténtalo de nuevo.')
    return base64url_to_bytes(dato['c'])


def dispositivo_activo(perfil):
    return perfil.dispositivos.filter(activo=True).first()


def opciones_registro(request, perfil):
    if dispositivo_activo(perfil):
        raise ErrorPasskey('Ya tienes un celular vinculado. Pide a un administrador que lo libere para cambiarlo.')
    rp_id, _ = _rp(request)
    opciones = generate_registration_options(
        rp_id=rp_id, rp_name=perfil.membresia.empresa.nombre, user_id=str(perfil.pk).encode(),
        user_name=perfil.user.email, user_display_name=perfil.nombre,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.REQUIRED))
    _guardar_challenge(request, opciones.challenge, 'registro')
    return opciones_a_dict(opciones)


def opciones_a_dict(opciones):
    import json
    return json.loads(options_to_json(opciones))


def registrar(request, perfil, credencial, nombre=''):
    challenge = _tomar_challenge(request, 'registro')
    if dispositivo_activo(perfil):
        raise ErrorPasskey('Ya tienes un celular vinculado.')
    rp_id, origen = _rp(request)
    try:
        v = verify_registration_response(credential=credencial, expected_challenge=challenge, expected_rp_id=rp_id,
                                         expected_origin=origen, require_user_verification=True)
    except (InvalidRegistrationResponse, ValueError, KeyError, TypeError):
        raise ErrorPasskey('No se pudo verificar el celular. Inténtalo de nuevo.')
    return DispositivoMarcacion.objects.create(
        perfil=perfil, credential_id=v.credential_id, public_key=v.credential_public_key, sign_count=v.sign_count,
        nombre=(nombre or '').strip()[:80], user_agent=request.META.get('HTTP_USER_AGENT', '')[:300])


def opciones_autenticacion(request, perfil):
    dispositivo = dispositivo_activo(perfil)
    if dispositivo is None:
        raise ErrorPasskey('Vincula tu celular para poder marcar tu jornada.')
    rp_id, _ = _rp(request)
    opciones = generate_authentication_options(
        rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED,
        allow_credentials=[PublicKeyCredentialDescriptor(id=bytes(dispositivo.credential_id))])
    _guardar_challenge(request, opciones.challenge, 'marca')
    return opciones_a_dict(opciones)


def verificar_aserto(request, perfil, credencial):
    """Valida la firma del celular vinculado y devuelve su `DispositivoMarcacion`."""
    challenge = _tomar_challenge(request, 'marca')
    if not isinstance(credencial, dict):
        raise ErrorPasskey('Verificación no válida.')
    if credencial.get('authenticatorAttachment') == 'cross-platform':
        raise ErrorPasskey('Marca desde el celular vinculado, no con un llavero o dispositivo externo.')
    try:
        id_cred = base64url_to_bytes(credencial.get('rawId') or credencial.get('id') or '')
    except Exception:
        raise ErrorPasskey('Verificación no válida.')
    dispositivo = perfil.dispositivos.filter(activo=True, credential_id=id_cred).first()
    if dispositivo is None:
        raise ErrorPasskey('Este celular no es el vinculado a tu cuenta.')
    rp_id, origen = _rp(request)
    try:
        v = verify_authentication_response(
            credential=credencial, expected_challenge=challenge, expected_rp_id=rp_id, expected_origin=origen,
            credential_public_key=bytes(dispositivo.public_key), credential_current_sign_count=dispositivo.sign_count,
            require_user_verification=True)
    except (InvalidAuthenticationResponse, ValueError, KeyError, TypeError):
        raise ErrorPasskey('No se pudo verificar tu identidad. Inténtalo de nuevo.')
    dispositivo.sign_count, dispositivo.ultimo_uso = v.new_sign_count, timezone.now()
    dispositivo.save(update_fields=['sign_count', 'ultimo_uso'])
    return dispositivo


def liberar(perfil, por):
    """Un administrador libera el celular vinculado (queda el registro) para que la persona vincule otro."""
    n = perfil.dispositivos.filter(activo=True).update(activo=False, liberado_por=por, liberado_en=timezone.now())
    return n
