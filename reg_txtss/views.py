from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from reg_base.acceso import acceso_tipo
from reg_base import acciones
from reg_base.alcance import puede_escribir, registros_visibles
from reg_base.estado import color_estado

from reg_actividades.servicios import contexto_pasos

from .forms import ActivarTxtssForm, ResponsableForm
from .models import ALTERNATIVAS, RegTxtss

POR_PAGINA = 25
ESTADOS = {'rojo': 3, 'amarillo': 1, 'verde': 2}


def _acceso(*caps):
    return acceso_tipo('txtss', 'reg.txtss.ver', *caps)


def _tabs(empresa):
    """Una pestaña por cada tipo de proyecto de la empresa (ninguna si no definió tipos)."""
    return list(empresa.tipos_proyecto.all())


def _volver(request, por_defecto, **kwargs):
    """Redirige a `next` (POST) si es una ruta propia; si no, al destino por defecto."""
    destino = request.POST.get('next', '')
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure()):
        return redirect(destino)
    return redirect(por_defecto, **kwargs)


def _filtrar(qs, tipo, q):
    if tipo.isdigit():
        qs = qs.filter(proyecto__tipo_id=int(tipo))
    if q:
        qs = qs.filter(Q(proyecto__nombre__icontains=q) | Q(proyecto__codigo__icontains=q)
                       | Q(proyecto__codigo_operador__icontains=q))
    return qs


def _resumen_datos(pagina):
    """Fotos, mapas y pasos con datos de cada registro de la página (para confirmar «Formatear»)."""
    from django.contrib.contenttypes.models import ContentType
    from reg_actividades.models import DatoPaso, ImagenMapa
    from reg_fotos.models import Foto
    ct = ContentType.objects.get_for_model(RegTxtss)
    ids = [r.pk for r in pagina]

    def contar(modelo, **extra):
        filas = modelo.objects.filter(content_type=ct, object_id__in=ids, **extra).values('object_id').annotate(n=Count('pk'))
        return {f['object_id']: f['n'] for f in filas}
    fotos, mapas, pasos = contar(Foto), contar(ImagenMapa), contar(DatoPaso, tiene_datos=True)
    for r in pagina:
        r.n_fotos, r.n_mapas, r.n_pasos = fotos.get(r.pk, 0), mapas.get(r.pk, 0), pasos.get(r.pk, 0)


@_acceso()
def lista(request):
    empresa, user = request.empresa, request.user
    qs = (registros_visibles(user, empresa, RegTxtss.objects.all()).with_estado()
          .select_related('proyecto', 'proyecto__tipo', 'user'))
    tabs = _tabs(empresa)
    tipo = request.GET.get('tipo', '')
    q = request.GET.get('q', '').strip()
    qs = _filtrar(qs, tipo, q)
    estado = request.GET.get('estado', '')
    if estado in ESTADOS:
        qs = qs.filter(orden_estado=ESTADOS[estado])
    pagina = Paginator(qs.order_by('orden_estado', '-fecha', '-id'), POR_PAGINA).get_page(request.GET.get('page'))
    for r in pagina:
        r.color = color_estado(r)
    es_super = user.is_superuser
    contexto = {
        'pagina': pagina, 'tabs': tabs, 'tipo': tipo, 'q': q, 'estado': estado,
        'puede_activar': tiene_capacidad(user, 'reg.activar', empresa),
        'puede_copiar': tiene_capacidad(user, 'reg.cargar_datos', empresa),
        'puede_editar': tiene_capacidad(user, 'reg.cambiar_responsable', empresa),
        'es_super': es_super, 'next': request.get_full_path(),
    }
    if contexto['puede_editar']:
        contexto['form_responsable'] = ResponsableForm(empresa=empresa, usuario=user)
    if es_super:
        _resumen_datos(pagina)
        borrados = _filtrar(RegTxtss.objects.filter(empresa=empresa, is_deleted=True)
                            .select_related('proyecto', 'proyecto__tipo', 'user'), tipo, q)
        contexto['borrados'] = Paginator(borrados.order_by('-updated_at', '-id'), POR_PAGINA).get_page(request.GET.get('pb'))
    return render(request, 'reg_txtss/lista.html', contexto)


@_acceso('reg.activar')
def activar(request):
    empresa, user = request.empresa, request.user
    puede_elegir = tiene_capacidad(user, 'reg.cambiar_responsable', empresa)
    form = ActivarTxtssForm(request.POST or None, empresa=empresa, usuario=user, puede_elegir_responsable=puede_elegir)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        responsable = d.get('user') or user
        creados = existian = 0
        with transaction.atomic():
            for proyecto in d['proyectos']:
                clave = dict(empresa=empresa, proyecto=proyecto, user=responsable, fecha=d['fecha'], alternativa=d['alternativa'])
                # Los borrados no cuentan: solo el superusuario los restaura (desde la papelera de la lista).
                if RegTxtss.objects.filter(is_deleted=False, **clave).exists():
                    existian += 1
                else:
                    RegTxtss.objects.create(**clave)
                    creados += 1
        if creados:
            messages.success(request, f'{creados} registro{"s" if creados != 1 else ""} activado{"s" if creados != 1 else ""}.')
        if existian:
            messages.info(request, f'{existian} ya existía{"n" if existian != 1 else ""}.')
        if len(d['proyectos']) == 1 and creados:
            r = RegTxtss.objects.filter(empresa=empresa, proyecto=d['proyectos'][0], user=responsable,
                                        fecha=d['fecha'], alternativa=d['alternativa'], is_deleted=False).first()
            if r:
                return redirect('reg_txtss:detalle', pk=r.pk)
        return redirect('reg_txtss:lista')
    return render(request, 'reg_txtss/activar.html', {'form': form})


@_acceso()
def detalle(request, pk):
    r = acciones.obtener_registro(request, RegTxtss, pk, 'proyecto__tipo')
    user, empresa = request.user, request.empresa
    qs = RegTxtss.objects.filter(pk=r.pk).with_estado()
    r.color = color_estado(qs.get())
    return render(request, 'reg_txtss/detalle.html', {
        'r': r, **_fotos_ctx(r), **contexto_pasos(request, r, 'txtss', puede_escribir(user, r)),
        'puede_escribir': puede_escribir(user, r),
        'puede_concluir': tiene_capacidad(user, 'reg.reabrir' if r.concluido else 'reg.concluir', empresa),
        'puede_cambiar_responsable': tiene_capacidad(user, 'reg.cambiar_responsable', empresa) and not r.concluido,
        'form_responsable': ResponsableForm(initial={'user': r.user, 'alternativa': r.alternativa}, empresa=empresa, usuario=user),
        'siguiente': r.siguiente_alternativa,
    })


@require_POST
@_acceso()
def concluir(request, pk):
    r = acciones.obtener_registro(request, RegTxtss, pk)
    concluido = acciones.alternar_concluido(request.user, r)
    messages.success(request, 'Registro concluido.' if concluido else 'Registro reabierto.')
    return redirect('reg_txtss:detalle', pk=r.pk)


@require_POST
@_acceso('reg.cargar_datos')
def copiar(request, pk):
    """Copia el registro con la alternativa siguiente (A→B→…→E)."""
    r = acciones.obtener_registro(request, RegTxtss, pk)   # el alcance lo fija obtener_registro
    siguiente = r.siguiente_alternativa
    if siguiente is None:
        messages.error(request, f'No hay una alternativa después de {r.alternativa or "A"}.')
        return _volver(request, 'reg_txtss:detalle', pk=r.pk)
    clave = dict(empresa=r.empresa, proyecto=r.proyecto, user=r.user, fecha=r.fecha, alternativa=siguiente)
    if RegTxtss.objects.filter(is_deleted=False, **clave).exists():
        messages.error(request, f'Ya existe un registro con la alternativa {siguiente} para este proyecto y fecha.')
        return _volver(request, 'reg_txtss:detalle', pk=r.pk)
    nuevo = RegTxtss.objects.create(**clave)
    messages.success(request, f'Registro copiado con la alternativa {siguiente}.')
    return _volver(request, 'reg_txtss:detalle', pk=nuevo.pk)


@require_POST
@_acceso('reg.cargar_datos')
def cambiar_fecha(request, pk):
    r = acciones.obtener_registro(request, RegTxtss, pk)
    acciones.exigir_escritura(request.user, r)
    from datetime import date
    try:
        r.fecha = date.fromisoformat(request.POST.get('fecha', ''))
        r.save(update_fields=['fecha', 'updated_at'])
        messages.success(request, 'Fecha actualizada.')
    except ValueError:
        messages.error(request, 'Fecha inválida.')
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect('reg_txtss:detalle', pk=r.pk)


@require_POST
@_acceso('reg.cambiar_responsable')
def cambiar_responsable(request, pk):
    r = acciones.obtener_registro(request, RegTxtss, pk)
    if r.concluido:
        messages.error(request, 'El registro está concluido: reábrelo para modificarlo.')
        return _volver(request, 'reg_txtss:detalle', pk=r.pk)
    form = ResponsableForm(request.POST, empresa=request.empresa, usuario=request.user)
    if form.is_valid():
        r.user = form.cleaned_data['user'] or r.user
        r.alternativa = form.cleaned_data['alternativa']
        try:
            r.save(update_fields=['user', 'alternativa', 'updated_at'])
            messages.success(request, 'Registro actualizado.')
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
    else:
        messages.error(request, 'Datos inválidos.')
    return _volver(request, 'reg_txtss:detalle', pk=r.pk)


@require_POST
@_acceso()
def eliminar(request, pk):
    acciones.exigir_superusuario(request.user)
    r = acciones.obtener_registro(request, RegTxtss, pk)
    r.soft_delete()
    messages.success(request, 'Registro eliminado. Solo el superusuario puede restaurarlo.')
    return _volver(request, 'reg_txtss:lista')


@require_POST
@_acceso()
def restaurar(request, pk):
    acciones.exigir_superusuario(request.user)
    r = get_object_or_404(RegTxtss, pk=pk, empresa=request.empresa, is_deleted=True)
    try:
        r.restore()
        messages.success(request, 'Registro restaurado.')
    except ValidationError as exc:
        messages.error(request, f'No se pudo restaurar: {exc.messages[0]}')
    return _volver(request, 'reg_txtss:lista')


@require_POST
@_acceso()
def formatear(request, pk):
    """Borra fotos, mapas y datos de pasos del registro y lo deja abierto (solo superusuario, no concluidos)."""
    acciones.exigir_superusuario(request.user)
    r = acciones.obtener_registro(request, RegTxtss, pk)
    if r.concluido:
        messages.error(request, 'El registro está concluido: reábrelo para formatearlo.')
        return _volver(request, 'reg_txtss:detalle', pk=r.pk)
    n = acciones.formatear_registro(r)
    messages.success(request, f'Registro formateado: {n["fotos"]} fotos, {n["mapas"]} mapas y {n["pasos"]} pasos borrados.')
    return _volver(request, 'reg_txtss:detalle', pk=r.pk)


def _fotos_ctx(registro):
    from reg_fotos.servicios import fotos_de
    fotos = fotos_de(registro)
    return {'fotos_total': fotos.count(), 'fotos_recientes': list(fotos.order_by('-id')[:6])}


@_acceso()
def pdf(request, pk):
    """PDF «TX / Technical Site Survey». `?cols_<paso>=1|2` fija las fotos por fila de cada sección."""
    from django.http import HttpResponse
    from .pdf import reporte
    r = acciones.obtener_registro(request, RegTxtss, pk, 'proyecto__tipo')
    columnas = {k[5:]: int(v) for k, v in request.GET.items() if k.startswith('cols_') and v in ('1', '2')}
    resp = HttpResponse(reporte.generar(r, columnas, request.user), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{reporte.nombre_archivo(r)}"'
    return resp
