from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from empresas.acceso import acceso_modulo

from . import equipos
from .forms import ConfigJornadasForm, PerfilForm
from .models import ConfigJornadas, Perfil


@acceso_modulo('jor', 'jor.perfiles.manage')
@require_POST
def perfil_acceso(request, membresia_id):
    """Interruptor de la pantalla Equipo: permite o impide que la persona fiche jornadas."""
    membresia = get_object_or_404(request.empresa.membresias.select_related('user'), pk=membresia_id)
    perfil = Perfil.de(membresia)
    perfil.activo = not perfil.activo
    perfil.save(update_fields=['activo'])
    messages.success(request, f'{membresia.user}: {"puede" if perfil.activo else "ya no puede"} fichar jornadas.')
    return redirect('jor_diario:equipo')


@acceso_modulo('jor', 'jor.perfiles.manage')
@require_POST
def perfil_reporte(request, membresia_id):
    """Interruptor de la pantalla Equipo: exige o no «Realizado» y «Planificado» al finalizar la jornada."""
    membresia = get_object_or_404(request.empresa.membresias.select_related('user'), pk=membresia_id)
    perfil = Perfil.de(membresia)
    perfil.exige_reporte = not perfil.exige_reporte
    perfil.save(update_fields=['exige_reporte'])
    messages.success(request, f'{membresia.user}: {"debe" if perfil.exige_reporte else "ya no debe"} completar el reporte diario.')
    return redirect('jor_diario:equipo')


@acceso_modulo('jor', 'jor.perfiles.manage')
@require_POST
def perfil_movil(request, membresia_id):
    """Interruptor de la pantalla Equipo: permite o no iniciar y finalizar la jornada desde un celular."""
    membresia = get_object_or_404(request.empresa.membresias.select_related('user'), pk=membresia_id)
    perfil = Perfil.de(membresia)
    perfil.puede_movil = not perfil.puede_movil
    perfil.save(update_fields=['puede_movil'])
    messages.success(request, f'{membresia.user}: {"puede" if perfil.puede_movil else "ya no puede"} marcar desde el celular.')
    return redirect('jor_diario:equipo')


@acceso_modulo('jor', 'jor.perfiles.manage')
@require_POST
def equipo_liberar(request, membresia_id, tipo):
    """Libera el equipo habitual (se cambió o se perdió): la siguiente marcación registra otro, sin revisión."""
    if tipo not in ('pc', 'movil'):
        raise Http404
    membresia = get_object_or_404(request.empresa.membresias.select_related('user'), pk=membresia_id)
    n = equipos.liberar(Perfil.de(membresia), tipo, request.user)
    nombre = 'computador' if tipo == 'pc' else 'celular'
    messages.success(request, f'Equipo ({nombre}) de {membresia.user} liberado: el próximo que use quedará como habitual.' if n
                     else f'{membresia.user} no tiene un {nombre} registrado.')
    if request.POST.get('next') == 'equipo':
        return redirect('jor_diario:equipo')
    return redirect('jor_diario:persona', membresia_id=membresia.pk)


@acceso_modulo('jor', 'jor.perfiles.manage')
def perfil_editar(request, membresia_id):
    membresia = get_object_or_404(request.empresa.membresias.select_related('user'), pk=membresia_id)
    form = PerfilForm(request.POST or None, instance=Perfil.de(membresia))
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Perfil guardado.')
        return redirect('jor_diario:persona', membresia_id=membresia.pk)
    return render(request, 'jor_empleados/perfil_form.html', {'form': form, 'persona': membresia})


def pestanas_config(request, activa):
    """Pestañas de Configuración de Jornadas que el usuario puede ver: General · Categorías · Etiquetas."""
    candidatas = [
        ('general', 'General', 'jor_empleados:config', 'jor.config.manage'),
        ('categorias', 'Categorías', 'jor_actividades:categorias', 'jor.config.manage'),
        ('etiquetas', 'Etiquetas', 'jor_actividades:etiquetas', 'jor.etiquetas.manage'),
    ]
    return [{'nombre': n, 'url': reverse(u), 'activa': c == activa}
            for c, n, u, cap in candidatas if tiene_capacidad(request.user, cap, request.empresa)]


@acceso_modulo('jor')
def config(request):
    if not tiene_capacidad(request.user, 'jor.config.manage', request.empresa):
        if tiene_capacidad(request.user, 'jor.etiquetas.manage', request.empresa):
            return redirect('jor_actividades:etiquetas')    # solo gestiona etiquetas: su pestaña
        raise PermissionDenied
    form = ConfigJornadasForm(request.POST or None, request.FILES or None, instance=ConfigJornadas.de(request.empresa))
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Configuración guardada.')
        return redirect('jor_empleados:config')
    from jor_reportes import variables
    return render(request, 'jor_empleados/config.html', {
        'form': form, 'pestanas': pestanas_config(request, 'general'),
        'tiene_plantilla': bool(form.instance.plantilla_certificado), 'catalogo': variables.catalogo_agrupado()})
