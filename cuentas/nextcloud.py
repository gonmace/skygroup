"""Inicio de sesión con Nextcloud (OAuth2 «authorization code»). Solo entra a cuentas ya vinculadas por uid."""
import ipaddress
import logging
import socket
from urllib.parse import quote, urlsplit

import requests
from django.conf import settings
from django.urls import get_script_prefix, reverse, set_script_prefix
from django.utils.http import urlencode

from empresas.tenancy import _state, site_url

log = logging.getLogger(__name__)
TIMEOUT = 15


class NextcloudError(Exception):
    pass


def _ips(host):
    return {ai[4][0] for ai in socket.getaddrinfo(host, None)}


def validar_servidor(url):
    """Lanza NextcloudError si `url` no es un servidor público por https. Evita que la configuración use al servidor
    para consultar su red interna (SSRF). En DEBUG se admiten http y redes privadas (desarrollo local)."""
    partes = urlsplit(url or '')
    if partes.scheme not in (('https', 'http') if settings.DEBUG else ('https',)) or not partes.hostname:
        raise NextcloudError('La URL de Nextcloud debe empezar por https://')
    if partes.username or partes.password:
        raise NextcloudError('La URL de Nextcloud no puede incluir usuario ni contraseña.')
    if settings.DEBUG:
        return
    try:
        ips = _ips(partes.hostname)
    except OSError as e:
        raise NextcloudError('No se pudo resolver el servidor de Nextcloud.') from e
    for ip in ips:
        a = ipaddress.ip_address(ip.split('%')[0])
        if not a.is_global or a.is_multicast:
            raise NextcloudError('La URL de Nextcloud apunta a una red privada o reservada.')


def redirect_uri(request):
    """Fija y sin `/<slug>/`: debe coincidir exactamente con la registrada en Nextcloud."""
    base = site_url() or f'{request.scheme}://{request.get_host()}'
    actual = get_script_prefix()
    set_script_prefix(getattr(_state, 'root_prefix', None) or '/')
    try:
        return base + reverse('cuentas:nextcloud_callback')
    finally:
        set_script_prefix(actual)


def url_autorizar(config, request, state):
    params = urlencode({'response_type': 'code', 'client_id': config.client_id,
                        'redirect_uri': redirect_uri(request), 'state': state})
    return f'{config.servidor_url}/apps/oauth2/authorize?{params}'


def canjear_codigo(config, request, code):
    """Devuelve (access_token, uid de Nextcloud)."""
    try:
        validar_servidor(config.servidor_url)      # se revalida en cada petición: el DNS pudo cambiar tras guardarla
        r = requests.post(f'{config.servidor_url}/apps/oauth2/api/v1/token', data={
            'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri(request),
            'client_id': config.client_id, 'client_secret': config.client_secret}, timeout=TIMEOUT,
            allow_redirects=False)
        r.raise_for_status()
        datos = r.json()
    except (requests.RequestException, ValueError, NextcloudError) as e:
        log.warning('Nextcloud: fallo al canjear el código: %s', e)
        raise NextcloudError from e
    token, uid = datos.get('access_token', ''), datos.get('user_id', '')
    if not token or not uid:
        raise NextcloudError
    return token, uid


def buscar_usuario(empresa, uid):
    """Cuenta vinculada a ese usuario de Nextcloud EN ESA EMPRESA (`NextcloudVinculo`). No crea ni vincula nada. Las cuentas con privilegios (staff/superusuario) nunca entran por Nextcloud.

    No se vincula por correo: el correo de Nextcloud lo puede editar cada persona sin verificarlo, así que
    permitiría tomar la cuenta de otro. El vínculo lo hace la propia persona con su sesión iniciada
    (`views.nextcloud_vincular`), el alta automática o un administrador a mano en el admin de Django."""
    from .models import NextcloudVinculo
    if not uid:
        return None
    v = (NextcloudVinculo.objects.filter(empresa=empresa, uid=uid, user__is_active=True, user__is_deleted=False,
                                          user__is_staff=False, user__is_superuser=False)
         .select_related('user').first())
    return v.user if v else None


def _solo_de(user, empresa):
    """True si la cuenta es miembro activo de `empresa` y de ninguna otra: una cuenta compartida entre empresas es global
    y un Nextcloud de UNA empresa no puede declararla suya (se vincula a mano desde su sesión)."""
    from .models import Membresia
    empresas = set(Membresia.objects.filter(user=user).values_list('empresa_id', flat=True))
    return empresas == {empresa.pk} and Membresia.objects.filter(user=user, empresa=empresa, activa=True).exists()


def enlazar_existente(empresa, uid):
    """Vincula, en el primer ingreso, la cuenta que un administrador YA dio de alta en la empresa. No crea nada.

    Solo si el uid de Nextcloud tiene forma de correo (lo fija el administrador del servidor y la persona no puede
    cambiarlo) y es el de una cuenta común con membresía activa en la empresa y sin otro vínculo ahí. Las cuentas con
    privilegios (staff/superusuario) nunca se enlazan solas. Devuelve el usuario o None."""
    from .models import Membresia, NextcloudVinculo, User
    email = (uid or '').strip().lower()
    if '@' not in email:
        return None
    user = User.objects.filter(email__iexact=email, is_active=True, is_deleted=False,
                               is_superuser=False, is_staff=False).first()
    if (user is None or not _solo_de(user, empresa)
            or NextcloudVinculo.objects.filter(empresa=empresa, user=user).exists()
            or NextcloudVinculo.objects.filter(empresa=empresa, uid=uid).exists()):
        return None
    NextcloudVinculo.objects.create(empresa=empresa, user=user, uid=uid)
    return user


def perfil(config, uid, token):
    """{'nombre', 'email', 'grupos'} del usuario según la API OCS de Nextcloud (vacíos si no responde)."""
    try:
        validar_servidor(config.servidor_url)
        r = requests.get(f'{config.servidor_url}/ocs/v1.php/cloud/users/{quote(uid, safe="")}?format=json',
                         headers={'OCS-APIREQUEST': 'true', 'Authorization': f'Bearer {token}'}, timeout=10,
                         allow_redirects=False)
        datos = (r.json().get('ocs', {}).get('data', {}) or {}) if r.status_code == 200 else {}
    except (requests.RequestException, ValueError, NextcloudError):
        datos = {}
    return {'nombre': datos.get('displayname') or '', 'email': (datos.get('email') or '').strip(),
            'grupos': datos.get('groups') or []}


def alta_automatica(config, uid, datos):
    """Crea la cuenta de quien entra por primera vez a la empresa de `config`. Devuelve (user, None) o (None, motivo).

    Solo se crea si el uid tiene forma de correo (lo fija el administrador de Nextcloud y la persona no puede
    cambiarlo); el correo del perfil nunca se usa. El cargo sale de la regla de dominio de la empresa (`DominioPermitido`); los
    miembros del grupo administrador de Nextcloud entran como Coordinador. Nunca se toma una cuenta existente con
    privilegios ni una ya vinculada a otro usuario de Nextcloud."""
    from django.db import transaction

    from .models import CorreoBloqueado, DominioPermitido, Membresia, NextcloudVinculo, RolEmpresa, User
    from .registro import DOMINIOS_PUBLICOS, dominio_de
    from .roles import RolBase
    from .services import agregar_miembro

    empresa = config.empresa
    if '@' not in uid:     # el correo del perfil lo edita cada persona sin verificarlo: no sirve para decidir cargo ni cuenta
        return None, ('Tu usuario de Nextcloud no es un correo, así que no se puede crear tu cuenta automáticamente. '
                      'Pide a un administrador que te dé acceso.')
    email = uid.strip().lower()
    dominio = dominio_de(email)
    if not dominio or dominio in DOMINIOS_PUBLICOS:
        return None, 'Tu cuenta de Nextcloud no tiene un correo de empresa. Pide a un administrador que te dé acceso.'
    regla = DominioPermitido.objects.filter(empresa=empresa, activo=True, dominio__iexact=dominio).select_related('rol').first()
    if regla is None or CorreoBloqueado.objects.filter(empresa=empresa, email__iexact=email).exists():
        return None, 'Tu correo no está autorizado para el acceso automático. Pide a un administrador que te dé acceso.'
    admin = bool(config.grupo_admin and config.grupo_admin in datos['grupos'])
    with transaction.atomic():
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            nombre, _, apellido = (datos['nombre'] or '').partition(' ')
            user = User(email=email, first_name=nombre, last_name=apellido)
            user.set_unusable_password()
            user.save()
        elif (not user.is_active or user.is_deleted or user.is_superuser or user.is_staff or uid.lower() != email
              or not _solo_de(user, empresa)
              or NextcloudVinculo.objects.filter(empresa=empresa, user=user).exclude(uid=uid).exists()):
            return None, ('Ya existe una cuenta con tu correo. Entra con tu correo y contraseña y pulsa '
                          '«Vincular Nextcloud» en el menú de tu usuario.')
        NextcloudVinculo.objects.get_or_create(empresa=empresa, user=user, defaults={'uid': uid})
        if not Membresia.objects.filter(user=user, empresa=empresa).exists():
            rol = regla.rol
            if admin:
                rol = (RolEmpresa.objects.filter(empresa=empresa, rol_base=RolBase.COORDINADOR, activo=True)
                       .order_by('orden', 'id').first() or rol)
            agregar_miembro(user, empresa, rol)
    return user, None
