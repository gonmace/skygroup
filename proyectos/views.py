from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Prefetch, Q, Value, When
from django.db.models.functions import Coalesce, Lower, NullIf
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from cuentas.capacidades import requiere_capacidad, tiene_capacidad

from .forms import ProyectoForm, TipoProyectoForm, UbicacionFormSet
from .models import Proyecto, ProyectoUbicacion, TipoProyecto

POR_PAGINA = 25

# Columnas ordenables de la tabla: clave de la URL → (título, expresión de orden). El estado se ordena por su
# lugar en el ciclo de vida, no alfabéticamente.
COLUMNAS = [
    ('codigo', 'Código', Lower('codigo')),
    ('nombre', 'Nombre', Lower('nombre')),
    ('tipo', 'Tipo', Lower('tipo__nombre')),
    ('ubicacion', 'Ubicación', Lower(Coalesce(NullIf('comuna', Value('')), 'ciudad'))),
    ('estado', 'Estado', Case(*[When(estado=v, then=Value(i)) for i, v in enumerate(Proyecto.Estado.values)],
                              output_field=IntegerField())),
]


def _empresa(request):
    empresa = getattr(request, 'empresa', None)
    if empresa is None:
        raise Http404
    return empresa


@requiere_capacidad('proyectos.view')
def lista(request):
    empresa = _empresa(request)
    qs = Proyecto.objects.de_empresa(empresa).activos().select_related('tipo')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(codigo__icontains=q)
                       | Q(ciudad__icontains=q) | Q(comuna__icontains=q))
    estado = request.GET.get('estado', '')
    if estado in Proyecto.Estado.values:
        qs = qs.filter(estado=estado)
    # Botones de tipo (con cantidad, según la búsqueda y el estado elegidos). El filtro por tipo solo rige en la lista:
    # el mapa tiene sus propios botones y filtra sin volver al servidor.
    cuenta_tipos = dict(qs.order_by().values_list('tipo').annotate(n=Count('pk')))
    tipo = request.GET.get('tipo', '')
    tipo = int(tipo) if tipo.isdigit() else None
    if tipo is not None and request.GET.get('vista') != 'mapa':
        qs = qs.filter(tipo_id=tipo)
    else:
        tipo = None
    orden = request.GET.get('orden', '')
    descendente = request.GET.get('dir') == 'desc'
    expresion = {k: e for k, _, e in COLUMNAS}.get(orden)
    if expresion is not None:
        qs = qs.order_by(expresion.desc(nulls_last=True) if descendente else expresion.asc(nulls_last=True), 'pk')
    else:
        orden = ''
    vista = 'mapa' if request.GET.get('vista') == 'mapa' else 'lista'
    ubicar = request.GET.get('ubicar', '')
    ubicar = int(ubicar) if ubicar.isdigit() else None   # proyecto al que volar al abrir el mapa
    pagina, puntos = None, []
    if vista == 'mapa':
        # Todos los proyectos filtrados (sin paginar) que tengan al menos una ubicación. `tipo` va en el punto para
        # que el mapa filtre por tipo sin volver al servidor.
        sin_tipo = empresa.termino_proyecto_singular
        for p in qs.prefetch_related(Prefetch('ubicaciones', queryset=ProyectoUbicacion.objects.order_by('pk'))):
            u = next(iter(p.ubicaciones.all()), None)
            if u:
                puntos.append({
                    'id': p.pk, 'lat': float(u.lat), 'lon': float(u.lon), 'nombre': p.nombre, 'codigo': p.codigo,
                    'estado': p.estado, 'estado_txt': p.get_estado_display(),
                    'tipo': p.tipo.nombre if p.tipo_id else sin_tipo,
                    'url': reverse('proyectos:detalle', args=[p.pk]),
                })
    else:
        qs = qs.annotate(tiene_ubicacion=Exists(ProyectoUbicacion.objects.filter(proyecto=OuterRef('pk'))))
        pagina = Paginator(qs, POR_PAGINA).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    params.pop('vista', None)
    params.pop('ubicar', None)
    base_tipos = params.copy()
    base_tipos.pop('tipo', None)
    botones_tipo = []
    tipos_con_datos = [t for t in empresa.tipos_proyecto.all() if cuenta_tipos.get(t.pk)]
    if len(tipos_con_datos) > 1:
        botones_tipo.append({'nombre': 'Todos', 'n': sum(cuenta_tipos.values()), 'activo': tipo is None,
                             'url': '?' + base_tipos.urlencode()})
        for t in tipos_con_datos:
            q_t = base_tipos.copy()
            q_t['tipo'] = t.pk
            botones_tipo.append({'nombre': t.nombre, 'n': cuenta_tipos[t.pk], 'activo': tipo == t.pk,
                                 'url': '?' + q_t.urlencode()})
    base = params.copy()
    for k in ('orden', 'dir'):
        base.pop(k, None)
    columnas = []
    for clave, titulo, _ in COLUMNAS:
        siguiente = 'desc' if (orden == clave and not descendente) else 'asc'
        base_q = base.copy()
        base_q['orden'], base_q['dir'] = clave, siguiente
        columnas.append({
            'titulo': titulo, 'url': '?' + base_q.urlencode(),
            'activa': orden == clave, 'desc': orden == clave and descendente,
        })
    return render(request, 'proyectos/lista.html', {
        'vista': vista, 'ubicar': ubicar, 'orden': orden, 'dir': 'desc' if descendente else 'asc', 'columnas': columnas, 'pagina': pagina, 'puntos': puntos, 'q': q, 'estado': estado,
        'tipo_sel': tipo, 'qs_filtros': params.urlencode(), 'botones_tipo': botones_tipo,
        'estados': Proyecto.Estado.choices,
        'puede_gestionar': tiene_capacidad(request.user, 'proyectos.manage', empresa),
        'etiquetas_pendientes': _etiquetas_pendientes(request, empresa),
    })


def _etiquetas_pendientes(request, empresa):
    """Proyectos que Jornadas detectó en los reportes y aún no están en el modelo (solo para quien puede agregarlos)."""
    if not (empresa.tiene_modulo('jor') and tiene_capacidad(request.user, 'proyectos.manage', empresa)
            and tiene_capacidad(request.user, 'jor.etiquetas.manage', empresa)):
        return []
    from jor_actividades.servicios import etiquetas_pendientes_de_proyecto
    return list(etiquetas_pendientes_de_proyecto(empresa))


@requiere_capacidad('proyectos.view')
def detalle(request, pk):
    proyecto = get_object_or_404(
        Proyecto.objects.de_empresa(_empresa(request)).activos().select_related('tipo'), pk=pk,
    )
    empresa = _empresa(request)
    puede_chat = empresa.tiene_modulo('msj') and tiene_capacidad(request.user, 'msj.usar', empresa)
    if puede_chat:
        from mje_mensajes.servicios import puede_ver_proyecto
        puede_chat = puede_ver_proyecto(request.user, empresa, proyecto)
    return render(request, 'proyectos/detalle.html', {
        'p': proyecto, 'ubicaciones': proyecto.ubicaciones.all(), 'puede_chat': puede_chat,
    })


@requiere_capacidad('proyectos.manage')
def editar(request, pk=None):
    empresa = _empresa(request)
    proyecto = get_object_or_404(Proyecto.objects.de_empresa(empresa).activos(), pk=pk) if pk else None
    form = ProyectoForm(request.POST or None, instance=proyecto, empresa=empresa)
    formset = UbicacionFormSet(request.POST or None, instance=proyecto or Proyecto(empresa=empresa))
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        proyecto = form.save()
        formset.instance = proyecto
        formset.save()
        messages.success(request, f'{request.empresa.termino_proyecto_singular} «{proyecto.nombre}» guardado.')
        return redirect('proyectos:detalle', pk=proyecto.pk)
    return render(request, 'proyectos/form.html', {'form': form, 'formset': formset, 'obj': proyecto})


@requiere_capacidad('proyectos.manage')
@require_POST
def eliminar(request, pk):
    proyecto = get_object_or_404(Proyecto.objects.de_empresa(_empresa(request)).activos(), pk=pk)
    proyecto.is_deleted = True  # borrado lógico: libera el código y conserva el historial
    proyecto.save(update_fields=['is_deleted', 'actualizado'])
    messages.success(request, f'«{proyecto.nombre}» eliminado.')
    return redirect('proyectos:lista')


# ── Tipos ─────────────────────────────────────────────────────────────────────

@requiere_capacidad('proyectos.manage')
def tipos(request):
    empresa = _empresa(request)
    form = TipoProyectoForm(request.POST or None, empresa=empresa)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Tipo creado.')
        return redirect('proyectos:tipos')
    lista = empresa.tipos_proyecto.all()
    cuenta = {t.pk: t.proyectos.filter(is_deleted=False).count() for t in lista}
    return render(request, 'proyectos/tipos.html', {
        'form': form, 'tipos': [(t, cuenta[t.pk]) for t in lista],
    })


@requiere_capacidad('proyectos.manage')
@require_POST
def tipo_eliminar(request, pk):
    tipo = get_object_or_404(TipoProyecto, pk=pk, empresa=_empresa(request))
    if tipo.proyectos.filter(is_deleted=False).exists():          # los eliminados (papelera) no cuentan: la lista tampoco
        messages.error(request, f'«{tipo.nombre}» tiene {request.empresa.termino_proyecto_plural.lower()} asociados.')
    else:
        with transaction.atomic():
            tipo.proyectos.update(tipo=None)      # los eliminados solo conservaban la referencia (FK PROTECT)
            tipo.delete()
        messages.success(request, 'Tipo eliminado.')
    return redirect('proyectos:tipos')
