from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from empresas.acceso import acceso_modulo
from jor_empleados.views import pestanas_config

from . import servicios
from .forms import COLOR, CategoriaForm
from .models import CategoriaActividad, Etiqueta


@acceso_modulo('jor', 'jor.etiquetas.manage')
def etiquetas(request):
    empresa = request.empresa
    if request.method == 'POST':             # crear
        tipo, nombre = request.POST.get('tipo'), request.POST.get('nombre', '')
        if tipo not in Etiqueta.Tipo.values:
            messages.error(request, 'Tipo de etiqueta no válido.')
        elif servicios.resolver_etiqueta(empresa, tipo, nombre) is None:
            messages.error(request, 'Escribe un nombre (o esa etiqueta está ignorada).')
        else:
            messages.success(request, 'Etiqueta lista.')
        return redirect('jor_actividades:etiquetas')
    por_tipo = []
    for valor, nombre in Etiqueta.Tipo.choices:
        raices = (Etiqueta.objects.filter(empresa=empresa, tipo=valor, canonica__isnull=True)
                  .annotate(usos=Count('items', distinct=True)).prefetch_related('alias').order_by('ignorada', 'nombre'))
        por_tipo.append({'valor': valor, 'nombre': nombre, 'etiquetas': raices})
    return render(request, 'jor_actividades/etiquetas.html', {'grupos': por_tipo, 'pestanas': pestanas_config(request, 'etiquetas')})


@acceso_modulo('jor', 'jor.etiquetas.manage')
@require_POST
def etiqueta_accion(request, pk):
    e = get_object_or_404(Etiqueta, pk=pk, empresa=request.empresa)
    accion = request.POST.get('accion')
    try:
        if accion == 'renombrar':
            color = request.POST.get('color', '')
            if color and not COLOR.match(color):
                raise servicios.ErrorEtiqueta('Usa un color hexadecimal (#rrggbb) o déjalo vacío.')
            servicios.renombrar(e, request.POST.get('nombre'), request.POST.get('codigo', ''), color)
        elif accion == 'fusionar':
            destino = get_object_or_404(Etiqueta, pk=request.POST.get('destino') if str(request.POST.get('destino')).isdigit() else 0,
                                        empresa=request.empresa)
            servicios.fusionar(e, destino)
        elif accion == 'separar':
            servicios.separar(e)
        elif accion in ('ignorar', 'restaurar'):
            e.ignorada = accion == 'ignorar'
            e.save(update_fields=['ignorada'])
        else:
            raise servicios.ErrorEtiqueta('Acción no válida.')
        messages.success(request, 'Listo.')
    except servicios.ErrorEtiqueta as err:
        messages.error(request, str(err))
    return redirect('jor_actividades:etiquetas')


@acceso_modulo('jor', 'jor.etiquetas.manage')
@require_POST
def etiquetas_a_proyectos(request):
    """Agrega al modelo Proyecto las etiquetas de proyecto elegidas en la lista de Proyectos."""
    if not tiene_capacidad(request.user, 'proyectos.manage', request.empresa):
        raise PermissionDenied
    ids = [int(x) for x in request.POST.getlist('etiqueta') if x.isdigit()]
    if not ids:
        messages.error(request, 'Elige al menos un proyecto de la lista.')
    else:
        creados, vinculados = servicios.agregar_a_proyectos(request.empresa, ids)
        partes = [f'{creados} creado{"s" if creados != 1 else ""}'] if creados else []
        if vinculados:
            partes.append(f'{vinculados} vinculado{"s" if vinculados != 1 else ""} a uno existente')
        messages.success(request, ('Agregado a proyectos: ' + ', '.join(partes) + '.') if partes else 'No había nada que agregar.')
    return redirect('proyectos:lista')


@acceso_modulo('jor', 'jor.config.manage')
def categorias(request):
    empresa = request.empresa
    form = CategoriaForm(request.POST or None, empresa=empresa)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Categoría creada.')
        return redirect('jor_actividades:categorias')
    lista = servicios.categorias(empresa).annotate(usos=Count('id') * 0)       # fuerza la siembra antes de listar
    usos = dict(empresa.items_actividad.values_list('categoria').annotate(n=Count('id')))
    filas = [(c, CategoriaForm(instance=c, empresa=empresa, prefix=f'c{c.pk}'), usos.get(c.codigo, 0)) for c in lista]
    return render(request, 'jor_actividades/categorias.html', {'form': form, 'filas': filas, 'pestanas': pestanas_config(request, 'categorias')})


@acceso_modulo('jor', 'jor.config.manage')
@require_POST
def categoria_editar(request, pk):
    c = get_object_or_404(CategoriaActividad, pk=pk, empresa=request.empresa)
    form = CategoriaForm(request.POST, instance=c, empresa=request.empresa, prefix=f'c{c.pk}')
    if form.is_valid():
        form.save()
        messages.success(request, 'Categoría guardada.')
    else:
        messages.error(request, ' '.join(e for errs in form.errors.values() for e in errs))
    return redirect('jor_actividades:categorias')
