from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import get_script_prefix
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Notificacion
from .services import ruta_segura


def _propias(request):
    empresa = getattr(request, 'empresa', None)
    if empresa is None:
        raise Http404
    return Notificacion.objects.filter(destinatario=request.user, empresa=empresa)


@login_required
def lista(request):
    qs = _propias(request).select_related('actor')
    solo_no_leidas = request.GET.get('filtro') == 'no_leidas'
    if solo_no_leidas:
        qs = qs.filter(leida=False)
    return render(request, 'notificaciones/lista.html', {
        'notificaciones': qs[:100], 'solo_no_leidas': solo_no_leidas,
    })


@login_required
@require_POST
def leer(request, pk):
    """Marca como leída y lleva al destino del aviso (si es una ruta interna segura)."""
    notif = get_object_or_404(_propias(request), pk=pk)
    if not notif.leida:
        notif.leida = True
        notif.save(update_fields=['leida'])
    if ruta_segura(notif.url):
        destino = f'{get_script_prefix().rstrip("/")}{notif.url}'
        if url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
            return redirect(destino)
    return redirect('notificaciones:lista')


@login_required
@require_POST
def leer_todas(request):
    _propias(request).filter(leida=False).update(leida=True)
    return redirect('notificaciones:lista')
