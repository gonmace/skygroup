"""APU → Plantillas (solo superusuario): los tipos de trabajo con que se genera un APU y, de cada uno, el prompt y el modelo de
cada paso de la IA. Cada guardado crea una versión nueva y se puede volver a una anterior. n8n solo ejecuta lo que aquí se
define (ver `ia.config`)."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
import json
import time

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apu_catalogo import categorias as cats
from apu_catalogo.acceso import acceso_apu
from apu_catalogo.models import PlantillaAPU, PromptAPU
from core.n8n import N8NError
from proyectos.models import Proyecto

from . import asistente, ia
from .models import TarifaModeloIA

# Lo que recibe la IA junto con el prompt (el texto del usuario del agente en n8n), por paso: informativo.
RECIBE = {
    'coherencia': 'Proyecto, actividad, unidad, detalles, región y las categorías de APU de la empresa.',
    'clasificacion': 'Actividad, unidad, detalles y proyecto.',
    'materiales': 'Actividad, unidad, detalles, proyecto, clasificación, lo ya confirmado, catálogo de la empresa, APU del catálogo '
                  '(posibles sub-análisis), decisiones anteriores, aclaraciones, historial de preguntas y si es la última ronda.',
    'mano_obra': 'Lo mismo que materiales, más las referencias de mano de obra de APU parecidos ya guardados (sin sub-análisis).',
    'equipos': 'Lo mismo que materiales, sin sub-análisis ni referencias de mano de obra.',
    'verificar': 'Actividad, tipo de insumo y las filas que propuso el paso anterior.',
    'modificar': 'La instrucción de la persona, la actividad, el proyecto, la composición actual del APU y el catálogo.',
    'verificar_titulo': 'Título y unidad originales, la instrucción y el resumen de los cambios propuestos.',
    'precios': 'Moneda, región, proyecto y los insumos sin precio (descripción, unidad y tipo).',
}


def _solo_super(request):
    if not request.user.is_superuser:
        raise PermissionDenied


def _modelos(actual=''):
    """Modelos que se pueden elegir: los que tienen tarifa (así el consumo se puede costear) y, si el prompt ya usa otro, ese."""
    lista = [(t.modelo, f'{t.modelo} · ${t.entrada_usd_mtok:g} / ${t.salida_usd_mtok:g} por M tokens') for t in TarifaModeloIA.objects.all()]
    if actual and actual not in {m for m, _ in lista}:
        lista.append((actual, f'{actual} · sin tarifa'))
    return lista


@acceso_apu('apu.ver')
def plantillas(request):
    _solo_super(request)
    filas = []
    for t in PlantillaAPU.objects.all():
        faltan = t.pasos_faltantes()
        filas.append({'t': t, 'pasos': t.prompts.filter(vigente=True).count(), 'faltan': faltan, 'apus': t.items.count()})
    return render(request, 'apu_generador/plantillas.html', {'filas': filas, 'total_pasos': len(PromptAPU.Paso.choices),
                                                           'copiables': PlantillaAPU.objects.all()})


@acceso_apu('apu.ver')
@require_POST
def plantilla_nueva(request):
    """Crea una plantilla vacía o, si se elige «copiar de», con los prompts vigentes de esa."""
    _solo_super(request)
    nombre = (request.POST.get('nombre') or '').strip()[:80]
    if not nombre:
        messages.error(request, 'Escribe el nombre de la plantilla.')
        return redirect('apu_generador:plantillas')
    origen = PlantillaAPU.objects.filter(pk=request.POST.get('copiar_de') or 0).first()
    try:
        with transaction.atomic():
            if origen:
                plantilla = origen.duplicar(nombre, request.user)
            else:
                plantilla = PlantillaAPU.objects.create(nombre=nombre, orden=PlantillaAPU.objects.count() + 1)
    except IntegrityError:
        messages.error(request, f'Ya existe una plantilla llamada «{nombre}».')
        return redirect('apu_generador:plantillas')
    messages.success(request, f'Plantilla «{plantilla.nombre}» creada.' + (f' Parte de una copia de «{origen.nombre}»: ajusta sus prompts.' if origen else ' Aún no tiene prompts: copia los de otra o cárgalos paso a paso.'))
    return redirect('apu_generador:plantilla', plantilla.pk)


@acceso_apu('apu.ver')
def plantilla(request, pk):
    _solo_super(request)
    plantilla = get_object_or_404(PlantillaAPU, pk=pk)
    pasos = list(PromptAPU.Paso.choices)
    paso = request.GET.get('paso') or pasos[0][0]
    if paso not in dict(pasos):
        paso = pasos[0][0]
    vigentes = {p.paso: p for p in plantilla.prompts.filter(vigente=True)}
    vigente = vigentes.get(paso)
    # Una versión anterior que se está mirando (no cambia nada hasta restaurarla).
    ver = plantilla.prompts.filter(paso=paso, version=request.GET.get('version') or 0).first()
    mostrado = ver or vigente
    historial = list(plantilla.prompts.filter(paso=paso).select_related('editado_por').order_by('-version'))
    return render(request, 'apu_generador/plantilla.html', {
        'plantilla': plantilla, 'paso': paso, 'paso_nombre': dict(pasos)[paso], 'vigente': vigente, 'mostrado': mostrado,
        'viendo_antigua': bool(ver and ver != vigente),
        'tabs': [(clave, nombre, clave in vigentes) for clave, nombre in pasos], 'historial': historial,
        'modelos': _modelos(mostrado.modelo if mostrado else ''), 'razonamientos': PromptAPU.Razonamiento.choices,
        'recibe': RECIBE.get(paso, ''), 'faltan': plantilla.pasos_faltantes(), 'se_prueba': paso in PRUEBA,
        'proyectos': Proyecto.objects.filter(empresa=request.empresa).order_by('nombre')})


@acceso_apu('apu.ver')
@require_POST
def plantilla_datos(request, pk):
    """Nombre, descripción, unidades habituales y si está activa."""
    _solo_super(request)
    plantilla = get_object_or_404(PlantillaAPU, pk=pk)
    nombre = (request.POST.get('nombre') or '').strip()[:80]
    if not nombre:
        messages.error(request, 'La plantilla necesita un nombre.')
        return redirect('apu_generador:plantilla', pk)
    plantilla.nombre = nombre
    plantilla.descripcion = (request.POST.get('descripcion') or '').strip()
    plantilla.unidades_sugeridas = (request.POST.get('unidades_sugeridas') or '').strip()[:200]
    plantilla.activo = request.POST.get('activo') == '1'
    try:
        with transaction.atomic():
            plantilla.save()
    except IntegrityError:
        messages.error(request, f'Ya existe una plantilla llamada «{nombre}».')
        return redirect('apu_generador:plantilla', pk)
    messages.success(request, 'Datos de la plantilla guardados.')
    return redirect('apu_generador:plantilla', pk)


def _casillas(post):
    return {c: (post.get(c) or '').strip() for c in PromptAPU.CASILLAS}


@acceso_apu('apu.ver')
@require_POST
def prompt_guardar(request, pk, paso):
    """Guarda lo editado como una versión nueva y vigente del prompt (si hay algo que cambió)."""
    _solo_super(request)
    plantilla = get_object_or_404(PlantillaAPU, pk=pk)
    if paso not in dict(PromptAPU.Paso.choices):
        raise PermissionDenied
    vuelta = reverse('apu_generador:plantilla', args=[pk]) + f'?paso={paso}'
    datos = {**_casillas(request.POST), 'modelo': (request.POST.get('modelo') or '').strip()[:80],
             'razonamiento': (request.POST.get('razonamiento') or '').strip()}
    if datos['razonamiento'] not in {v for v, _ in PromptAPU.Razonamiento.choices}:
        messages.error(request, 'Elige un nivel de razonamiento válido.')
        return redirect(vuelta)
    if not datos['rol'] and not datos['criterios'] and not datos['reglas']:
        messages.error(request, 'El prompt no puede quedar vacío.')
        return redirect(vuelta)
    if not datos['modelo']:
        messages.error(request, 'Elige el modelo con que se ejecuta este paso.')
        return redirect(vuelta)
    actual = plantilla.prompt(paso)
    comentario = (request.POST.get('comentario') or '').strip()
    if actual is None:
        PromptAPU.objects.create(plantilla=plantilla, paso=paso, version=1, vigente=True, editado_por=request.user,
                                 comentario=comentario[:200], **datos)
    elif all(getattr(actual, k) == v for k, v in datos.items()):
        messages.info(request, 'No hay cambios que guardar.')
        return redirect(vuelta)
    else:
        actual.nueva_version(request.user, comentario, **datos)
    messages.success(request, 'Guardado como versión nueva. Desde ahora la usan los APU nuevos.')
    return redirect(vuelta)


@acceso_apu('apu.ver')
@require_POST
def prompt_restaurar(request, pk, version_pk):
    """Vuelve a una versión anterior: se guarda como una versión nueva (el historial no se reescribe)."""
    _solo_super(request)
    antigua = get_object_or_404(PromptAPU.objects.select_related('plantilla'), pk=version_pk, plantilla_id=pk)
    vigente = antigua.plantilla.prompt(antigua.paso)
    if vigente and vigente.pk == antigua.pk:
        messages.info(request, 'Esa ya es la versión vigente.')
    else:
        (vigente or antigua).nueva_version(request.user, f'Restaurada la versión {antigua.version}',
                                           **{c: getattr(antigua, c) for c in (*PromptAPU.CASILLAS, 'modelo', 'razonamiento')})
        messages.success(request, f'Se restauró la versión {antigua.version} como versión nueva.')
    return redirect(reverse('apu_generador:plantilla', args=[pk]) + f'?paso={antigua.paso}')


# ── Banco de pruebas: correr un paso con lo que hay en el formulario, sin guardar ─────────────────────────────────────

# Qué webhook ejecuta cada paso y qué otros prompts necesita junto con él (se usan los vigentes de la plantilla).
PRUEBA = {
    'coherencia': ('coherencia', ('coherencia', 'clasificacion')),
    'clasificacion': ('coherencia', ('coherencia', 'clasificacion')),
    'materiales': ('insumos', ('materiales', 'verificar')),
    'mano_obra': ('insumos', ('mano_obra', 'verificar')),
    'equipos': ('insumos', ('equipos', 'verificar')),
    'verificar': ('insumos', ('materiales', 'verificar')),
}


def _json(ok, message='', status=200, **extra):
    return JsonResponse({'success': ok, 'message': message, **extra}, status=status)


@acceso_apu('apu.ver')
@require_POST
def prompt_probar(request, pk, paso):
    """Corre el paso con el texto y el modelo del formulario (sin guardarlos) y devuelve lo que respondió la IA. No guarda
    insumos ni cobra créditos; la llamada queda en Consumo IA con sus tokens."""
    _solo_super(request)
    plantilla = get_object_or_404(PlantillaAPU, pk=pk)
    if paso not in PRUEBA:
        return _json(False, 'Este paso solo se puede probar desde un APU real (necesita su composición).', 400)
    try:
        d = json.loads(request.body or b'{}')
    except ValueError:
        d = {}
    actividad, unidad = str(d.get('actividad') or '').strip(), str(d.get('unidad') or '').strip()
    detalles = str(d.get('descripcion') or '').strip()
    proyecto = Proyecto.objects.filter(empresa=request.empresa, pk=d.get('proyecto') or 0).first()
    if not (actividad and unidad and detalles) or proyecto is None:
        return _json(False, 'Para probar, elige un proyecto e indica la actividad, su unidad y los detalles.', 400)
    modelo = str(d.get('modelo') or '').strip()
    if not modelo:
        return _json(False, 'Elige el modelo con que quieres probar.', 400)
    probando = PromptAPU(plantilla=plantilla, paso=paso, modelo=modelo[:80],
                         razonamiento=str(d.get('razonamiento') or '').strip(), **_casillas(d))
    if not probando.texto:
        return _json(False, 'El prompt está vacío.', 400)

    webhook, pasos = PRUEBA[paso]
    config = {}
    otros = d.get('otros') if isinstance(d.get('otros'), dict) else {}
    for p in pasos:   # los pasos que acompañan: su borrador sin guardar si lo hay; si no, su prompt vigente
        if p == paso:
            continue
        borrador = otros.get(p)
        if isinstance(borrador, dict):
            ensayo = PromptAPU(plantilla=plantilla, paso=p, modelo=str(borrador.get('modelo') or '')[:80],
                               razonamiento=str(borrador.get('razonamiento') or '').strip(), **_casillas(borrador))
            if ensayo.texto and ensayo.modelo:
                config[p] = {'prompt': ensayo.texto, 'modelo': ensayo.modelo, 'razonamiento': ensayo.razonamiento,
                             'version': f'PRUEBA · {plantilla.nombre} · {ensayo.get_paso_display()} · {ensayo.modelo}'[:120]}
                continue
        try:
            config.update(ia.config(plantilla, p))
        except N8NError as e:
            return _json(False, str(e), 400)
    config[paso] = {'prompt': probando.texto, 'modelo': probando.modelo, 'razonamiento': probando.razonamiento,
                    'version': f'PRUEBA · {plantilla.nombre} · {probando.get_paso_display()} · {probando.modelo}'[:120]}
    base_texto = f'{actividad} {detalles}'
    contexto = ia.contexto_proyecto(proyecto)
    if webhook == 'coherencia':
        payload = {'actividad': actividad, 'unidad': unidad, 'descripcion': detalles, 'region': '', 'proyecto': contexto,
                   'categorias': cats.para_ia(request.empresa), 'historial': [],
                   'ultima_ronda': bool(d.get('sin_preguntas', True))}
    else:
        tipo = 'materiales' if paso == 'verificar' else paso
        payload = {
            'tipo': tipo, 'actividad': actividad, 'unidad': unidad, 'region': '',
            # como en el generador, los pasos de insumos solo reciben el alcance; sin uno escrito se arma uno provisional
            'resumen_alcance': (str(d.get('resumen_alcance') or '').strip() or
                                f"Proyecto «{contexto['nombre']}» ({contexto['tipo']}, {contexto['ciudad']}): {contexto['descripcion']}\n{detalles}".strip())[:2000],
            'clasificacion': {}, 'confirmado': {}, 'catalogo': asistente.catalogo_para_ia(request.empresa, tipo, base_texto),
            'catalogo_items': asistente.catalogo_items_para_ia(request.empresa, None, base_texto) if tipo == 'materiales' else [],
            'referencias_mano_obra': (asistente.referencias_mano_obra(request.empresa, actividad, unidad, detalles, excluir_pk=None)
                                      if tipo == 'mano_obra' else []),
            'decisiones_previas': [], 'aclaraciones': [], 'historial': [], 'ultima_ronda': bool(d.get('sin_preguntas', True))}
    payload['ia'] = config
    inicio = time.monotonic()
    try:
        respuesta = ia.llamar(webhook, payload, empresa=request.empresa, usuario=request.user, paso=f'prueba:{paso}'[:20])
    except N8NError as e:
        return _json(False, str(e), 502)
    return _json(True, 'Listo.', respuesta=respuesta, segundos=round(time.monotonic() - inicio, 1), modelo=probando.modelo,
                 razonamiento=probando.razonamiento, ejecucion_id=respuesta.get('ejecucion_id', ''))
