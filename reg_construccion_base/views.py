from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from proyectos.models import Proyecto
from reg_actividades.servicios import contexto_pasos
from reg_base import acciones, revisiones
from reg_base.acceso import acceso_tipo
from reg_base.alcance import puede_escribir, registros_visibles
from reg_base.estado import color_estado

from . import servicios
from .forms import DatosVisitaForm, HallazgoForm, NuevaVisitaForm
from .models import CLAVE, Hallazgo, RegConstruccionBase

POR_PAGINA = 25
ESTADOS = {'rojo': 3, 'amarillo': 1, 'verde': 2}


def _acceso(*caps):
    return acceso_tipo(CLAVE, 'reg.construccion_base.ver', *caps)


def _visibles(request):
    return registros_visibles(request.user, request.empresa, RegConstruccionBase.objects.all())


@_acceso()
def lista(request):
    """Arriba, los proyectos con visitas (activados); abajo, las visitas del proyecto elegido."""
    empresa, user = request.empresa, request.user
    base = _visibles(request).vigentes()
    q = request.GET.get('q', '').strip()
    sitios_qs = base
    if q:
        sitios_qs = sitios_qs.filter(Q(proyecto__nombre__icontains=q) | Q(proyecto__codigo__icontains=q))
    abiertos = (Hallazgo.objects.filter(proyecto_id=OuterRef('proyecto_id'), is_deleted=False, visita__in=base)
                .exclude(estado='cerrado').order_by().values('proyecto_id').annotate(c=Count('pk')).values('c'))
    ultima = base.filter(proyecto_id=OuterRef('proyecto_id')).order_by('-fecha', '-id')
    sitios = list(sitios_qs.order_by().values('proyecto_id', 'proyecto__codigo', 'proyecto__nombre')
                  .annotate(visitas=Count('id'), ultima=Max('fecha'), ultimo_id=Subquery(ultima.values('id')[:1]),
                            n_abiertos=Coalesce(Subquery(abiertos), 0))
                  .order_by('proyecto__codigo', 'proyecto__nombre'))
    try:
        sel = int(request.GET.get('proyecto', ''))
    except ValueError:
        sel = None
    if sel is None and len(sitios) == 1:
        sel = sitios[0]['proyecto_id']
    estado = request.GET.get('estado', '')
    desde, hasta = _fecha(request.GET.get('desde')), _fecha(request.GET.get('hasta'))
    pagina = None
    if sel is not None:
        qs = base.with_estado().filter(proyecto_id=sel).select_related('proyecto', 'user', 'contratista')
        if estado in ESTADOS:
            qs = qs.filter(orden_estado=ESTADOS[estado])
        if desde:
            qs = qs.filter(fecha__gte=desde)
        if hasta:
            qs = qs.filter(fecha__lte=hasta)
        revs = (RegConstruccionBase.objects.filter(serie=OuterRef('serie'), is_deleted=False).order_by()
                .values('serie').annotate(c=Count('pk')).values('c'))
        qs = qs.annotate(
            n_revisiones=Subquery(revs),
            n_abiertos=Count('hallazgos', filter=Q(hallazgos__is_deleted=False) & ~Q(hallazgos__estado='cerrado'),
                             distinct=True),
        )
        pagina = Paginator(qs.order_by('-fecha', '-id'), POR_PAGINA).get_page(request.GET.get('page'))
        for r in pagina:
            r.color = color_estado(r)
    return render(request, 'reg_construccion_base/lista.html', {
        'pagina': pagina, 'q': q, 'estado': estado, 'desde': request.GET.get('desde', ''),
        'hasta': request.GET.get('hasta', ''), 'sitios': sitios, 'sel': sel,
        'puede_activar': tiene_capacidad(user, 'reg.activar', empresa),
        'puede_nueva': tiene_capacidad(user, 'reg.cargar_datos', empresa),
        'puede_editar_sitio': tiene_capacidad(user, 'proyectos.manage', empresa),
    })


def _fecha(valor):
    try:
        return date.fromisoformat(valor) if valor else None
    except ValueError:
        return None


@_acceso('reg.activar')
def nueva(request):
    empresa, user = request.empresa, request.user
    puede_elegir = tiene_capacidad(user, 'reg.cambiar_responsable', empresa)
    form = NuevaVisitaForm(request.POST or None, empresa=empresa, usuario=user, puede_elegir_responsable=puede_elegir)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            r = RegConstruccionBase.objects.create(
                empresa=empresa, proyecto=d['proyecto'], fecha=d['fecha'], contratista=d.get('contratista'),
                user=d.get('user') or user)
        except ValidationError as exc:
            form.add_error(None, exc.messages[0])
        else:
            messages.success(request, f'Visita {r.numero} de {r.proyecto.nombre} creada.')
            return redirect('reg_construccion_base:detalle', pk=r.pk)
    return render(request, 'reg_construccion_base/nueva.html', {'form': form})


def _obtener(request, pk, *select):
    return acciones.obtener_registro(request, RegConstruccionBase, pk, 'contratista', *select)


@_acceso()
def detalle(request, pk):
    r = _obtener(request, pk, 'proyecto__tipo')
    user, empresa = request.user, request.empresa
    r.color = color_estado(RegConstruccionBase.objects.filter(pk=r.pk).with_estado().get())
    escribe = puede_escribir(user, r)
    from reg_base.tipos import tipo
    from reg_fotos.servicios import fotos_de
    fotos = fotos_de(r)
    return render(request, 'reg_construccion_base/detalle.html', {
        'r': r, **contexto_pasos(request, r, CLAVE, escribe), 'puede_escribir': escribe,
        'form': DatosVisitaForm(instance=r, usuario=user,
                                puede_cambiar_responsable=tiene_capacidad(user, 'reg.cambiar_responsable', empresa))
        if escribe else None,
        'puede_emitir': tiene_capacidad(user, 'reg.concluir', empresa) and not r.concluido,
        'puede_reabrir': r.concluido and (user.is_superuser or tiene_capacidad(user, 'reg.reabrir', empresa)),
        'hallazgos': r.hallazgos.filter(is_deleted=False).order_by('numero'),
        'pendientes': servicios.pendientes_de_seguimiento(r).count(),
        'fotos_total': fotos.count(), 'fotos_recientes': list(fotos.order_by('-id')[:8]),
        'visitas': _visibles(request).vigentes().filter(proyecto_id=r.proyecto_id).order_by('numero'),
        **revisiones.contexto(user, r, tipo(CLAVE)),
    })


@require_POST
@_acceso('reg.cargar_datos')
def datos(request, pk):
    r = _obtener(request, pk)
    acciones.exigir_escritura(request.user, r)
    form = DatosVisitaForm(request.POST, instance=r, usuario=request.user,
                           puede_cambiar_responsable=tiene_capacidad(request.user, 'reg.cambiar_responsable', request.empresa))
    if form.is_valid():
        try:
            form.save()
            messages.success(request, 'Datos de la visita actualizados.')
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
    else:
        messages.error(request, '; '.join(e for errs in form.errors.values() for e in errs))
    return redirect('reg_construccion_base:detalle', pk=pk)


@require_POST
@_acceso('reg.concluir')
def emitir(request, pk):
    """Emite la visita (queda de solo lectura). Exige que los pasos obligatorios estén completos. Para corregir una
    visita emitida se crea una REVISIÓN (no se reabre)."""
    r = _obtener(request, pk)
    if r.concluido:
        raise Http404
    if not puede_escribir(request.user, r):
        raise PermissionDenied
    faltan = servicios.faltan_para_emitir(r)
    if faltan:
        messages.error(request, 'Antes de emitir completa: ' + ', '.join(faltan) + '.')
        return redirect('reg_construccion_base:detalle', pk=pk)
    r.concluido, r.emitido_en, r.emitido_por = True, timezone.now(), request.user
    r.save(update_fields=['concluido', 'emitido_en', 'emitido_por', 'updated_at'])
    messages.success(request, 'Visita emitida: quedó de solo lectura.')
    return redirect('reg_construccion_base:detalle', pk=pk)


@require_POST
@_acceso()
def reabrir(request, pk):
    """Reabre una visita emitida para seguir editándola. Solo con `reg.reabrir` (Administrador/Coordinador) o superusuario."""
    r = _obtener(request, pk)
    if not r.concluido:
        raise Http404
    if not (request.user.is_superuser or tiene_capacidad(request.user, 'reg.reabrir', request.empresa)):
        raise PermissionDenied
    r.concluido, r.emitido_en, r.emitido_por = False, None, None
    r.save(update_fields=['concluido', 'emitido_en', 'emitido_por', 'updated_at'])
    messages.success(request, 'Visita reabierta: ya se puede editar.')
    return redirect('reg_construccion_base:detalle', pk=pk)


@require_POST
@_acceso()
def eliminar(request, pk):
    acciones.exigir_superusuario(request.user)
    r = _obtener(request, pk)
    if r.concluido:
        messages.error(request, 'Una visita emitida no se puede eliminar: crea una revisión.')
        return redirect('reg_construccion_base:detalle', pk=pk)
    r.soft_delete()
    if r.rev_vigente:   # si era la vigente, la más reciente de las que quedan toma su lugar
        resto = r.revisiones().order_by('-rev_numero').first()
        if resto is not None:
            revisiones.elegir_vigente(resto)
    messages.success(request, 'Visita eliminada.')
    return redirect('reg_construccion_base:lista')


@require_POST
@_acceso('reg.cargar_datos')
def nueva_visita(request, pk):
    """Otra visita del mismo proyecto (hoy, o la fecha indicada) con el contratista de la última."""
    base = _obtener(request, pk)
    try:
        fecha = date.fromisoformat(request.POST.get('fecha') or date.today().isoformat())
    except ValueError:
        messages.error(request, 'Fecha inválida.')
        return redirect('reg_construccion_base:detalle', pk=pk)
    m_es_ito = not tiene_capacidad(request.user, 'reg.alcance.todo', request.empresa) and not request.user.is_superuser
    try:
        nueva_ = RegConstruccionBase.objects.create(
            empresa=base.empresa, proyecto=base.proyecto, fecha=fecha, contratista=base.contratista,
            user=request.user if m_es_ito else base.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect('reg_construccion_base:detalle', pk=pk)
    messages.success(request, f'Visita {nueva_.numero} del {fecha:%d/%m/%Y} creada.')
    return redirect('reg_construccion_base:detalle', pk=nueva_.pk)


@_acceso()
def pdf(request, pk):
    """Reporte de visita en PDF. `?cols_actividades|hallazgos|seguimiento|libro=1|2` fija las fotos por fila."""
    from .pdf import reporte
    r = _obtener(request, pk, 'proyecto__tipo')
    columnas = {k: int(request.GET[f'cols_{k}']) for k, _ in reporte.SECCIONES_FOTOS
                if request.GET.get(f'cols_{k}') in ('1', '2')}
    resp = HttpResponse(reporte.generar(r, columnas), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{reporte.nombre_archivo(r)}"'
    return resp


# ── Hallazgos ───────────────────────────────────────────────────────────────────

def _hallazgos_visibles(request):
    return (Hallazgo.objects.filter(empresa=request.empresa, is_deleted=False, visita__in=_visibles(request))
            .select_related('visita', 'proyecto'))


def _hallazgo(request, pk):
    return get_object_or_404(_hallazgos_visibles(request), pk=pk)


@_acceso()
def hallazgos(request):
    qs = _hallazgos_visibles(request).filter(visita__rev_vigente=True)
    estado, severidad = request.GET.get('estado', ''), request.GET.get('severidad', '')
    vencidos = request.GET.get('vencidos') == '1'
    try:
        proyecto = int(request.GET.get('proyecto', ''))
    except ValueError:
        proyecto = None
    if estado in dict(Hallazgo.Estado.choices):
        qs = qs.filter(estado=estado)
    elif not estado:
        qs = qs.exclude(estado=Hallazgo.Estado.CERRADO)   # por defecto, lo que sigue pendiente
    if severidad in dict(Hallazgo.Severidad.choices):
        qs = qs.filter(severidad=severidad)
    if proyecto:
        qs = qs.filter(proyecto_id=proyecto)
    if vencidos:
        qs = qs.filter(plazo__lt=date.today()).exclude(estado=Hallazgo.Estado.CERRADO)
    pagina = Paginator(qs.order_by('proyecto__codigo', 'numero'), POR_PAGINA).get_page(request.GET.get('page'))
    return render(request, 'reg_construccion_base/hallazgos.html', {
        'pagina': pagina, 'estado': estado, 'severidad': severidad, 'vencidos': vencidos, 'proyecto': proyecto,
        'proyecto_txt': str(proyecto or ''),
        'estados': Hallazgo.Estado.choices, 'severidades': Hallazgo.Severidad.choices,
        'proyectos': Proyecto.objects.de_empresa(request.empresa).order_by('codigo', 'nombre'),
    })


@_acceso('reg.cargar_datos')
def hallazgo_nuevo(request, pk):
    visita = _obtener(request, pk)
    acciones.exigir_escritura(request.user, visita)
    form = HallazgoForm(request.POST or None, empresa=request.empresa)
    if request.method == 'POST' and form.is_valid():
        h = form.save(commit=False)
        h.empresa, h.proyecto, h.visita, h.creado_por = request.empresa, visita.proyecto, visita, request.user
        h.save()
        messages.success(request, f'{h.codigo} registrado. Puedes agregarle fotos.')
        return redirect('reg_construccion_base:hallazgo_detalle', pk=h.pk)
    return render(request, 'reg_construccion_base/hallazgo_form.html', {'form': form, 'visita': visita, 'h': None})


@_acceso()
def hallazgo_detalle(request, pk):
    from reg_base.tipos import tipo
    from reg_fotos.models import Foto
    from django.contrib.contenttypes.models import ContentType
    h = _hallazgo(request, pk)
    ct = ContentType.objects.get_for_model(RegConstruccionBase)
    fotos = Foto.objects.filter(content_type=ct, object_id=h.visita_id, etapa=h.etapa_fotos).order_by('orden', 'id')
    return render(request, 'reg_construccion_base/hallazgo_detalle.html', {
        'h': h, 'tipo': tipo(CLAVE), 'fotos': fotos,
        'seguimientos': h.seguimientos.select_related('visita').order_by('creado', 'id'),
        'puede_editar': puede_escribir(request.user, h.visita),
    })


@_acceso('reg.cargar_datos')
def hallazgo_editar(request, pk):
    h = _hallazgo(request, pk)
    acciones.exigir_escritura(request.user, h.visita)
    form = HallazgoForm(request.POST or None, instance=h, empresa=request.empresa)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'{h.codigo} actualizado.')
        return redirect('reg_construccion_base:hallazgo_detalle', pk=h.pk)
    return render(request, 'reg_construccion_base/hallazgo_form.html', {'form': form, 'visita': h.visita, 'h': h})


@require_POST
@_acceso('reg.cargar_datos')
def hallazgo_eliminar(request, pk):
    h = _hallazgo(request, pk)
    acciones.exigir_escritura(request.user, h.visita)
    if h.seguimientos.exists():
        messages.error(request, 'Este hallazgo ya tiene seguimientos en otras visitas: no se puede eliminar.')
        return redirect('reg_construccion_base:hallazgo_detalle', pk=pk)
    h.is_deleted = True
    h.save(update_fields=['is_deleted', 'actualizado'])
    messages.success(request, f'{h.codigo} eliminado.')
    return redirect('reg_construccion_base:detalle', pk=h.visita_id)
