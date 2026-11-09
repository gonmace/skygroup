"""Alta automática por dominio de correo: reglas, token firmado y creación de la cuenta."""
from django.core import signing
from django.db import transaction

from .models import CorreoBloqueado, DominioPermitido, Membresia, User
from .services import agregar_miembro

SALT = 'cuentas.registro'
TOKEN_VIDA = 24 * 3600  # segundos

# Dominios abiertos a cualquiera: permitirlos equivaldría a registro libre.
DOMINIOS_PUBLICOS = frozenset({
    'gmail.com', 'googlemail.com', 'hotmail.com', 'hotmail.es', 'outlook.com', 'outlook.es', 'live.com',
    'msn.com', 'yahoo.com', 'yahoo.es', 'ymail.com', 'icloud.com', 'me.com', 'mac.com', 'aol.com',
    'proton.me', 'protonmail.com', 'gmx.com', 'gmx.net', 'zoho.com', 'mail.com',
})


def normalizar_dominio(texto):
    return (texto or '').strip().lower().lstrip('@')


def dominio_de(email):
    return email.rsplit('@', 1)[-1].strip().lower() if '@' in (email or '') else ''


def dominio_permitido(empresa, email):
    """`DominioPermitido` que habilita a `email` en `empresa`, o None si no puede darse de alta solo
    (dominio no permitido, correo bloqueado o cuenta bloqueada globalmente)."""
    email = (email or '').strip().lower()
    if CorreoBloqueado.objects.filter(empresa=empresa, email__iexact=email).exists():
        return None
    if User.objects.filter(email__iexact=email, is_active=False).exists():
        return None
    return (DominioPermitido.objects.filter(empresa=empresa, activo=True, dominio__iexact=dominio_de(email))
            .select_related('rol').first())


def hay_dominios(empresa):
    return DominioPermitido.objects.filter(empresa=empresa, activo=True).exists()


def token_registro(email, empresa, first_name='', last_name=''):
    return signing.dumps({'e': email.strip().lower(), 'c': empresa.pk, 'n': first_name, 'a': last_name}, salt=SALT)


def leer_token(token, empresa):
    """Datos del token o None si está vencido, alterado o es de otra empresa."""
    try:
        datos = signing.loads(token, salt=SALT, max_age=TOKEN_VIDA)
    except signing.BadSignature:
        return None
    return datos if datos.get('c') == empresa.pk else None


@transaction.atomic
def registrar(empresa, email, first_name='', last_name='', password=None):
    """Crea (si hace falta) la cuenta y la membresía según el dominio. Devuelve (user, creado) o None
    si ya no está permitido (se vuelve a validar al confirmar). Una membresía existente no se toca."""
    regla = dominio_permitido(empresa, email)
    if regla is None:
        return None
    user = User.objects.filter(email__iexact=email).first()
    creado = user is None
    if creado:
        user = User(email=email, first_name=first_name, last_name=last_name)
        user.set_password(password) if password else user.set_unusable_password()
        user.save()
    if not Membresia.objects.filter(user=user, empresa=empresa).exists():
        agregar_miembro(user, empresa, regla.rol)
    return user, creado
