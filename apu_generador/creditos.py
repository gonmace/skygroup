"""Créditos de APU: límites por empresa y por persona, por día y por mes (fecha local).

Reglas:
- Cuesta 1 crédito: generar un APU (se cobra al guardar el resultado), reutilizarlo en otro proyecto y cada prompt de
  modificación. Los pasos intermedios, «proponer de nuevo» y responder consultas no cobran.
- Se revisa PRIMERO la empresa y después la persona: si la empresa agotó su límite, nadie genera aunque tenga créditos.
- El superusuario no consume. El administrador de sistema no tiene límite personal, pero sí consume el de la empresa.
- Todo pasa por `consumir()`, que serializa con `select_for_update` (la empresa y la persona) y revalida dentro de la
  transacción; `revertir()` devuelve el crédito si la IA falla.
"""
from django.db import transaction
from django.utils import timezone

from apu_catalogo.acceso import es_admin_o_super

from .models import ConsumoAPU, LimiteAPU, LimiteEmpresaAPU

DEFECTO_EMPRESA = (20, 100)
DEFECTO_PERSONA = (3, 10)


class SinCreditos(Exception):
    """No se puede consumir. El mensaje va dirigido a la persona y se muestra tal cual."""


def _inicios():
    ahora = timezone.localtime()
    dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    return dia, dia.replace(day=1)


def limite_empresa(empresa):
    """(max_dia, max_mes) de la empresa, o None si no se aplica límite."""
    fila = LimiteEmpresaAPU.objects.filter(empresa=empresa).first()
    if fila is None:
        return DEFECTO_EMPRESA
    return (fila.max_dia, fila.max_mes) if fila.activo else None


def limite_persona(membresia):
    fila = LimiteAPU.objects.filter(membresia=membresia).first()
    return (fila.max_dia, fila.max_mes) if fila else DEFECTO_PERSONA


def usado_empresa(empresa):
    dia, mes = _inicios()
    qs = ConsumoAPU.objects.filter(empresa=empresa)
    return qs.filter(fecha__gte=dia).count(), qs.filter(fecha__gte=mes).count()


def usado_persona(user, empresa):
    dia, mes = _inicios()
    qs = ConsumoAPU.objects.filter(empresa=empresa, usuario=user)
    return qs.filter(fecha__gte=dia).count(), qs.filter(fecha__gte=mes).count()


def _membresia(user, empresa):
    return user.membresias.filter(empresa=empresa, activa=True).first()


def _motivo(user, empresa):
    """Mensaje de por qué no puede consumir, o '' si puede. Empresa primero, luego la persona."""
    tope = limite_empresa(empresa)
    if tope is not None:
        dia, mes = usado_empresa(empresa)
        if mes >= tope[1]:
            return f'La empresa agotó sus {tope[1]} APU de este mes. Pide al administrador que amplíe el límite.'
        if dia >= tope[0]:
            return f'La empresa agotó sus {tope[0]} APU de hoy. Se renueva mañana, o pide al administrador que amplíe el límite.'
    if not es_admin_o_super(user, empresa):
        membresia = _membresia(user, empresa)
        if membresia is not None:
            max_dia, max_mes = limite_persona(membresia)
            dia, mes = usado_persona(user, empresa)
            if mes >= max_mes:
                return f'Usaste {mes} de {max_mes} APU este mes. Pide a un administrador que amplíe tu límite.'
            if dia >= max_dia:
                return f'Usaste {dia} de {max_dia} APU hoy. Se renueva mañana.'
    return ''


def puede_consumir(user, empresa):
    """(True, '') si puede; (False, motivo) si no."""
    if user.is_superuser:
        return True, ''
    motivo = _motivo(user, empresa)
    return (not motivo), motivo


@transaction.atomic
def consumir(user, empresa, tipo, referencia=''):
    """Descuenta 1 crédito. Lanza `SinCreditos` si no alcanza. El superusuario no consume (devuelve None)."""
    if user.is_superuser:
        return None
    # Serializa a todos los que consumen de la misma empresa: la segunda petición espera y ve el consumo ya hecho.
    LimiteEmpresaAPU.objects.select_for_update().get_or_create(empresa=empresa, defaults={
        'max_dia': DEFECTO_EMPRESA[0], 'max_mes': DEFECTO_EMPRESA[1]})
    motivo = _motivo(user, empresa)
    if motivo:
        raise SinCreditos(motivo)
    return ConsumoAPU.objects.create(empresa=empresa, usuario=user, tipo=tipo, referencia=referencia)


def revertir(user, empresa, tipo, referencia):
    """Borra el último consumo de esa acción (la IA falló después de cobrar)."""
    if user.is_superuser:
        return
    with transaction.atomic():
        consumo = (ConsumoAPU.objects.select_for_update()
                   .filter(empresa=empresa, usuario=user, tipo=tipo, referencia=referencia).order_by('-fecha').first())
        if consumo:
            consumo.delete()


def resumen(user, empresa):
    """Para mostrar los contadores: {'persona': (usado_dia, max_dia, usado_mes, max_mes) | None,
    'empresa': (…) | None}. `None` = sin límite (superusuario o sin tope)."""
    salida = {'persona': None, 'empresa': None}
    if user.is_superuser:
        return salida
    tope = limite_empresa(empresa)
    if tope is not None:
        d, m = usado_empresa(empresa)
        salida['empresa'] = (d, tope[0], m, tope[1])
    if not es_admin_o_super(user, empresa):
        membresia = _membresia(user, empresa)
        if membresia is not None:
            max_dia, max_mes = limite_persona(membresia)
            d, m = usado_persona(user, empresa)
            salida['persona'] = (d, max_dia, m, max_mes)
    return salida
