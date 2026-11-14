from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from cuentas.roles import RolBase
from reg_base.acceso import acceso_tipo
from reg_base import acciones
from reg_base.alcance import puede_escribir, registros_visibles
from reg_base.estado import color_estado

from datetime import date

from cuentas.capacidades import membresia_activa

from reg_actividades.servicios import contexto_pasos

from .bloqueo import MENSAJE_POSTERIOR_CONCLUIDA, hay_posterior_concluida
from .forms import ActivarConstruccionForm, DatosObraForm
from .models import ESTADOS_OBRA, RegConstruccion

POR_PAGINA = 25
ESTADOS = {'rojo': 3, 'amarillo': 1, 'verde': 2}


def _acceso(*caps):
    return acceso_tipo('construccion', 'reg.construccion.ver', *caps)


@_acceso()
def lista(request):
    empresa, user = request.empresa, request.user
    base = registros_visibles(user, empresa, RegConstruccion.objects.all())
    q = request.GET.get('q', '').strip()
    sitios_qs = base
    if q:
        sitios_qs = sitios_qs.filter(Q(proyecto__nombre__icontains=q) | Q(proyecto__codigo__icontains=q)
                                     | Q(nombre_obra__icontains=q))
    sitios = list(sitios_qs.order_by().values('proyecto_id', 'proyecto__codigo', 'proyecto__nombre', 'proyecto__estado')
                  .annotate(visitas=Count('id'), ultima=Max('fecha'),
                            avance=Subquery(base.filter(proyecto_id=OuterRef('proyecto_id')).order_by('-fecha', '-id')
                                            .values('avance_pct')[:1]),
                            ultimo_id=Subquery(base.filter(proyecto_id=OuterRef('proyecto_id')).order_by('-fecha', '-id')
                                               .values('id')[:1]),
                            ).order_by('proyecto__codigo', 'proyecto__nombre'))
    nombres_obra = dict(ESTADOS_OBRA)
    for s in sitios:
        s['estado_obra'] = s['proyecto__estado']
        s['estado_obra_nombre'] = nombres_obra.get(s['estado_obra'], '—')
    try:
        sel = int(request.GET.get('proyecto', ''))
    except ValueError:
        sel = None
    if sel is None and len(sitios) == 1:
        sel = sitios[0]['proyecto_id']
    estado = request.GET.get('estado', '')
    estado_obra = request.GET.get('obra', '')
    pagina = None
    if sel is not None:
        qs = (base.with_estado().filter(proyecto_id=sel)
              .select_related('proyecto', 'proyecto__tipo', 'user', 'contratista'))
        if estado in ESTADOS:
            qs = qs.filter(orden_estado=ESTADOS[estado])
        if estado_obra in dict(ESTADOS_OBRA):
            qs = qs.filter(proyecto__estado=estado_obra)
        pagina = Paginator(qs.order_by('-fecha', '-id'), POR_PAGINA).get_page(request.GET.get('page'))
        for r in pagina:
            r.color = color_estado(r)
    return render(request, 'reg_construccion/lista.html', {
        'pagina': pagina, 'q': q, 'estado': estado, 'estado_obra': estado_obra, 'estados_obra': ESTADOS_OBRA,
        'sitios': sitios, 'sel': sel,
        'puede_activar': tiene_capacidad(user, 'reg.activar', empresa),
        'puede_nueva': tiene_capacidad(user, 'reg.cargar_datos', empresa),
        'puede_editar_sitio': tiene_capacidad(user, 'proyectos.manage', empresa),
    })


@_acceso('reg.activar')
def activar(request):
    empresa, user = request.empresa, request.user
    puede_elegir = tiene_capacidad(user, 'reg.cambiar_responsable', empresa)
    form = ActivarConstruccionForm(request.POST or None, empresa=empresa, usuario=user, puede_elegir_responsable=puede_elegir)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        responsable = d.get('user') or user
        clave = dict(empresa=empresa, proyecto=d['proyecto'], fecha=d['fecha'])
        previo = RegConstruccion.objects.filter(**clave).first()
        if previo and not previo.is_deleted:
            messages.error(request, 'Ya existe una visita de este proyecto en esa fecha.')
            return render(request, 'reg_construccion/activar.html', {'form': form})
        if RegConstruccion.objects.filter(empresa=empresa, proyecto=d['proyecto'], is_deleted=False,
                                          concluido=True, fecha__gt=d['fecha']).exists():
            messages.error(request, MENSAJE_POSTERIOR_CONCLUIDA)
            return render(request, 'reg_construccion/activar.html', {'form': form})
        try:
            if previo:   # borrada antes: se reactiva conservando lo cargado
                previo.is_deleted, previo.is_active, previo.user = False, True, responsable
                previo.contratista = d.get('contratista') or previo.contratista
                previo.save()
                r = previo
            else:
                r = RegConstruccion.objects.create(user=responsable, contratista=d.get('contratista'),
                                                   nombre_obra=d['proyecto'].nombre, **clave)
        except ValidationError as exc:
            form.add_error(None, exc.messages[0])
            return render(request, 'reg_construccion/activar.html', {'form': form})
        messages.success(request, f'Registro activado para {r.proyecto.nombre} · {r.fecha:%d/%m/%Y}.')
        return redirect('reg_construccion:detalle', pk=r.pk)
    return render(request, 'reg_construccion/activar.html', {'form': form})


@_acceso()
def detalle(request, pk):
    r = acciones.obtener_registro(request, RegConstruccion, pk, 'contratista', 'proyecto__tipo')
    user, empresa = request.user, request.empresa
    from reg_construccion.models import RegConstruccion as M
    r.color = color_estado(M.objects.filter(pk=r.pk).with_estado().get())
    lat, lon = r.coordenadas
    escribe = puede_escribir(user, r)
    return render(request, 'reg_construccion/detalle.html', {
        'r': r, **_fotos_ctx(r), **contexto_pasos(request, r, 'construccion', escribe), 'lat': lat, 'lon': lon, 'puede_escribir': escribe,
        'form': _form_datos(user, empresa, r) if escribe else None,
        'puede_nueva': tiene_capacidad(user, 'reg.cargar_datos', empresa),
        'aviso_bloqueo': MENSAJE_POSTERIOR_CONCLUIDA if hay_posterior_concluida(r) else None,
        'puede_concluir': tiene_capacidad(user, 'reg.reabrir' if r.concluido else 'reg.concluir', empresa),
        'visitas': registros_visibles(user, empresa, RegConstruccion.objects.filter(proyecto_id=r.proyecto_id)).order_by('fecha', 'id'),
    })


@require_POST
@_acceso('reg.cargar_datos')
def datos(request, pk):
    r = acciones.obtener_registro(request, RegConstruccion, pk, 'contratista')
    acciones.exigir_escritura(request.user, r)
    fecha_original = r.fecha
    form = _form_datos(request.user, request.empresa, r, request.POST)
    if form.is_valid():
        nueva = form.cleaned_data.get('fecha')
        if nueva and nueva != fecha_original and (
                hay_posterior_concluida(r, fecha_original) or hay_posterior_concluida(r, nueva)):
            messages.error(request, MENSAJE_POSTERIOR_CONCLUIDA)
            return redirect('reg_construccion:detalle', pk=pk)
        try:
            form.save()
            messages.success(request, 'Datos de la obra actualizados.')
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
    else:
        messages.error(request, '; '.join(e for errs in form.errors.values() for e in errs))
    return redirect('reg_construccion:detalle', pk=pk)


@require_POST
@_acceso()
def concluir(request, pk):
    r = acciones.obtener_registro(request, RegConstruccion, pk)
    concluido = acciones.alternar_concluido(request.user, r)
    messages.success(request, 'Visita concluida.' if concluido else 'Visita reabierta.')
    return redirect('reg_construccion:detalle', pk=pk)


@require_POST
@_acceso()
def eliminar(request, pk):
    acciones.exigir_superusuario(request.user)
    r = acciones.obtener_registro(request, RegConstruccion, pk)
    if r.concluido:
        messages.error(request, 'Una visita concluida no se puede eliminar: reábrela primero.')
        return redirect('reg_construccion:detalle', pk=pk)
    if hay_posterior_concluida(r):
        messages.error(request, MENSAJE_POSTERIOR_CONCLUIDA)
        return redirect('reg_construccion:detalle', pk=pk)
    r.soft_delete()
    messages.success(request, 'Visita eliminada.')
    return redirect('reg_construccion:lista')


def _form_datos(user, empresa, registro, post=None):
    return DatosObraForm(post, instance=registro, usuario=user,
                         puede_cambiar_responsable=tiene_capacidad(user, 'reg.cambiar_responsable', empresa))


@require_POST
@_acceso('reg.cargar_datos')
def nueva_visita(request, pk):
    """Otra visita del mismo proyecto (fecha distinta) copiando la cabecera de la última. Se puede crear desde una
    visita concluida: es el camino normal para seguir la obra."""
    base = acciones.obtener_registro(request, RegConstruccion, pk, 'contratista')
    try:
        fecha = date.fromisoformat(request.POST.get('fecha') or date.today().isoformat())
    except ValueError:
        messages.error(request, 'Fecha inválida.')
        return redirect('reg_construccion:detalle', pk=pk)
    if hay_posterior_concluida(base, fecha):
        messages.error(request, MENSAJE_POSTERIOR_CONCLUIDA)
        return redirect('reg_construccion:detalle', pk=pk)
    # Solo entre las visitas que esta persona puede ver: no hereda la cabecera de lo que no le corresponde.
    ultima = (registros_visibles(request.user, base.empresa, RegConstruccion.objects.filter(proyecto=base.proyecto))
              .order_by('-fecha', '-id').first() or base)
    m = membresia_activa(request.user, base.empresa)
    es_ito = m is not None and m.rol.rol_base == RolBase.MIEMBRO   # un ITO/Buscador queda como responsable de lo que crea
    responsable = request.user if es_ito else base.user
    clave = dict(empresa=base.empresa, proyecto=base.proyecto, fecha=fecha)
    previo = RegConstruccion.objects.filter(**clave).first()
    if previo and not previo.is_deleted:
        messages.error(request, 'Ya existe una visita de este proyecto en esa fecha.')
        return redirect('reg_construccion:detalle', pk=previo.pk)
    cabecera = dict(contratista=ultima.contratista, nombre_obra=ultima.nombre_obra, descripcion=ultima.descripcion,
                    revision=ultima.revision)
    try:
        if previo:   # borrada antes: se reactiva conservando lo cargado
            previo.is_deleted, previo.is_active, previo.user = False, True, responsable
            for campo, valor in cabecera.items():
                setattr(previo, campo, valor)
            previo.save()
            nueva = previo
        else:
            nueva = RegConstruccion.objects.create(user=responsable, **cabecera, **clave)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect('reg_construccion:detalle', pk=pk)
    messages.success(request, f'Visita del {fecha:%d/%m/%Y} creada con la cabecera de la anterior.')
    return redirect('reg_construccion:detalle', pk=nueva.pk)


def _fotos_ctx(registro):
    return acciones.contexto_imagenes(registro, 12)


@_acceso()
def pdf(request, pk):
    """Reporte de avance en PDF. `?cols_actividades|libro|electrico=1|2` fija las fotos por fila de cada sección."""
    from django.http import HttpResponse
    from .pdf import reporte
    r = acciones.obtener_registro(request, RegConstruccion, pk, 'contratista', 'proyecto__tipo')
    columnas = {k: int(request.GET[f'cols_{k}']) for k, _, _ in reporte.SECCIONES_FOTOS
                if request.GET.get(f'cols_{k}') in ('1', '2')}
    respuesta = HttpResponse(reporte.generar(r, columnas), content_type='application/pdf')
    respuesta['Content-Disposition'] = f'inline; filename="{reporte.nombre_archivo(r)}"'
    return respuesta
