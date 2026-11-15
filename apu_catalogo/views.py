from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from proyectos.models import Proyecto

from apu_motor import PerfilInvalido, validar_perfil

from . import editor
from .acceso import acceso_apu
from .forms import MODOS, PerfilDatosForm
from . import calculo
from .models import Insumo, ItemModelo, PerfilCalculo, PrecioInsumo, ProyectoAPU, Tipo


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

def _precio_de(item):
    """Precio unitario con el perfil efectivo del proyecto, o None si el proyecto aún no tiene incidencias."""
    try:
        return calculo.analizar(item).total
    except Exception:  # un perfil o dato roto no debe tumbar la lista
        return None


@acceso_apu('apu.ver')
def items(request):
    empresa = request.empresa
    q = request.GET.get('q', '').strip()
    proyecto = request.GET.get('proyecto', '')
    categoria = request.GET.get('categoria', '')
    qs = ItemModelo.objects.filter(empresa=empresa).select_related('proyecto')
    if q:
        qs = qs.filter(Q(codigo__icontains=q) | Q(descripcion__icontains=q))
    if proyecto.isdigit():
        qs = qs.filter(proyecto_id=proyecto)
    if categoria:
        qs = qs.filter(categoria=categoria)
    pagina = Paginator(qs.order_by('proyecto__nombre', 'codigo'), 25).get_page(request.GET.get('page'))
    for it in pagina:
        it.precio_unitario = _precio_de(it)
        pa = ProyectoAPU.objects.filter(proyecto_id=it.proyecto_id).select_related('perfil').first() if it.proyecto_id else None
        it.moneda = pa.perfil.moneda if pa else ''
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'apu_catalogo/items.html', {
        'pagina': pagina, 'q': q, 'proyecto_sel': proyecto, 'categoria_sel': categoria, 'qs_filtros': params.urlencode(),
        'proyectos': Proyecto.objects.de_empresa(empresa).activos().filter(apu_items__isnull=False).distinct().order_by('nombre'),
        'categorias': ItemModelo.objects.filter(empresa=empresa).exclude(categoria='').values_list('categoria', flat=True).distinct().order_by('categoria'),
        'puede_generar': tiene_capacidad(request.user, 'apu.catalogo.manage', empresa)})


@acceso_apu('apu.ver')
def item_detalle(request, pk):
    from apu_generador import ia as ia_gen
    from apu_generador.models import LlamadaIA
    empresa = request.empresa
    item = get_object_or_404(ItemModelo.objects.select_related('proyecto', 'origen', 'creado_por'), pk=pk, empresa=empresa)
    pa = ProyectoAPU.objects.filter(proyecto_id=item.proyecto_id).select_related('perfil').first() if item.proyecto_id else None
    region = request.GET.get('region', '').strip()
    analisis = calculo.analizar(item, region=region)
    consumo = None
    if request.user.is_superuser:
        llamadas = LlamadaIA.objects.filter(Q(apu=item) | Q(borrador__apu_guardado=item))
        ia_gen.sincronizar_uso(list(llamadas.filter(uso__isnull=True).exclude(ejecucion_id='')[:20]))
        consumo = ia_gen.resumen_uso(llamadas)
    return render(request, 'apu_catalogo/item.html', {
        'item': item, 'analisis': analisis, 'desglose': calculo.desglose(analisis.perfil, analisis.resultado),
        'proyecto_apu': pa, 'region': region, 'consumo': consumo,
        'puede_generar': tiene_capacidad(request.user, 'apu.catalogo.manage', empresa),
        'puede_incidencias': tiene_capacidad(request.user, 'apu.perfiles.manage', empresa),
        'proyectos': Proyecto.objects.de_empresa(empresa).activos().order_by('nombre'),
        'perfiles': PerfilCalculo.propios(empresa), 'plantillas': PerfilCalculo.objects.filter(empresa__isnull=True, activo=True),
        'con_apu': set(ProyectoAPU.objects.filter(proyecto__empresa=empresa).values_list('proyecto_id', flat=True))})


@acceso_apu('apu.ver')
def proyectos(request):
    empresa = request.empresa
    lista = (Proyecto.objects.de_empresa(empresa).activos()
             .annotate(n_apu=Count('apu_items', distinct=True)).filter(Q(n_apu__gt=0) | Q(apu__isnull=False))
             .select_related('apu__perfil').order_by('nombre'))
    return render(request, 'apu_catalogo/proyectos.html', {
        'proyectos': lista, 'puede_incidencias': tiene_capacidad(request.user, 'apu.perfiles.manage', empresa)})


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
    if request.method == 'POST' and accion == 'guardar' and not errores:
        ProyectoAPU.objects.update_or_create(proyecto=proyecto, defaults={'perfil': perfil, 'ajustes': nuevos})
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
        'proyecto': proyecto, 'perfil': perfil, 'perfiles': perfiles, 'lineas': list(valores.values()), 'errores': errores,
        'ajustados': set(nuevos), 'vista_previa': vista_previa, 'huerfanos': huerfanos, 'n_apu': ItemModelo.objects.filter(proyecto=proyecto).count()})


@acceso_apu('apu.ver')
def insumos(request):
    empresa = request.empresa
    q = request.GET.get('q', '').strip()
    tipo = request.GET.get('tipo', '')
    qs = Insumo.objects.filter(empresa=empresa).prefetch_related(
        Prefetch('precios', queryset=PrecioInsumo.objects.filter(region='').order_by('-fecha'), to_attr='precios_nacionales'))
    if q:
        qs = qs.filter(Q(codigo__icontains=q) | Q(descripcion__icontains=q))
    if tipo in Tipo.values:
        qs = qs.filter(tipo=tipo)
    pagina = Paginator(qs.order_by('tipo', 'codigo'), 40).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'apu_catalogo/insumos.html', {
        'pagina': pagina, 'q': q, 'tipo_sel': tipo, 'tipos': Tipo.choices, 'qs_filtros': params.urlencode()})
