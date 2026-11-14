from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from empresas.acceso import acceso_modulo
from reg_base import acciones, tipos
from reg_base.alcance import puede_escribir

from . import servicios
from .iconos import ICONOS_ELEGIBLES
from .models import DatoPaso

_acceso = acceso_modulo('reg')


def _registro(request, clave, pk):
    t = tipos.tipo_de_request(request, clave)
    if not tiene_capacidad(request.user, t.capacidad_ver, request.empresa):
        raise PermissionDenied
    return t, acciones.obtener_registro(request, t.modelo, pk)


@_acceso
def pasos(request, clave, pk):
    """Antigua pantalla solo de pasos: ahora el detalle del registro ya la muestra. Se conserva la URL (marcadores,
    enlaces viejos) y manda al detalle; `_registro` mantiene el 404 de registros ajenos o de tipos desconocidos."""
    t, registro = _registro(request, clave, pk)
    return redirect(t.url_detalle, pk=registro.pk)


def _asignado(registro, clave, nombre):
    for a in servicios.asignados_de(registro, clave):
        if a.paso.nombre == nombre:
            return a
    raise Http404('Ese paso no pertenece a la plantilla del registro.')


def _bloqueo_de_paso(registro, clave, paso):
    """Aviso si el módulo del registro impide guardar este paso (Construcción: visita posterior concluida)."""
    if clave == 'construccion':
        from reg_construccion.bloqueo import bloqueo_de_paso
        return bloqueo_de_paso(registro, paso)
    return None


def _solo(request, a):
    """Slug del componente si se abre/guarda uno solo (?w=…); None = el paso completo. 404 si no es del paso."""
    w = request.POST.get('w') or request.GET.get('w') or ''
    if w and not a.paso.widgets.filter(widget_slug=w).exists():
        raise Http404('Ese componente no pertenece al paso.')
    return w or None


def _render_paso(request, t, registro, a, bloques, color, escribe, status=200, solo=None):
    asignados = servicios.asignados_de(registro, t.clave)
    nombres = [x.paso.nombre for x in asignados]
    i = nombres.index(a.paso.nombre)
    return render(request, 'reg_actividades/paso.html', {
        'tipo': t, 'r': registro, 'paso': a.paso, 'bloques': bloques, 'color': color, 'puede_escribir': escribe, 'solo': solo,
        'anterior': asignados[i - 1].paso if i > 0 else None,
        'siguiente': asignados[i + 1].paso if i + 1 < len(asignados) else None,
        'url_detalle': t.url_detalle,
        'aviso_bloqueo': _bloqueo_de_paso(registro, t.clave, a.paso) if escribe else None,
        'hay_mapa': any(b['widget'].slug in ('mapa_1p', 'mapa_2_puntos') for b in bloques),   # carga Leaflet solo si hace falta
    }, status=status)


@_acceso
def paso(request, clave, pk, nombre):
    t, registro = _registro(request, clave, pk)
    a = _asignado(registro, clave, nombre)
    escribe = puede_escribir(request.user, registro)
    from django.contrib.contenttypes.models import ContentType
    dato = DatoPaso.objects.filter(content_type=ContentType.objects.get_for_model(type(registro)),
                                   object_id=registro.pk, paso_nombre=nombre).first()
    bloques, color = servicios.construir_paso(registro, clave, a.paso, dato, request.user, escribe)
    solo = _solo(request, a)
    if solo:
        bloques = [b for b in bloques if b['pw'].widget_slug == solo]
    return _render_paso(request, t, registro, a, bloques, color, escribe, solo=solo)


@require_POST
@_acceso
def guardar(request, clave, pk, nombre):
    t, registro = _registro(request, clave, pk)
    acciones.exigir_escritura(request.user, registro)
    a = _asignado(registro, clave, nombre)
    solo = _solo(request, a)
    bloqueo = _bloqueo_de_paso(registro, clave, a.paso)
    if bloqueo:
        messages.error(request, bloqueo)
        return redirect('reg_actividades:paso', clave=clave, pk=pk, nombre=nombre)
    ok, errores = servicios.guardar_paso(registro, a.paso, request.POST, request.FILES, user=request.user,
                                         solo={solo} if solo else None)
    if ok:
        messages.success(request, 'Guardado.' if solo else 'Paso guardado.')
        # Un componente suelto vuelve al detalle del registro (donde están los pasos); el paso completo se queda en su página.
        return redirect(tipos.tipo(clave).url_detalle, pk=pk) if solo else redirect(
            'reg_actividades:paso', clave=clave, pk=pk, nombre=nombre)
    # Con errores no se guardó nada: se vuelve a pintar el formulario con lo que el usuario escribió.
    from django.contrib.contenttypes.models import ContentType
    dato = DatoPaso.objects.filter(content_type=ContentType.objects.get_for_model(type(registro)),
                                   object_id=registro.pk, paso_nombre=nombre).first()
    bloques, color = servicios.construir_paso(registro, clave, a.paso, dato, request.user, True)   # `datos` = lo guardado
    if solo:
        bloques = [b for b in bloques if b['pw'].widget_slug == solo]
    for b in bloques:
        b['errores'] = errores.get(b['pw'].widget_slug, [])
        if b['widget'].guarda_datos:   # se repinta con lo que el usuario escribió (aunque no sea válido)
            c = servicios.Contexto(registro=registro, paso=a.paso, clave=clave, user=request.user, puede_escribir=True,
                                   extra={'previos': b['datos']})   # lo ya guardado, para las reglas por rol
            datos, _errs = b['widget'].leer(request.POST, request.FILES, b['pw'].config, c)
            b['datos'] = datos
            b.update(b['widget'].contexto(datos, b['pw'].config, c))
    messages.error(request, 'Revisa los campos marcados: no se guardó nada.')
    return _render_paso(request, t, registro, a, bloques, color, True, status=422, solo=solo)


# ── Configuración (reg.config.manage) ─────────────────────────────────────────

from django.db.models import Count  # noqa: E402
from django.shortcuts import get_object_or_404  # noqa: E402

from .forms import PasoForm, PasoWidgetForm, PlantillaForm  # noqa: E402
from .models import Paso, PasoAsignado, PasoWidget, Plantilla  # noqa: E402
from .widgets import todos as tipos_de_widget  # noqa: E402

_config = acceso_modulo('reg', 'reg.config.manage')


@_config
def pasos_config(request):
    empresa = request.empresa
    form = PasoForm(request.POST or None, empresa=empresa)
    if request.method == 'POST' and form.is_valid():
        paso = form.save()
        messages.success(request, f'Paso «{paso.titulo}» creado.')
        return redirect('reg_actividades:paso_editar', pk=paso.pk)
    lista = Paso.objects.filter(empresa=empresa).annotate(n_widgets=Count('widgets', distinct=True),
                                                           n_plantillas=Count('asignaciones', distinct=True))
    return render(request, 'reg_actividades/config_pasos.html', {'lista': lista, 'form': form})


@_config
def paso_editar(request, pk):
    paso = get_object_or_404(Paso, pk=pk, empresa=request.empresa)
    form = PasoForm(request.POST or None, instance=paso, empresa=request.empresa)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Paso guardado.')
        return redirect('reg_actividades:paso_editar', pk=pk)
    return render(request, 'reg_actividades/config_paso.html', {
        'paso': paso, 'form': form, 'widgets': paso.widgets.all(),
        'form_widget': PasoWidgetForm(paso=paso, initial={'orden': paso.widgets.count() + 1}),
        'tipos_widget': tipos_de_widget(), 'iconos': ICONOS_ELEGIBLES,
    })


@require_POST
@_config
def paso_eliminar(request, pk):
    paso = get_object_or_404(Paso, pk=pk, empresa=request.empresa)
    if paso.asignaciones.exists():
        messages.error(request, 'El paso está asignado a una plantilla: quítalo de ella primero.')
        return redirect('reg_actividades:paso_editar', pk=pk)
    paso.delete()
    messages.success(request, 'Paso eliminado.')
    return redirect('reg_actividades:pasos_config')


@require_POST
@_config
def widget_agregar(request, pk):
    paso = get_object_or_404(Paso, pk=pk, empresa=request.empresa)
    form = PasoWidgetForm(request.POST, paso=paso)
    if form.is_valid():
        d = form.cleaned_data
        PasoWidget.objects.create(paso=paso, widget_slug=d['widget_slug'], orden=d['orden'], config=d['config'])
        messages.success(request, 'Widget agregado.')
    else:
        messages.error(request, ' '.join(e for errs in form.errors.values() for e in errs))
    return redirect('reg_actividades:paso_editar', pk=pk)


@require_POST
@_config
def widget_editar(request, pk, widget_id):
    paso = get_object_or_404(Paso, pk=pk, empresa=request.empresa)
    pw = get_object_or_404(PasoWidget, pk=widget_id, paso=paso)
    form = PasoWidgetForm(request.POST, paso=paso, instance=pw)
    if form.is_valid():
        pw.orden, pw.config = form.cleaned_data['orden'], form.cleaned_data['config']
        pw.save()
        messages.success(request, 'Widget actualizado.')
    else:
        messages.error(request, ' '.join(e for errs in form.errors.values() for e in errs))
    return redirect('reg_actividades:paso_editar', pk=pk)


@require_POST
@_config
def widget_eliminar(request, pk, widget_id):
    paso = get_object_or_404(Paso, pk=pk, empresa=request.empresa)
    get_object_or_404(PasoWidget, pk=widget_id, paso=paso).delete()
    messages.success(request, 'Widget eliminado.')
    return redirect('reg_actividades:paso_editar', pk=pk)


@_config
def plantillas(request):
    empresa = request.empresa
    form = PlantillaForm(request.POST or None, empresa=empresa)
    if request.method == 'POST' and form.is_valid():
        p = form.save()
        messages.success(request, f'Plantilla «{p.nombre}» creada.')
        return redirect('reg_actividades:plantilla_editar', pk=p.pk)
    lista = Plantilla.objects.filter(empresa=empresa).select_related('tipo_proyecto').annotate(n=Count('asignados'))
    return render(request, 'reg_actividades/config_plantillas.html', {'lista': lista, 'form': form})


@_config
def plantilla_editar(request, pk):
    p = get_object_or_404(Plantilla, pk=pk, empresa=request.empresa)
    form = PlantillaForm(request.POST or None, instance=p, empresa=request.empresa)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Plantilla guardada.')
        return redirect('reg_actividades:plantilla_editar', pk=pk)
    asignados = p.asignados.select_related('paso')
    disponibles = Paso.objects.filter(empresa=request.empresa).exclude(pk__in=[a.paso_id for a in asignados])
    return render(request, 'reg_actividades/config_plantilla.html', {
        'p': p, 'form': form, 'asignados': asignados, 'disponibles': disponibles,
    })


@require_POST
@_config
def plantilla_eliminar(request, pk):
    get_object_or_404(Plantilla, pk=pk, empresa=request.empresa).delete()
    messages.success(request, 'Plantilla eliminada.')
    return redirect('reg_actividades:plantillas')


@require_POST
@_config
def plantilla_paso_agregar(request, pk):
    p = get_object_or_404(Plantilla, pk=pk, empresa=request.empresa)
    paso = get_object_or_404(Paso, pk=request.POST.get('paso') or 0, empresa=request.empresa)
    PasoAsignado.objects.get_or_create(plantilla=p, paso=paso, defaults={'orden': p.asignados.count() + 1})
    return redirect('reg_actividades:plantilla_editar', pk=pk)


@require_POST
@_config
def plantilla_paso_orden(request, pk, asignado_id):
    p = get_object_or_404(Plantilla, pk=pk, empresa=request.empresa)
    a = get_object_or_404(PasoAsignado, pk=asignado_id, plantilla=p)
    try:
        a.orden = max(0, int(request.POST.get('orden', a.orden)))
        a.save(update_fields=['orden'])
    except ValueError:
        messages.error(request, 'Orden inválido.')
    return redirect('reg_actividades:plantilla_editar', pk=pk)


@require_POST
@_config
def plantilla_paso_quitar(request, pk, asignado_id):
    p = get_object_or_404(Plantilla, pk=pk, empresa=request.empresa)
    get_object_or_404(PasoAsignado, pk=asignado_id, plantilla=p).delete()
    return redirect('reg_actividades:plantilla_editar', pk=pk)


@require_POST
@_config
def sembrar(request):
    pasos_n, plantillas_n = servicios.sembrar_ejemplo(request.empresa)
    if pasos_n or plantillas_n:
        messages.success(request, f'Se crearon {pasos_n} paso(s) y {plantillas_n} plantilla(s) de ejemplo.')
    else:
        messages.info(request, 'La configuración de ejemplo ya existía.')
    return redirect('reg_actividades:plantillas')
