"""Acceso al módulo APU: `acceso_modulo` + la regla de jornada.

Si la empresa tiene Asistencia (`jor`), quien usa APU debe tener una jornada EN CURSO. Están exentos el superusuario y el
administrador de sistema de la empresa; una empresa sin Asistencia no tiene la restricción."""
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render

from cuentas.capacidades import administra
from empresas.acceso import acceso_modulo

MENSAJE_PROXIMAMENTE = 'APU estará disponible próximamente.'
MENSAJE_SIN_JORNADA = 'Inicia tu jornada para usar APU.'


def es_admin_o_super(user, empresa):
    """Superusuario o administrador de sistema de la empresa (los exentos de jornada y de límite personal)."""
    return bool(user.is_superuser or (empresa is not None and administra(user, empresa.pk)))


def apu_cerrado_para(user, empresa):
    """True si APU todavía no está abierto para esta persona («Próximamente»): solo superusuario y administradores."""
    return settings.APU_SOLO_ADMIN and not es_admin_o_super(user, empresa)


def exige_jornada(user, empresa):
    return empresa.tiene_modulo('jor') and not es_admin_o_super(user, empresa)


def tiene_jornada_en_curso(user, empresa):
    from jor_diario.models import Jornada
    return Jornada.objects.filter(empresa=empresa, perfil__membresia__user=user,
                                  estado=Jornada.Estado.EN_CURSO).exists()


def bloqueado_por_jornada(user, empresa):
    return exige_jornada(user, empresa) and not tiene_jornada_en_curso(user, empresa)


def _es_ajax(request):
    return (request.headers.get('x-requested-with') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('accept', '')
            or request.content_type == 'application/json')


def acceso_apu(*capacidades):
    """Como `acceso_modulo('apu', …)` más la regla de jornada. Las páginas muestran el aviso; las llamadas AJAX
    responden 403 con un `message`."""
    def decorador(vista):
        @acceso_modulo('apu', *capacidades)
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if apu_cerrado_para(request.user, request.empresa):
                if _es_ajax(request):
                    return JsonResponse({'success': False, 'message': MENSAJE_PROXIMAMENTE}, status=403)
                return render(request, 'apu_catalogo/proximamente.html', status=403)
            if bloqueado_por_jornada(request.user, request.empresa):
                if _es_ajax(request):
                    return JsonResponse({'success': False, 'message': MENSAJE_SIN_JORNADA}, status=403)
                messages.warning(request, MENSAJE_SIN_JORNADA)
                return render(request, 'apu_catalogo/sin_jornada.html', status=403)
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador
