"""Equipo habitual de marcación: el primer computador (y el primer celular, si la persona puede marcar desde él) con
el que marca queda registrado; marcar después desde otro equipo se detecta como «cambio de equipo».

El equipo se identifica con un token aleatorio guardado en una cookie (más una copia en localStorage que el JS reenvía
por si el iframe de Nextcloud bloquea la cookie). Borrar los datos del navegador o usar otro navegador cuenta como otro
equipo: es una señal para revisión, no una prueba."""
import hashlib
import secrets

from django.conf import settings
from django.utils import timezone

from .models import EquipoMarcacion

COOKIE = 'jor_equipo'
COOKIE_MAX_AGE = 5 * 365 * 24 * 3600


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def token_de(request):
    """Token que trae el navegador (cookie o campo `equipo`), o uno nuevo si no trae ninguno válido."""
    t = request.COOKIES.get(COOKIE) or request.POST.get('equipo') or ''
    return t if 20 <= len(t) <= 100 else secrets.token_urlsafe(32)


def resolver(request, perfil, tipo, ip=None):
    """→ (equipo, token, es_cambio). Sin equipo activo de ese tipo se registra este (primera vez, sin aviso). Si el
    token coincide con el habitual, se actualiza su último uso. Si no, se guarda como equipo inactivo (para poder
    adoptarlo después) y es_cambio=True; el habitual se devuelve en `equipo.habitual`."""
    token = token_de(request)
    h = _hash(token)
    ahora = timezone.now()
    ua = request.META.get('HTTP_USER_AGENT', '')[:300]
    habitual = perfil.equipos.filter(tipo=tipo, activo=True).first()
    if habitual is None:
        eq = perfil.equipos.filter(tipo=tipo, token_hash=h).first()
        if eq is None:
            eq = EquipoMarcacion(perfil=perfil, tipo=tipo, token_hash=h)
        eq.activo, eq.user_agent, eq.ip, eq.ultimo_uso = True, ua, ip or None, ahora
        eq.save()
        eq.habitual = None
        return eq, token, False
    if habitual.token_hash == h:
        habitual.ultimo_uso = ahora
        habitual.save(update_fields=['ultimo_uso'])
        habitual.habitual = None
        return habitual, token, False
    eq, _ = perfil.equipos.get_or_create(tipo=tipo, token_hash=h, activo=False,
                                         defaults={'user_agent': ua, 'ip': ip or None})
    eq.ultimo_uso, eq.user_agent, eq.ip = ahora, ua, ip or eq.ip
    eq.save(update_fields=['ultimo_uso', 'user_agent', 'ip'])
    eq.habitual = habitual
    return eq, token, True


def poner_cookie(response, token):
    response.set_cookie(COOKIE, token, max_age=COOKIE_MAX_AGE, httponly=True, secure=not settings.DEBUG,
                        samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax') or 'Lax')


def adoptar(equipo):
    """Pasa a ser el equipo habitual de su tipo (el anterior queda inactivo)."""
    equipo.perfil.equipos.filter(tipo=equipo.tipo, activo=True).exclude(pk=equipo.pk).update(activo=False)
    equipo.activo = True
    equipo.save(update_fields=['activo'])


def liberar(perfil, tipo, por):
    """El administrador libera el equipo habitual: la siguiente marcación registra otro sin revisión."""
    return perfil.equipos.filter(tipo=tipo, activo=True).update(activo=False, liberado_por=por,
                                                                liberado_en=timezone.now())
