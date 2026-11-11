"""Passkey (WebAuthn) del celular con el que cada persona marca su jornada.

El celular guarda la clave privada y la desbloquea con huella/PIN del propio teléfono; al servidor solo llega la
clave pública y la firma de cada marcación. Cada «challenge» vive en la sesión, es de un solo uso y caduca."""
import logging
import secrets
import time

from django.core import signing
from django.core.cache import cache
from django.utils import timezone
from webauthn import (base64url_to_bytes, generate_authentication_options, generate_registration_options,
                      options_to_json, verify_authentication_response, verify_registration_response)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (AuthenticatorAttachment, PublicKeyCredentialHint, AuthenticatorSelectionCriteria,
                                      PublicKeyCredentialDescriptor, ResidentKeyRequirement,
                                      UserVerificationRequirement)

from .models import DispositivoMarcacion

logger = logging.getLogger(__name__)

CLAVE_SESION = 'jor_passkey_challenge'
TTL_S = 180   # el challenge vive mientras se firma (con QR desde el PC tarda) y se leen las 3 lecturas de GPS


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


# ── Enlace de vinculación (un solo uso) ────────────────────────────────────────────────────────────
# Se genera desde la sesión del computador y se abre en el celular SIN iniciar sesión allí: es firmado, caduca a los
# ENLACE_TTL_S y se invalida al vincular (o al generar otro: solo vale el último de cada persona).
ENLACE_TTL_S = 600
_SAL_ENLACE = 'jor-vincular-celular'


def _clave_enlace(perfil_id):
    return f'jor:vinc:vigente:{perfil_id}'


def generar_enlace(perfil):
    """Token firmado que autoriza vincular UN celular a `perfil`. Invalida el anterior de esa persona."""
    if dispositivo_activo(perfil):
        raise ErrorPasskey('Ya tienes un celular vinculado. Pide a un administrador que lo libere para cambiarlo.')
    nonce = secrets.token_urlsafe(12)
    cache.set(_clave_enlace(perfil.pk), nonce, ENLACE_TTL_S + 30)
    return signing.dumps({'p': perfil.pk, 'n': nonce}, salt=_SAL_ENLACE)


def perfil_de_enlace(token):
    """Perfil al que pertenece un enlace vigente; ErrorPasskey si caducó, se usó o fue reemplazado."""
    from .models import Perfil
    try:
        d = signing.loads(token, salt=_SAL_ENLACE, max_age=ENLACE_TTL_S)
        vigente = cache.get(_clave_enlace(d['p']))
    except (signing.BadSignature, KeyError, TypeError):
        raise ErrorPasskey('Este enlace no es válido.')
    if not vigente or vigente != d['n']:
        raise ErrorPasskey('Este enlace ya se usó o caducó. Genera uno nuevo desde tu computador.')
    perfil = Perfil.objects.select_related('membresia__user', 'membresia__empresa').filter(pk=d['p']).first()
    if perfil is None or not perfil.activo or not perfil.membresia.activa:
        raise ErrorPasskey('Este enlace no es válido.')
    return perfil


def consumir_enlace(perfil):
    cache.delete(_clave_enlace(perfil.pk))


def dispositivo_activo(perfil):
    return perfil.dispositivos.filter(activo=True).first()


def opciones_registro(request, perfil, desde_pc=False):
    if dispositivo_activo(perfil):
        raise ErrorPasskey('Ya tienes un celular vinculado. Pide a un administrador que lo libere para cambiarlo.')
    rp_id, _ = _rp(request)
    # Desde un computador el navegador muestra un QR y es el CELULAR (su llavero: Google/iCloud) quien crea y guarda la
    # passkey («hybrid»): no puede restringirse a `platform`, que en el PC solo ofrece Windows Hello/Touch ID.
    opciones = generate_registration_options(
        rp_id=rp_id, rp_name=perfil.membresia.empresa.nombre, user_id=str(perfil.pk).encode(),
        user_name=perfil.user.email, user_display_name=perfil.nombre,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.CROSS_PLATFORM if desde_pc else AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.REQUIRED),
        hints=[PublicKeyCredentialHint.HYBRID] if desde_pc else None)
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
    except (InvalidRegistrationResponse, ValueError, KeyError, TypeError) as e:
        logger.warning('Registro de passkey rechazado (rp_id=%s, origen=%s): %s', rp_id, origen, e)
        raise ErrorPasskey('No se pudo verificar el celular. Inténtalo de nuevo.')
    return DispositivoMarcacion.objects.create(
        perfil=perfil, credential_id=v.credential_id, public_key=v.credential_public_key, sign_count=v.sign_count,
        nombre=(nombre or '').strip()[:80], user_agent=request.META.get('HTTP_USER_AGENT', '')[:300])


def opciones_autenticacion(request, perfil, desde_pc=False):
    dispositivo = dispositivo_activo(perfil)
    if dispositivo is None:
        raise ErrorPasskey('Vincula tu celular para poder marcar tu jornada.')
    rp_id, _ = _rp(request)
    opciones = generate_authentication_options(
        rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED,
        allow_credentials=[PublicKeyCredentialDescriptor(id=bytes(dispositivo.credential_id))])
    _guardar_challenge(request, opciones.challenge, 'marca')
    d = opciones_a_dict(opciones)
    if desde_pc:
        d['hints'] = ['hybrid']   # en un computador: ofrecer el QR para firmar con el celular vinculado
    return d


def verificar_aserto(request, perfil, credencial):
    """Valida la firma del celular vinculado y devuelve su `DispositivoMarcacion`."""
    challenge = _tomar_challenge(request, 'marca')
    if not isinstance(credencial, dict):
        raise ErrorPasskey('Verificación no válida.')
    # No se filtra por `authenticatorAttachment`: firmar desde el computador con el QR del celular, o con una passkey
    # que el llavero del celular reporta como «cross-platform», es legítimo. La identidad la fija la credencial
    # registrada: solo su clave pública verifica la firma.
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
