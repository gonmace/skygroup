from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from empresas.acceso import acceso_modulo

from apu_motor import PerfilInvalido, validar_perfil

from . import editor
from .forms import MODOS, PerfilDatosForm
from .models import Insumo, ItemModelo, PerfilCalculo


@acceso_modulo('apu', 'apu.ver')
def inicio(request):
    empresa = request.empresa
    perfiles = PerfilCalculo.objects.filter(Q(empresa=empresa) | Q(empresa__isnull=True), activo=True)
    return render(request, 'apu_catalogo/inicio.html', {
        'resumen': [('tag', 'Insumos', Insumo.objects.filter(empresa=empresa).count()),
                    ('list', 'Ítems del catálogo', ItemModelo.objects.filter(empresa=empresa).count()),
                    ('settings', 'Perfiles de cálculo', len(perfiles))],
        'perfiles': perfiles,
        'puede_perfiles': tiene_capacidad(request.user, 'apu.perfiles.manage', empresa),
    })


@acceso_modulo('apu', 'apu.ver')
def perfil_detalle(request, pk):
    """Estructura de un perfil (de la empresa o plantilla de la plataforma): sus líneas y el redondeo."""
    perfil = PerfilCalculo.objects.filter(Q(empresa=request.empresa) | Q(empresa__isnull=True), pk=pk).first()
    if perfil is None:
        raise Http404
    return render(request, 'apu_catalogo/perfil.html', {
        'perfil': perfil, 'filas': perfil.filas(), 'redondeo': perfil.validado()['redondeo'],
        'puede_perfiles': tiene_capacidad(request.user, 'apu.perfiles.manage', request.empresa),
    })


@acceso_modulo('apu', 'apu.perfiles.manage')
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


@acceso_modulo('apu', 'apu.perfiles.manage')
def perfil_nuevo(request):
    return _editor(request, None)


@acceso_modulo('apu', 'apu.perfiles.manage')
def perfil_editar(request, pk):
    return _editor(request, _perfil_propio(request, pk))


@acceso_modulo('apu', 'apu.perfiles.manage')
@require_POST
def perfil_eliminar(request, pk):
    perfil = _perfil_propio(request, pk)
    nombre = perfil.nombre
    perfil.delete()
    messages.success(request, f'Se eliminó el perfil «{nombre}».')
    return redirect('apu_catalogo:inicio')
