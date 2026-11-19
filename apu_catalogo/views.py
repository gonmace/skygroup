from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, ProtectedError, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from proyectos.models import Proyecto

from apu_motor import PerfilInvalido, validar_perfil

from . import categorias as cats, conversion, editor, unidades
from .acceso import acceso_apu
from .forms import MODOS, InsumoForm, PerfilDatosForm
from . import calculo
from .models import CategoriaAPU, Insumo, ItemModelo, PerfilCalculo, PrecioInsumo, ProyectoAPU, Tipo


@acceso_apu('apu.ver')
def inicio(request):
    from apu_generador import creditos
    from apu_generador.models import APUBorrador
    empresa = request.empresa
    perfiles = PerfilCalculo.objects.filter(Q(empresa=empresa) | Q(empresa__isnull=True), activo=True)
    puede_generar = tiene_capacidad(request.user, 'apu.catalogo.manage', empresa)
    pendientes = APUBorrador.objects.filter(empresa=empresa, eliminado=False, guardado=False, creado_por=request.user)
    return render(request, 'apu_catalogo/inicio.html', {
        'resumen': [('calculator', 'APU', ItemModelo.objects.filter(empresa=empresa).count()),
                    ('tag', 'Insumos', Insumo.objects.filter(empresa=empresa).count()),
                    ('clock', 'Pendientes tuyos', pendientes.count())],
        'creditos': creditos.resumen(request.user, empresa),
        'recientes': ItemModelo.objects.filter(empresa=empresa).select_related('proyecto').order_by('-creado', '-pk')[:5],
        'perfiles': perfiles, 'puede_generar': puede_generar,
        'puede_perfiles': tiene_capacidad(request.user, 'apu.perfiles.manage', empresa),
        'sin_habilitados': not ProyectoAPU.objects.filter(proyecto__empresa=empresa, proyecto__is_deleted=False).exists(),
    })


@acceso_apu('apu.ver')
def perfil_detalle(request, pk):
    """Estructura de un perfil (de la empresa o plantilla de la plataforma): sus líneas y el redondeo."""
    perfil = PerfilCalculo.objects.filter(Q(empresa=request.empresa) | Q(empresa__isnull=True), pk=pk).first()
    if perfil is None:
        raise Http404
    return render(request, 'apu_catalogo/perfil.html', {
        'perfil': perfil, 'filas': perfil.filas(), 'redondeo': perfil.validado()['redondeo'],
        'puede_perfiles': tiene_capacidad(request.user, 'apu.perfiles.manage', request.empresa),
    })


@acceso_apu('apu.perfiles.manage')
@require_POST
def perfil_copiar(request, pk):
    """Copia una plantilla de la plataforma (o un perfil propio) a la empresa para ajustarla."""
    origen = PerfilCalculo.objects.filter(Q(empresa=request.empresa) | Q(empresa__isnull=True), pk=pk).first()
    if origen is None:
        raise Http404
    copia = origen.copiar_a(request.empresa)
    messages.success(request, f'Se creó el perfil «{copia.nombre}». Ajústalo y guarda los cambios.')
    return redirect('apu_catalogo:perfil_editar', pk=copia.pk)


def _perfil_propio(request, pk):
    """Un perfil de la empresa. Las plantillas de la plataforma no se tocan: se copian y se edita la copia."""
    perfil = PerfilCalculo.objects.filter(empresa=request.empresa, pk=pk).first()
    if perfil is None:
        raise Http404
    return perfil


def _redondeo_crudo(post):
    """El redondeo tal como viene del formulario, con valores por defecto si aún está incompleto (para la prueba)."""
    def entero(clave, defecto):
        v = post.get(clave, '').strip()
        return int(v) if v.isdigit() and int(v) <= 8 else defecto
    modo = post.get('modo') if post.get('modo') in dict(MODOS) else 'HALF_UP'
    return {'linea': entero('dec_linea', None), 'total': entero('dec_total', 2), 'modo': modo}


def _editor(request, perfil):
    """Crear (`perfil=None`) o editar un perfil de la empresa. El formulario completo viaja en cada envío; cada botón
    es una acción (agregar, quitar, subir, bajar, probar) y solo «guardar» persiste. Ver `editor.py`."""
    empresa = request.empresa
    guardando = False
    if request.method == 'POST':
        accion = request.POST.get('accion', 'probar')
        estado = editor.estado_desde_post(request.POST)
        editor.aplicar_accion(estado, accion)
        guardando = accion == 'guardar'
        form = (PerfilDatosForm(empresa, perfil, request.POST) if guardando
                else PerfilDatosForm(empresa, perfil, initial=request.POST.dict()))
        redondeo = form.redondeo() if guardando and form.is_valid() else _redondeo_crudo(request.POST)
    else:
        datos = perfil.datos if perfil else editor.MINIMO
        estado = editor.estado_inicial(datos)
        red = validar_perfil(datos)['redondeo']
        form = PerfilDatosForm(empresa, perfil, initial={
            'nombre': perfil.nombre if perfil else '', 'pais': perfil.pais if perfil else '',
            'moneda': perfil.moneda if perfil else '', 'dec_total': red['total'], 'dec_linea': red['linea'],
            'modo': red['modo']})
        redondeo = red

    datos, errores = editor.datos_desde_estado(estado, redondeo)
    try:
        validar_perfil(datos)
    except PerfilInvalido as e:
        errores.append(str(e))

    if guardando and form.is_valid() and not errores:
        guardado = perfil or PerfilCalculo(empresa=empresa)
        d = form.cleaned_data
        guardado.nombre, guardado.pais, guardado.moneda, guardado.datos = d['nombre'], d['pais'], d['moneda'], datos
        guardado.save()
        messages.success(request, f'Se guardó el perfil «{guardado.nombre}».')
        return redirect('apu_catalogo:perfil_detalle', pk=guardado.pk)

    filas = editor.filas_para_plantilla(estado)
    return render(request, 'apu_catalogo/perfil_form.html', {
        'perfil': perfil, 'form': form, 'filas': filas, 'errores': errores, 'estado': estado,
        'resultados_apu': [f for f in filas if f['nivel'] == 'apu' and not f['es_suma']],
        'resultados_presupuesto': [f for f in filas if f['nivel'] == 'presupuesto'],
        'prueba': [(g, editor.ETIQUETA_GRUPO[g], estado['prueba'][g]) for g in ('MAT', 'MO', 'EQ')],
        'vista_previa': editor.previsualizar(datos, estado['prueba'])})


@acceso_apu('apu.perfiles.manage')
def perfil_nuevo(request):
    return _editor(request, None)


@acceso_apu('apu.perfiles.manage')
def perfil_editar(request, pk):
    return _editor(request, _perfil_propio(request, pk))


@acceso_apu('apu.perfiles.manage')
@require_POST
def perfil_eliminar(request, pk):
    perfil = _perfil_propio(request, pk)
    nombre = perfil.nombre
    perfil.delete()
    messages.success(request, f'Se eliminó el perfil «{nombre}».')
    return redirect('apu_catalogo:inicio')


# ── Base de APU ───────────────────────────────────────────────────────────────

def _analisis_de(item):
    """Análisis del APU (precio unitario con el perfil del proyecto y estado de sus precios); None si un perfil o un dato
    roto lo impide: no debe tumbar la lista."""
    try:
        return calculo.analizar(item)
    except Exception:
        return None


@acceso_apu('apu.ver')
def items(request):
    empresa = request.empresa
    q = request.GET.get('q', '').strip()
    proyecto = request.GET.get('proyecto', '')
    categoria = request.GET.get('categoria', '')
    qs = ItemModelo.objects.filter(empresa=empresa).select_related('proyecto', 'categoria')
    if q:
        qs = qs.filter(Q(codigo__icontains=q) | Q(descripcion__icontains=q))
    if proyecto.isdigit():
        qs = qs.filter(proyecto_id=proyecto)
    if categoria.isdigit():
        qs = qs.filter(categoria_id=categoria)
    elif categoria == 'sin':
        qs = qs.filter(categoria__isnull=True)
    pagina = Paginator(qs.order_by('proyecto__nombre', 'codigo'), 25).get_page(request.GET.get('page'))
    for it in pagina:
        a = _analisis_de(it)
        it.precio_unitario = a.total if a else None
        it.estado_precios = a.estado_precios if a else ''          # semáforo: completo / parcial / ninguno / vacio
        it.n_insumos, it.n_sin_precio = (a.n_insumos, len(a.sin_precio)) if a else (0, 0)
        pa = ProyectoAPU.objects.filter(proyecto_id=it.proyecto_id).select_related('perfil').first() if it.proyecto_id else None
        it.moneda = pa.perfil.moneda if pa else ''
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'apu_catalogo/items.html', {
        'pagina': pagina, 'q': q, 'proyecto_sel': proyecto, 'categoria_sel': categoria, 'qs_filtros': params.urlencode(),
        'proyectos': Proyecto.objects.de_empresa(empresa).activos().filter(apu_items__isnull=False).distinct().order_by('nombre'),
        'categorias': CategoriaAPU.objects.filter(empresa=empresa),
        'puede_generar': tiene_capacidad(request.user, 'apu.catalogo.manage', empresa)})


@acceso_apu('apu.ver')
def item_detalle(request, pk):
    from apu_generador import ia as ia_gen
    from apu_generador.models import LlamadaIA
    empresa = request.empresa
    item = get_object_or_404(ItemModelo.objects.select_related('proyecto', 'origen', 'creado_por'), pk=pk, empresa=empresa)
    pa = ProyectoAPU.objects.filter(proyecto_id=item.proyecto_id).select_related('perfil').first() if item.proyecto_id else None
    region = request.GET.get('region')            # opcional: ver los precios de otra región; por defecto, la del proyecto
    region = region.strip() if region is not None else None
    analisis = calculo.analizar(item, region=region)
    consumo = None
    if request.user.is_superuser:
        llamadas = LlamadaIA.objects.filter(Q(apu=item) | Q(borrador__apu_guardado=item))
        ia_gen.sincronizar_uso(list(llamadas.filter(uso__isnull=True).exclude(ejecucion_id='')[:20]))
        consumo = ia_gen.resumen_uso(llamadas)
    return render(request, 'apu_catalogo/item.html', {
        'item': item, 'analisis': analisis, 'desglose': calculo.desglose(analisis.perfil, analisis.resultado),
        'proyecto_apu': pa, 'region': region if region is not None else (pa.region if pa else ''), 'consumo': consumo,
        'puede_generar': tiene_capacidad(request.user, 'apu.catalogo.manage', empresa),
        'puede_incidencias': tiene_capacidad(request.user, 'apu.perfiles.manage', empresa),
        'proyectos': Proyecto.objects.de_empresa(empresa).activos().filter(apu__isnull=False).order_by('nombre'),
        'con_apu': set(ProyectoAPU.objects.filter(proyecto__empresa=empresa).values_list('proyecto_id', flat=True))})


def _lista_proyectos(empresa):
    return (Proyecto.objects.de_empresa(empresa).activos()
            .annotate(n_apu=Count('apu_items', distinct=True)).filter(Q(n_apu__gt=0) | Q(apu__isnull=False))
            .select_related('apu__perfil').order_by('nombre'))


def _permisos_proyectos(request, empresa):
    return {'puede_incidencias': tiene_capacidad(request.user, 'apu.perfiles.manage', empresa),
            'puede_generar': tiene_capacidad(request.user, 'apu.catalogo.manage', empresa)}


@acceso_apu('apu.ver')
def proyectos(request):
    """Solo el resumen de cada proyecto; el listado de sus APU está en el detalle (`proyecto_detalle`)."""
    empresa = request.empresa
    tarjetas = []
    for p in _lista_proyectos(empresa):
        r = calculo.resumen_proyecto(p)
        r.pop('filas', None)               # aquí no se listan los APU
        tarjetas.append({'proyecto': p, 'resumen': r})
    return render(request, 'apu_catalogo/proyectos.html', {
        'tarjetas': tarjetas, **_permisos_proyectos(request, empresa),
        'puede_proyectos': tiene_capacidad(request.user, 'proyectos.manage', empresa),
        'hay_sin_habilitar': Proyecto.objects.de_empresa(empresa).activos().filter(apu__isnull=True).exists()})


@acceso_apu('apu.ver')
def proyecto_detalle(request, pk):
    """Detalle de un proyecto: su resumen y el listado de todos sus APU (con las cantidades editables)."""
    empresa = request.empresa
    elegido = get_object_or_404(_lista_proyectos(empresa), pk=pk)
    return render(request, 'apu_catalogo/proyecto_detalle.html', {
        'elegido': elegido, 'resumen': calculo.resumen_proyecto(elegido), **_permisos_proyectos(request, empresa)})


@acceso_apu('apu.ver')
def proyecto_pdf(request, pk):
    """PDF con el resumen del proyecto y la composición de cada uno de sus APU."""
    from . import pdf
    elegido = get_object_or_404(_lista_proyectos(request.empresa), pk=pk)
    resp = HttpResponse(pdf.generar(elegido), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="APU-{elegido.codigo or elegido.pk}.pdf"'
    return resp


@acceso_apu('apu.perfiles.manage')
def habilitar(request):
    """Habilita un proyecto para APU: elige su perfil de cálculo (siempre uno de la empresa; una plantilla se copia) y la región
    de sus precios. La descripción del proyecto es la que ya tiene: no se pide ni se valida aquí. Es el primer paso del módulo."""
    from apu_generador import asistente
    empresa = request.empresa
    pendientes = Proyecto.objects.de_empresa(empresa).activos().filter(apu__isnull=True).order_by('nombre')
    clave = request.POST.get('proyecto') or request.GET.get('proyecto') or ''
    elegido = pendientes.filter(pk=clave).first() if clave.isdigit() else None
    if request.method == 'POST':
        if elegido is None:
            messages.error(request, 'Elige un proyecto de tu empresa que aún no esté habilitado.')
        else:
            try:
                asistente.asegurar_proyecto_apu(elegido, request.POST.get('perfil'), empresa, request.POST.get('region'))
            except asistente.ErrorPaso as e:
                messages.error(request, str(e))
            else:
                messages.success(request, f'Se habilitó «{elegido.nombre}» para APU. Ya puedes generar sus APU.')
                return redirect('apu_generador:nuevo')
    return render(request, 'apu_catalogo/habilitar.html', {
        'pendientes': pendientes, 'elegido': elegido,
        'perfil_sel': request.POST.get('perfil', ''), 'region': request.POST.get('region', ''), 'perfiles': PerfilCalculo.propios(empresa),
        'plantillas': PerfilCalculo.objects.filter(empresa__isnull=True, activo=True),
        'hay_proyectos': Proyecto.objects.de_empresa(empresa).activos().exists(),
        'puede_proyectos': tiene_capacidad(request.user, 'proyectos.manage', empresa)})


def _pct(valor):
    return format((valor * 100).normalize(), 'f')


@acceso_apu('apu.perfiles.manage')
def incidencias(request, pk):
    """Ajusta, solo para este proyecto, los porcentajes y factores del perfil de cálculo (p. ej. Gastos generales 12 %).
    El precio de los APU del proyecto no se guarda: cambia en cuanto se guardan las incidencias."""
    empresa = request.empresa
    proyecto = get_object_or_404(Proyecto.objects.de_empresa(empresa).activos(), pk=pk)
    pa = ProyectoAPU.objects.select_related('perfil').filter(proyecto=proyecto).first()
    perfiles = PerfilCalculo.objects.filter(Q(empresa=empresa, activo=True) | Q(pk=pa.perfil_id if pa else 0))
    if request.method == 'POST':
        perfil = perfiles.filter(pk=request.POST.get('perfil') or 0).first() or (pa.perfil if pa else None)
    else:
        perfil = pa.perfil if pa else perfiles.first()
    if perfil is None:
        messages.error(request, 'No hay perfiles de cálculo. Crea uno primero.')
        return redirect('apu_catalogo:inicio')
    base = perfil.validado()
    ajustes_actuales = pa.ajustes if pa and pa.perfil_id == perfil.pk else {}
    errores, valores = {}, {}
    for l in base['lineas']:
        if l['tipo'] not in ('suma', 'porcentaje'):
            continue
        es_pct = l['tipo'] == 'porcentaje'
        base_v = l['pct'] if es_pct else l['factor']
        actual = Decimal(str(ajustes_actuales[l['cod']])) if l['cod'] in ajustes_actuales else base_v
        valores[l['cod']] = {'cod': l['cod'], 'nombre': l['nombre'], 'es_pct': es_pct, 'base': base_v,
                             'base_txt': _pct(base_v) if es_pct else format(base_v.normalize(), 'f'),
                             'valor_txt': _pct(actual) if es_pct else format(actual.normalize(), 'f'),
                             'nivel': l['nivel']}
    accion = request.POST.get('accion') if request.method == 'POST' else ''
    if request.method == 'POST':
        nuevos = {}
        for cod, v in valores.items():
            texto = request.POST.get(f'aj_{cod}')
            texto = (v['valor_txt'] if texto is None else texto).strip().replace(',', '.') or v['base_txt']   # vacío = el del perfil
            v['valor_txt'] = texto
            try:
                n = Decimal(texto)
            except InvalidOperation:
                errores[cod] = v['error'] = 'Indica un número.'
                continue
            n = n / 100 if v['es_pct'] else n
            if n != v['base']:
                nuevos[cod] = str(n)
        candidato = ProyectoAPU(proyecto=proyecto, perfil=perfil, ajustes=nuevos)
        efectivo = None
        if not errores:
            try:
                efectivo = candidato.perfil_efectivo()
            except Exception as e:
                errores['general'] = str(e)
    else:
        nuevos, candidato, efectivo = ajustes_actuales, pa, None
    items_proyecto = list(ItemModelo.objects.filter(proyecto=proyecto, empresa=empresa).order_by('codigo')[:5])
    region = request.POST.get('region', pa.region if pa else '').strip()[:80] if request.method == 'POST' else (pa.region if pa else '')
    if request.method == 'POST' and accion == 'guardar' and not errores:
        ProyectoAPU.objects.update_or_create(proyecto=proyecto, defaults={'perfil': perfil, 'ajustes': nuevos, 'region': region})
        messages.success(request, f'Se guardaron las incidencias de «{proyecto.nombre}»: cambia el precio de sus '
                                  f'{ItemModelo.objects.filter(proyecto=proyecto).count()} APU.')
        return redirect('apu_catalogo:proyectos')
    vista_previa = []
    if efectivo and request.method == 'POST':
        base_perfil = perfil.validado()
        for it in items_proyecto:
            antes = calculo.analizar(it, perfil=base_perfil if not pa else pa.perfil_efectivo() if pa.perfil_id == perfil.pk else base_perfil)
            despues = calculo.analizar(it, perfil=efectivo)
            vista_previa.append({'item': it, 'antes': antes.total, 'despues': despues.total, 'moneda': perfil.moneda})
    huerfanos = pa.ajustes_huerfanos() if pa and pa.perfil_id == perfil.pk else []
    return render(request, 'apu_catalogo/incidencias.html', {
        'proyecto': proyecto, 'region': region, 'perfil': perfil, 'perfiles': perfiles, 'lineas': list(valores.values()), 'errores': errores,
        'ajustados': set(nuevos), 'vista_previa': vista_previa, 'huerfanos': huerfanos, 'n_apu': ItemModelo.objects.filter(proyecto=proyecto).count()})


def _insumos_filtrados(empresa, q, tipo, solo_sin_precio):
    """Insumos de la empresa según los filtros de la lista (los mismos para listar y para eliminar en bloque)."""
    qs = Insumo.objects.filter(empresa=empresa)
    if q:
        qs = qs.filter(Q(codigo__icontains=q) | Q(descripcion__icontains=q))
    if tipo in Tipo.values:
        qs = qs.filter(tipo=tipo)
    if solo_sin_precio:
        qs = qs.filter(precios__isnull=True)
    return qs


@acceso_apu('apu.ver')
def insumos(request):
    empresa = request.empresa
    q = request.GET.get('q', '').strip()
    tipo = request.GET.get('tipo', '')
    solo_sin_precio = request.GET.get('sin_precio') == '1'
    qs = _insumos_filtrados(empresa, q, tipo, solo_sin_precio).prefetch_related(
        Prefetch('precios', queryset=PrecioInsumo.objects.filter(region='', proyecto__isnull=True).order_by('-fecha'), to_attr='precios_nacionales'))
    todos = Insumo.objects.filter(empresa=empresa)
    conteos = dict(todos.values_list('tipo').annotate(n=Count('pk')))
    pagina = Paginator(qs.order_by('tipo', 'codigo'), 40).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    # Se separan por tipo (material, mano de obra, equipo) conservando el orden de la página.
    grupos = [{'tipo': v, 'nombre': l, 'insumos': [i for i in pagina if i.tipo == v]} for v, l in Tipo.choices]
    return render(request, 'apu_catalogo/insumos.html', {
        'grupos': [g for g in grupos if g['insumos']],
        'puede_editar': tiene_capacidad(request.user, 'apu.catalogo.manage', empresa), 'es_super': request.user.is_superuser,
        'n_filtrados': pagina.paginator.count, 'pagina': pagina, 'q': q, 'tipo_sel': tipo, 'tipos': Tipo.choices, 'qs_filtros': params.urlencode(),
        'tipos_conteo': [(v, l, conteos.get(v, 0)) for v, l in Tipo.choices], 'n_total': sum(conteos.values()),
        'solo_sin_precio': solo_sin_precio,
        'n_sin_precio': todos.filter(precios__isnull=True).count(),
        'hay_filtros': bool(q or tipo or solo_sin_precio)})


@acceso_apu('apu.catalogo.manage')
def insumo_editar(request, pk):
    insumo = get_object_or_404(Insumo, pk=pk, empresa=request.empresa)
    antes = insumo.unidad
    form = InsumoForm(request.empresa, request.POST or None, instance=insumo)
    if request.method == 'POST' and form.is_valid():
        nueva = unidades.normalizar(form.cleaned_data['unidad'])[:20]
        factor = unidades.factor(antes, nueva) if nueva != unidades.normalizar(antes) else None
        if factor:      # unidad convertible (p. ej. m² → pie²): sus cantidades y precios se recalculan para no cambiar el costo
            insumo.unidad = antes
            form.save()
            lineas, precios = conversion.cambiar_unidad(insumo, nueva, factor)
            messages.success(request, f'Se guardó el insumo «{insumo.descripcion}». La unidad pasó de «{antes}» a «{nueva}» (×{factor:.4f}): '
                                      f'se convirtieron {lineas} línea(s) de APU y {precios} precio(s).')
        else:
            form.save()
            messages.success(request, f'Se guardó el insumo «{insumo.descripcion}».')
            if unidades.normalizar(antes) != unidades.normalizar(insumo.unidad) and (
                    insumo.usos.exists() or insumo.precios.exists()):
                messages.warning(request, f'Cambiaste la unidad de «{antes}» a «{insumo.unidad}», pero no se pueden convertir solas: '
                                          'las cantidades y los precios que ya tiene siguen como estaban. Revísalos. '
                                          'Para convertirlos, edita el insumo desde la ficha del APU e indica el factor.')
        return redirect('apu_catalogo:insumos')
    return render(request, 'apu_catalogo/insumo_form.html', {'form': form, 'insumo': insumo})


@acceso_apu('apu.catalogo.manage')
@require_POST
def insumo_eliminar(request, pk):
    insumo = get_object_or_404(Insumo, pk=pk, empresa=request.empresa)
    nombre = insumo.descripcion
    try:
        insumo.delete()
    except ProtectedError:
        messages.error(request, f'No se puede eliminar «{nombre}»: lo usan APU existentes. '
                                'Puedes desactivarlo desde «Editar».')
    else:
        messages.success(request, f'Se eliminó el insumo «{nombre}».')
    return redirect('apu_catalogo:insumos')



@acceso_apu('apu.catalogo.manage')
@require_POST
def insumos_eliminar_varios(request):
    """Eliminación en bloque: SOLO el superusuario. Recibe `ids` (los marcados) o `todos=1` (todos los que cumplen los filtros
    de la lista: q, tipo, sin_precio). Un insumo que usa algún APU no se puede borrar (protegido): se salta y se informa."""
    if not request.user.is_superuser:
        raise PermissionDenied
    empresa = request.empresa
    filtros = {'q': request.POST.get('q', '').strip(), 'tipo': request.POST.get('tipo', ''), 'solo_sin_precio': request.POST.get('sin_precio') == '1'}
    if request.POST.get('todos') == '1':
        qs = _insumos_filtrados(empresa, **filtros)
    else:
        ids = [int(i) for i in request.POST.getlist('ids') if i.isdigit()]
        if not ids:
            messages.warning(request, 'No marcaste ningún insumo para eliminar.')
            return redirect(_volver_a_insumos(filtros))
        qs = Insumo.objects.filter(empresa=empresa, pk__in=ids)
    eliminados = protegidos = 0
    for insumo in list(qs.distinct()):
        try:
            with transaction.atomic():
                insumo.delete()
        except ProtectedError:
            protegidos += 1
        else:
            eliminados += 1
    if eliminados:
        messages.success(request, f'Se eliminaron {eliminados} insumo(s).')
    if protegidos:
        messages.warning(request, f'{protegidos} insumo(s) no se eliminaron porque los usan APU existentes. Puedes desactivarlos desde «Editar».')
    if not eliminados and not protegidos:
        messages.info(request, 'No había insumos que eliminar con esa selección.')
    return redirect(_volver_a_insumos(filtros))


def _volver_a_insumos(filtros):
    params = {k: v for k, v in (('q', filtros['q']), ('tipo', filtros['tipo']), ('sin_precio', '1' if filtros['solo_sin_precio'] else '')) if v}
    base = reverse('apu_catalogo:insumos')
    return f'{base}?{urlencode(params)}' if params else base


# ── Categorías de APU ─────────────────────────────────────────────────────────

@acceso_apu('apu.ver')
def categorias(request):
    empresa = request.empresa
    lista = list(CategoriaAPU.objects.filter(empresa=empresa).annotate(n_apu=Count('items')))
    return render(request, 'apu_catalogo/categorias.html', {
        'categorias': lista, 'puede_editar': tiene_capacidad(request.user, 'apu.catalogo.manage', empresa),
        'sin_categoria': ItemModelo.objects.filter(empresa=empresa, categoria__isnull=True).count()})


def _categoria_propia(request, pk):
    return get_object_or_404(CategoriaAPU, pk=pk, empresa=request.empresa)


@acceso_apu('apu.catalogo.manage')
@require_POST
def categoria_nueva(request):
    try:
        c = cats.crear(request.empresa, request.POST.get('nombre'))
        messages.success(request, f'Se creó la categoría «{c.nombre}».')
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('apu_catalogo:categorias')


@acceso_apu('apu.catalogo.manage')
@require_POST
def categoria_renombrar(request, pk):
    c = _categoria_propia(request, pk)
    try:
        anterior = c.nombre
        cats.renombrar(c, request.POST.get('nombre'))
        messages.success(request, f'«{anterior}» ahora se llama «{c.nombre}».')
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('apu_catalogo:categorias')


@acceso_apu('apu.catalogo.manage')
@require_POST
def categoria_mover(request, pk):
    c = _categoria_propia(request, pk)
    cats.reordenar(request.empresa, c.pk, -1 if request.POST.get('sentido') == 'subir' else 1)
    return redirect('apu_catalogo:categorias')


@acceso_apu('apu.catalogo.manage')
@require_POST
def categoria_fusionar(request, pk):
    origen = _categoria_propia(request, pk)
    destino = CategoriaAPU.objects.filter(empresa=request.empresa, pk=request.POST.get('destino') or 0).first()
    if destino is None:
        messages.error(request, 'Elige la categoría a la que se moverán los APU.')
        return redirect('apu_catalogo:categorias')
    try:
        nombre = origen.nombre
        n = cats.fusionar(origen, destino)
        messages.success(request, f'«{nombre}» se fusionó en «{destino.nombre}» ({n} APU movidos).')
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('apu_catalogo:categorias')


@acceso_apu('apu.catalogo.manage')
@require_POST
def categoria_eliminar(request, pk):
    c = _categoria_propia(request, pk)
    nombre, n = c.nombre, c.items.count()
    c.delete()   # los APU quedan «Sin categoría»
    messages.success(request, f'Se eliminó la categoría «{nombre}»' + (f'; {n} APU quedaron sin categoría.' if n else '.'))
    return redirect('apu_catalogo:categorias')


@acceso_apu('apu.catalogo.manage')
@require_POST
def cantidades_guardar(request, pk):
    """Guarda las cantidades (metrados) de los APU de un proyecto: campos `metrado_<pk del APU>`; vacío = sin cantidad."""
    proyecto = get_object_or_404(Proyecto.objects.de_empresa(request.empresa), pk=pk)
    items = list(ItemModelo.objects.filter(empresa=request.empresa, proyecto=proyecto))
    nuevos, errores = {}, []
    for it in items:
        crudo = request.POST.get(f'metrado_{it.pk}')
        if crudo is None:
            continue                      # el campo no vino en el formulario: no se toca
        crudo = crudo.strip().replace(' ', '').replace(',', '.')
        if not crudo:
            nuevos[it.pk] = None
            continue
        try:
            valor = Decimal(crudo)
        except InvalidOperation:
            errores.append(f'«{crudo}» no es una cantidad válida ({it.codigo}).')
            continue
        if not valor.is_finite() or valor < 0 or valor >= Decimal('1e12'):
            errores.append(f'La cantidad de {it.codigo} debe estar entre 0 y 999 999 999 999.')
            continue
        nuevos[it.pk] = valor.quantize(Decimal('0.0001'))
    if errores:
        messages.error(request, errores[0] + (f' (y {len(errores) - 1} más)' if len(errores) > 1 else '') + ' No se guardó nada.')
    else:
        cambiados = 0
        for it in items:
            if it.pk in nuevos and it.metrado != nuevos[it.pk]:
                ItemModelo.objects.filter(pk=it.pk).update(metrado=nuevos[it.pk])
                cambiados += 1
        messages.success(request, f'Cantidades guardadas ({cambiados} APU actualizados).' if cambiados else 'No había cambios en las cantidades.')
    return redirect('apu_catalogo:proyecto_detalle', pk=proyecto.pk)
