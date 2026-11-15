import json
from datetime import date

from django.contrib import messages
from django.db.models import Avg, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apu_catalogo import calculo
from apu_catalogo.acceso import acceso_apu, es_admin_o_super
from apu_catalogo.models import ItemModelo, PerfilCalculo, ProyectoAPU
from core.n8n import N8NError
from cuentas.capacidades import tiene_capacidad
from proyectos.models import Proyecto

from . import asistente, creditos, ia
from .asistente import Conflicto, ErrorPaso
from .models import APUBorrador, ConsumoAPU, LlamadaIA

DURACION_DEFECTO_MS = 40_000


def _json(ok, message='', status=200, **extra):
    return JsonResponse({'success': ok, 'message': message, **extra}, status=status)


def _datos(request):
    try:
        datos = json.loads(request.body or b'{}')
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _proyectos(empresa):
    return Proyecto.objects.de_empresa(empresa).activos().order_by('nombre')


def _habilitados(empresa):
    """Proyectos habilitados para APU (tienen su `ProyectoAPU`: perfil de cálculo e incidencias)."""
    return _proyectos(empresa).filter(apu__isnull=False)


def _puede_con(request, borrador):
    """Quien lo creó, el equipo del proyecto y los administradores."""
    user = request.user
    if borrador.creado_por_id == user.pk or es_admin_o_super(user, request.empresa):
        return True
    return borrador.proyecto.equipo.filter(user=user, activa=True).exists()


def _borrador(request, pk, editable=True):
    b = get_object_or_404(APUBorrador.objects.select_related('proyecto', 'apu_guardado'), pk=pk,
                          empresa=request.empresa, eliminado=False)
    if not _puede_con(request, b):
        raise Http404
    return b


def _url_paso(borrador):
    """Dónde está el borrador ahora: el paso en que quedó (no se puede volver atrás)."""
    if borrador.paso <= 1:
        return reverse('apu_generador:actividad', args=[borrador.pk])
    if borrador.paso >= 5:
        return reverse('apu_generador:resultado', args=[borrador.pk])
    return reverse('apu_generador:paso', args=[borrador.pk, asistente.SLUG_URL[asistente.TIPO_DE_PASO[borrador.paso]]])


def _promedio_ms(empresa, webhook):
    ms = (LlamadaIA.objects.filter(empresa=empresa, webhook=webhook, ok=True, duracion_ms__gt=0)
          .order_by('-fecha').values_list('duracion_ms', flat=True)[:20])
    ms = list(ms)
    return int(sum(ms) / len(ms)) if ms else DURACION_DEFECTO_MS


def _contexto_base(request, borrador=None):
    return {'borrador': borrador, 'creditos': creditos.resumen(request.user, request.empresa),
            'pasos': [(1, 'Actividad')] + [(n, nombre) for n, _, nombre in asistente.PASOS],
            'paso_actual': borrador.paso if borrador else 1}


# ── Paso 1: actividad ─────────────────────────────────────────────────────────

def _info_proyectos(empresa):
    info = {}
    pas = list(ProyectoAPU.objects.filter(proyecto__empresa=empresa).select_related('perfil'))
    perfiles, perfil_ids = {pa.proyecto_id: pa.perfil.nombre for pa in pas}, {pa.proyecto_id: pa.perfil_id for pa in pas}
    regiones = {pa.proyecto_id: pa.region for pa in pas}
    for p in _habilitados(empresa):
        info[p.pk] = {'perfil': perfiles.get(p.pk, ''), 'perfil_id': perfil_ids.get(p.pk, ''), 'region': regiones.get(p.pk, ''), 'descripcion_ok': asistente.descripcion_suficiente(p),
                      'descripcion': p.descripcion or ''}
    return info


def _correr_coherencia(request, borrador):
    """Llama a `apu-coherencia` y deja el borrador en el paso 2 si todo está claro y es coherente."""
    payload = {'actividad': borrador.actividad, 'unidad': borrador.unidad, 'descripcion': borrador.descripcion,
               'region': borrador.region, 'proyecto': ia.contexto_proyecto(borrador.proyecto)}
    base = {'borrador_id': borrador.pk, 'continuar_url': _url_paso(borrador)}
    try:
        datos = ia.llamar('coherencia', payload, empresa=request.empresa, usuario=request.user, borrador=borrador,
                          paso='coherencia')
    except N8NError as e:
        return _json(False, str(e), 502, **base)
    if datos.get('proyecto_claro') is False:
        falta = str(datos.get('falta') or 'Describe mejor qué se construye, dónde y para qué.')
        return _json(True, 'La descripción del proyecto no es suficiente para generar el APU.', estado='proyecto_poco_claro',
                     falta=falta, **base)
    if datos.get('coherente') is False:
        razon = str(datos.get('razon') or 'La actividad no es coherente con la descripción.')
        return _json(True, razon, estado='no_coherente', razon=razon, **base)
    if datos.get('coherente') is not True:
        return _json(False, 'El servicio de IA devolvió una respuesta inválida. Inténtalo de nuevo.', 502, **base)
    claves = ('sistema_constructivo', 'tipo_elemento', 'material_principal', 'proceso_principal', 'categoria')
    borrador.clasificacion = {k: str(datos.get(k) or '')[:200] for k in claves}
    borrador.paso = 2
    borrador.save(update_fields=['clasificacion', 'paso', 'actualizado'])
    base['continuar_url'] = _url_paso(borrador)
    return _json(True, 'La actividad es coherente. Continuamos con los materiales.', estado='ok', **base)


def _validar_actividad(datos):
    actividad, unidad = str(datos.get('actividad') or '').strip(), str(datos.get('unidad') or '').strip()
    if not actividad or not unidad:
        raise ErrorPaso('Indica la actividad y su unidad.')
    if len(actividad) > 200:
        raise ErrorPaso('La actividad no puede superar los 200 caracteres.')
    return {'actividad': actividad, 'unidad': unidad[:20], 'descripcion': str(datos.get('descripcion') or '').strip()}


def _completar_proyecto(request, proyecto, datos):
    """La descripción del proyecto debe ser suficiente: si no lo es, se pide aquí y se guarda en el proyecto."""
    if not asistente.descripcion_suficiente(proyecto):
        proyecto.descripcion = str(datos.get('proyecto_descripcion') or '').strip()
        if not asistente.descripcion_suficiente(proyecto):
            raise ErrorPaso(f'Describe brevemente el proyecto (al menos {asistente.MIN_PALABRAS_DESCRIPCION} palabras): '
                            'qué se construye, dónde y para qué. La IA la usa para ajustar cada APU.')
        proyecto.save(update_fields=['descripcion'])


def _sin_proyectos_habilitados(request):
    """Primer paso del módulo: antes de generar hay que habilitar un proyecto para APU."""
    if tiene_capacidad(request.user, 'apu.perfiles.manage', request.empresa):
        messages.info(request, 'Primero habilita un proyecto para APU: elige su perfil de cálculo y su descripción.')
        return redirect('apu_catalogo:habilitar')
    messages.warning(request, 'Todavía no hay proyectos habilitados para APU. Pide a un coordinador que habilite uno.')
    return redirect('apu_catalogo:inicio')


@acceso_apu('apu.catalogo.manage')
def nuevo(request):
    empresa = request.empresa
    if request.method == 'GET' and not _habilitados(empresa).exists():
        return _sin_proyectos_habilitados(request)
    if request.method == 'POST':
        datos = _datos(request)
        ok, motivo = creditos.puede_consumir(request.user, empresa)
        if not ok:
            return _json(False, motivo, 402)
        proyecto = _habilitados(empresa).filter(pk=datos.get('proyecto') or 0).first()
        if proyecto is None:
            return _json(False, 'Elige un proyecto habilitado para APU. Si no lo ves, habilítalo primero en APU → Proyectos.', 400)
        try:
            campos = _validar_actividad(datos)
            _completar_proyecto(request, proyecto, datos)
        except ErrorPaso as e:
            return _json(False, str(e), 400)
        borrador = APUBorrador.objects.create(empresa=empresa, proyecto=proyecto, creado_por=request.user, paso=1,
                                              region=proyecto.apu.region, **campos)
        return _correr_coherencia(request, borrador)
    inicial = {'proyecto': request.GET.get('proyecto', '')}
    return render(request, 'apu_generador/actividad.html', {
        **_contexto_base(request), 'proyectos': _habilitados(empresa), 'info_proyectos': _info_proyectos(empresa),
        'inicial': inicial, 'promedio_ms': _promedio_ms(empresa, 'apu-coherencia')})


@acceso_apu('apu.catalogo.manage')
def actividad(request, pk):
    """El paso 1 de un borrador pendiente (aún sin coherencia confirmada): corregir y volver a comprobar."""
    borrador = _borrador(request, pk)
    if borrador.paso > 1:
        return redirect(_url_paso(borrador))
    if request.method == 'POST':
        datos = _datos(request)
        try:
            campos = _validar_actividad(datos)
            _completar_proyecto(request, borrador.proyecto, datos)
        except ErrorPaso as e:
            return _json(False, str(e), 400)
        for k, v in campos.items():
            setattr(borrador, k, v)
        borrador.region = getattr(borrador.proyecto, 'apu', None) and borrador.proyecto.apu.region or ''
        borrador.save()
        return _correr_coherencia(request, borrador)
    empresa = request.empresa
    return render(request, 'apu_generador/actividad.html', {
        **_contexto_base(request, borrador), 'proyectos': [borrador.proyecto],
        'info_proyectos': _info_proyectos(empresa), 'inicial': {'proyecto': borrador.proyecto_id}, 'promedio_ms': _promedio_ms(empresa, 'apu-coherencia')})


# ── Pasos 2 a 4: propuesta de la IA y guardado ────────────────────────────────

def _tipo_o_404(slug):
    tipo = asistente.TIPO_DE_SLUG.get(slug)
    if tipo is None:
        raise Http404
    return tipo


def _estado_paso(borrador, tipo):
    """Propuesta guardada del paso (para retomar sin volver a llamar a la IA) y rondas usadas."""
    guardado = (borrador.consultas or {}).get(tipo, {})
    return {'propuesta': guardado.get('propuesta'), 'respuestas': guardado.get('respuestas') or {},
            'usadas': int((borrador.rondas or {}).get(tipo, 0))}


@acceso_apu('apu.catalogo.manage')
def paso(request, pk, slug):
    borrador = _borrador(request, pk)
    tipo = _tipo_o_404(slug)
    if borrador.paso != asistente.PASO_DE[tipo]:
        return redirect(_url_paso(borrador))
    catalogo = asistente.catalogo_para_ia(request.empresa, tipo)
    nombre = {n: t for n, k, t in asistente.PASOS}[asistente.PASO_DE[tipo]]
    return render(request, 'apu_generador/paso.html', {
        **_contexto_base(request, borrador), 'tipo': tipo, 'slug': slug, 'nombre_paso': nombre,
        'estado': _estado_paso(borrador, tipo), 'catalogo': catalogo, 'max_repeticiones': asistente.MAX_REPETICIONES,
        'mano_obra': borrador.mano_obra if tipo == 'mano_obra' else None,
        'promedio_ms': _promedio_ms(request.empresa, 'apu-insumos')})


@acceso_apu('apu.catalogo.manage')
@require_POST
def proponer(request, pk, slug):
    """Llama a `apu-insumos`. No guarda lo confirmado: solo deja a mano la propuesta para poder retomarla."""
    borrador = _borrador(request, pk)
    tipo = _tipo_o_404(slug)
    if borrador.paso != asistente.PASO_DE[tipo]:
        return _json(False, 'Este paso ya está cerrado.', 409, continuar_url=_url_paso(borrador))
    datos = _datos(request)
    guardado = (borrador.consultas or {}).get(tipo, {})
    usadas = int((borrador.rondas or {}).get(tipo, 0))
    if usadas > asistente.MAX_REPETICIONES:
        return _json(False, 'Ya usaste todas las propuestas de este paso. Revisa la última y continúa.', 429)
    respuestas = {str(k): str(v).strip() for k, v in (datos.get('respuestas') or {}).items() if str(v).strip()}
    historial = list(guardado.get('historial') or [])
    propuesta_previa = guardado.get('propuesta') or {}
    for c in propuesta_previa.get('consultas', []):
        if c['id'] in respuestas:
            historial.append({'pregunta': c['pregunta'], 'respuesta': respuestas[c['id']]})
    confirmado = {t: [{'descripcion': f['descripcion'], 'unidad': f['unidad'], 'cantidad': f.get('cantidad') or f.get('personas')}
                      for f in borrador.filas(t)] for t in ia.TIPOS_INSUMO if t != tipo and borrador.filas(t)}
    payload = {
        'tipo': tipo, 'actividad': borrador.actividad, 'unidad': borrador.unidad, 'descripcion': borrador.descripcion,
        'region': borrador.region, 'proyecto': ia.contexto_proyecto(borrador.proyecto),
        'clasificacion': borrador.clasificacion, 'confirmado': confirmado,
        'catalogo': asistente.catalogo_para_ia(request.empresa, tipo, f'{borrador.actividad} {borrador.descripcion}'),
        'catalogo_items': asistente.catalogo_items_para_ia(request.empresa, borrador.apu_guardado_id),
        'decisiones_previas': asistente.decisiones_previas(request.empresa, borrador.pk),
        'aclaraciones': asistente.aclaraciones(borrador, tipo),
        'respuestas': [{'pregunta': h['pregunta'], 'respuesta': h['respuesta']} for h in historial],
        'historial': historial, 'ultima_ronda': usadas >= asistente.MAX_REPETICIONES,
    }
    try:
        crudo = ia.llamar('insumos', payload, empresa=request.empresa, usuario=request.user, borrador=borrador, paso=tipo)
    except N8NError as e:
        return _json(False, str(e), 502)
    propuesta = ia.normalizar_propuesta(crudo, tipo)
    if not propuesta['filas'] and not propuesta['consultas'] and not any(o['filas'] for c in propuesta['consultas'] for o in c['opciones']):
        return _json(False, 'La IA no propuso nada para este paso. Inténtalo de nuevo o agrega las filas a mano.', 502)
    borrador.consultas = {**(borrador.consultas or {}),
                          tipo: {**guardado, 'propuesta': propuesta, 'respuestas': respuestas, 'historial': historial}}
    borrador.rondas = {**(borrador.rondas or {}), tipo: usadas + 1}
    borrador.save(update_fields=['consultas', 'rondas', 'actualizado'])
    return _json(True, 'Propuesta lista.', propuesta=propuesta, usadas=usadas + 1,
                 restantes=max(0, asistente.MAX_REPETICIONES + 1 - (usadas + 1)))


@acceso_apu('apu.catalogo.manage')
@require_POST
def guardar(request, pk, slug):
    borrador = _borrador(request, pk)
    tipo = _tipo_o_404(slug)
    if borrador.paso != asistente.PASO_DE[tipo]:
        return _json(False, 'Este paso ya está cerrado.', 409, continuar_url=_url_paso(borrador))
    try:
        asistente.guardar_paso(borrador, tipo, _datos(request))
    except ErrorPaso as e:
        return _json(False, str(e), 400)
    return _json(True, 'Paso guardado.', continuar_url=_url_paso(borrador))


# ── Paso 5: precios, resultado y guardado ─────────────────────────────────────

@acceso_apu('apu.catalogo.manage')
def resultado(request, pk):
    borrador = _borrador(request, pk)
    if borrador.paso < 5:
        return redirect(_url_paso(borrador))
    if borrador.guardado:
        return redirect('apu_catalogo:item_detalle', pk=borrador.apu_guardado_id)
    prev = asistente.previsualizar(borrador)
    pa = ProyectoAPU.objects.filter(proyecto=borrador.proyecto).first()
    return render(request, 'apu_generador/resultado.html', {
        **_contexto_base(request, borrador), 'prev': prev, 'desglose': calculo.desglose(prev['perfil'], prev['resultado']),
        'proyecto_apu': pa, 'hoy': date.today().isoformat(),
        'puede_incidencias': tiene_capacidad(request.user, 'apu.perfiles.manage', request.empresa),
        'ultima_modificacion': next((i for i in reversed(borrador.instrucciones or []) if not i.get('aplicada')), None)})


MAX_SUGERENCIAS = 3          # veces que se puede pedir sugerencias de precio por borrador
MAX_INSUMOS_SUGERENCIA = 40


@acceso_apu('apu.catalogo.manage')
@require_POST
def sugerir_precios(request, pk):
    """Pide a la IA (`apu-precios`) precios ESTIMADOS de los insumos sin precio. Son una recomendación: no se guarda nada;
    la persona decide si los usa. No cobra créditos (queda registrada la llamada y sus tokens)."""
    borrador = _borrador(request, pk)
    if borrador.paso < 5:
        return _json(False, 'Termina los pasos anteriores primero.', 409, continuar_url=_url_paso(borrador))
    usadas = int((borrador.rondas or {}).get('precios', 0))
    if usadas >= MAX_SUGERENCIAS and not request.user.is_superuser:   # el superusuario no tiene tope
        return _json(False, 'Ya pediste sugerencias de precio varias veces para este APU. Carga los que faltan a mano.', 429)
    prev = asistente.previsualizar(borrador)
    faltan = prev['sin_precio'][:MAX_INSUMOS_SUGERENCIA]
    if not faltan:
        return _json(False, 'Todos los insumos de este APU ya tienen precio.', 400)
    pa = ProyectoAPU.objects.filter(proyecto=borrador.proyecto).select_related('perfil').first()
    moneda = pa.perfil.moneda if pa else ''
    payload = {'moneda': moneda, 'region': borrador.region or borrador.proyecto.ciudad or borrador.proyecto.region or '',
               'fecha': date.today().isoformat(), 'proyecto': ia.contexto_proyecto(borrador.proyecto),
               'insumos': [{'id': i.pk, 'descripcion': i.descripcion, 'unidad': i.unidad, 'tipo': i.tipo} for i in faltan]}
    try:
        crudo = ia.llamar('precios', payload, empresa=request.empresa, usuario=request.user, borrador=borrador, paso='precios')
    except N8NError as e:
        return _json(False, str(e), 502)
    sugerencias = ia.normalizar_precios(crudo, {i.pk for i in faltan}, moneda)
    if not sugerencias:
        return _json(False, 'La IA no pudo estimar esos precios. Cárgalos a mano.', 502)
    borrador.rondas = {**(borrador.rondas or {}), 'precios': usadas + 1}
    borrador.save(update_fields=['rondas', 'actualizado'])
    return _json(True, f'La IA estimó {len(sugerencias)} de {len(faltan)} precio(s). Son recomendaciones: revísalas antes de usarlas.',
                 sugerencias=sugerencias)


@acceso_apu('apu.catalogo.manage')
@require_POST
def precio(request, pk):
    borrador = _borrador(request, pk)
    d = _datos(request)
    try:
        fecha = date.fromisoformat(str(d.get('fecha') or date.today().isoformat()))
        obj = asistente.cargar_precio(request.empresa, d.get('insumo'), d.get('precio'), d.get('moneda'),
                                      d.get('region', borrador.region), fecha, estimado=bool(d.get('estimado')),
                                      fuente=str(d.get('fuente') or ''))
    except (ErrorPaso, ValueError) as e:
        return _json(False, str(e) if isinstance(e, ErrorPaso) else 'La fecha no es válida.', 400)
    return _json(True, f'Se guardó el precio de «{obj.insumo.descripcion}».')


@acceso_apu('apu.catalogo.manage')
@require_POST
def guardar_apu(request, pk):
    borrador = _borrador(request, pk)
    if borrador.paso < 5:
        return _json(False, 'Termina los pasos anteriores primero.', 409, continuar_url=_url_paso(borrador))
    titulo = ' '.join(str(_datos(request).get('actividad') or '').split())
    if len(titulo) > 200:
        return _json(False, 'El título no puede superar los 200 caracteres.', 400)
    if titulo and titulo != borrador.actividad:        # la persona verificó o corrigió el título en el paso 5
        borrador.actividad = titulo
        borrador.save(update_fields=['actividad', 'actualizado'])
    try:
        item = asistente.guardar_apu(borrador, request.user)
    except creditos.SinCreditos as e:
        return _json(False, str(e), 402)
    except Conflicto as e:
        return _json(False, str(e), 409)
    except ErrorPaso as e:
        return _json(False, str(e), 400)
    return _json(True, f'Se guardó el APU {item.codigo} en «{borrador.proyecto.nombre}».',
                 continuar_url=reverse('apu_catalogo:item_detalle', args=[item.pk]))


# ── Pendientes ────────────────────────────────────────────────────────────────

@acceso_apu('apu.catalogo.manage')
def pendientes(request):
    qs = APUBorrador.objects.filter(empresa=request.empresa, eliminado=False, guardado=False).select_related(
        'proyecto', 'creado_por')
    if not es_admin_o_super(request.user, request.empresa):
        qs = qs.filter(Q(creado_por=request.user) | Q(proyecto__equipo__user=request.user, proyecto__equipo__activa=True)).distinct()
    return render(request, 'apu_generador/pendientes.html', {
        'borradores': qs.order_by('-actualizado'), 'pasos': {n: nombre for n, _, nombre in asistente.PASOS} | {1: 'Actividad'},
        **{'creditos': creditos.resumen(request.user, request.empresa)}})


@acceso_apu('apu.catalogo.manage')
def continuar(request, pk):
    """Lleva al borrador al paso en que quedó."""
    return redirect(_url_paso(_borrador(request, pk)))


@acceso_apu('apu.catalogo.manage')
@require_POST
def eliminar(request, pk):
    borrador = _borrador(request, pk)
    borrador.eliminado = True
    borrador.save(update_fields=['eliminado', 'actualizado'])
    messages.success(request, f'Se eliminó el borrador «{borrador.actividad}».')
    return redirect('apu_generador:pendientes')


# ── Reutilizar y modificar con IA ─────────────────────────────────────────────

def _proponer_modificacion(request, borrador, instruccion):
    """Cobra 1 crédito (modificar), llama a `apu-modificar` y deja la propuesta en el borrador para su revisión."""
    referencia = f'APUBorrador#{borrador.pk}'
    try:
        creditos.consumir(request.user, request.empresa, ConsumoAPU.Tipo.MODIFICAR, referencia)
    except creditos.SinCreditos as e:
        return str(e), 402
    payload = {'instruccion': instruccion, 'actividad': borrador.actividad, 'unidad': borrador.unidad,
               'proyecto': ia.contexto_proyecto(borrador.proyecto),
               'apu': {t: ({**getattr(borrador, t)} if getattr(borrador, t) else {'filas': []}) for t in ia.TIPOS_INSUMO},
               'catalogo': {t: asistente.catalogo_para_ia(request.empresa, t) for t in ia.TIPOS_INSUMO},
               'catalogo_items': asistente.catalogo_items_para_ia(request.empresa, borrador.apu_guardado_id)}
    try:
        crudo = ia.llamar('modificar', payload, empresa=request.empresa, usuario=request.user, borrador=borrador,
                          paso='modificar')
    except N8NError as e:
        creditos.revertir(request.user, request.empresa, ConsumoAPU.Tipo.MODIFICAR, referencia)
        return str(e), 502
    propuesta = {t: ia.normalizar_propuesta(crudo.get(t) or {}, t, con_defectos=False) for t in ia.TIPOS_INSUMO}
    for v in propuesta.values():
        v.pop('consultas', None)
    propuesta['actividad'] = asistente.limpiar_titulo(crudo.get('actividad'))      # el título también puede cambiar (se revisa)
    if not asistente.diferencias(borrador, propuesta):
        creditos.revertir(request.user, request.empresa, ConsumoAPU.Tipo.MODIFICAR, referencia)
        return 'La IA no encontró cambios que aplicar con esa instrucción. No se descontó ningún crédito.', 200
    borrador.instrucciones = list(borrador.instrucciones or []) + [{
        'instruccion': instruccion, 'resumen_cambios': str(crudo.get('resumen_cambios') or '')[:1000],
        'propuesta': propuesta, 'aplicada': False}]
    borrador.save(update_fields=['instrucciones', 'actualizado'])
    return '', 200


@acceso_apu('apu.catalogo.manage')
@require_POST
def modificar(request, pk):
    borrador = _borrador(request, pk)
    if borrador.paso < 5:
        return _json(False, 'Termina los pasos anteriores primero.', 409, continuar_url=_url_paso(borrador))
    instruccion = str(_datos(request).get('instruccion') or '').strip()
    if len(instruccion) < 5:
        return _json(False, 'Escribe qué quieres cambiar del APU.', 400)
    mensaje, estado = _proponer_modificacion(request, borrador, instruccion)
    if estado != 200:
        return _json(False, mensaje, estado)
    if mensaje:
        return _json(True, mensaje, sin_cambios=True)
    return _json(True, 'La IA propuso cambios. Revísalos antes de aplicarlos.',
                 continuar_url=reverse('apu_generador:revision', args=[borrador.pk]))


def _pendiente_de_revision(borrador):
    return next((i for i in reversed(borrador.instrucciones or []) if not i.get('aplicada')), None)


@acceso_apu('apu.catalogo.manage')
def revision(request, pk):
    """Una sola página con los cambios propuestos (agregados, quitados, cambiados), cada uno con su casilla."""
    borrador = _borrador(request, pk)
    mod = _pendiente_de_revision(borrador)
    if mod is None:
        return redirect(_url_paso(borrador))
    cambios = asistente.diferencias(borrador, mod['propuesta'])
    if request.method == 'POST':
        elegidos = request.POST.getlist('cambio')
        try:
            asistente.aplicar_cambios(borrador, mod['propuesta'], elegidos)
        except ErrorPaso as e:
            messages.error(request, str(e))
            return redirect('apu_generador:revision', pk=borrador.pk)
        mod['aplicada'] = True
        borrador.save(update_fields=['instrucciones', 'actualizado'])
        messages.success(request, f'Se aplicaron {len(elegidos)} cambio(s) a la composición.' if elegidos
                         else 'No se aplicó ningún cambio.')
        return redirect(_url_paso(borrador))
    return render(request, 'apu_generador/revision.html', {
        **_contexto_base(request, borrador), 'mod': mod, 'cambios': cambios})


def _apu_de_la_empresa(request, pk):
    return get_object_or_404(ItemModelo.objects.select_related('proyecto'), pk=pk, empresa=request.empresa)


@acceso_apu('apu.catalogo.manage')
@require_POST
def reutilizar(request, pk):
    """Copia un APU a otro proyecto (1 crédito) y, si hay prompt, pide a la IA los cambios (1 crédito más)."""
    item = _apu_de_la_empresa(request, pk)
    datos = _datos(request)
    destino = _habilitados(request.empresa).filter(pk=datos.get('proyecto') or 0).first()
    if destino is None:
        return _json(False, 'Elige un proyecto de destino habilitado para APU.', 400)
    instruccion = str(datos.get('instruccion') or '').strip()
    ok, motivo = creditos.puede_consumir(request.user, request.empresa)
    if not ok:
        return _json(False, motivo, 402)
    borrador = asistente.crear_borrador_reutilizado(item, destino, request.user, request.empresa)
    referencia = f'APUBorrador#{borrador.pk}'
    try:
        creditos.consumir(request.user, request.empresa, ConsumoAPU.Tipo.REUTILIZAR, referencia)
    except creditos.SinCreditos as e:
        borrador.delete()
        return _json(False, str(e), 402)
    if instruccion:
        mensaje, estado = _proponer_modificacion(request, borrador, instruccion)
        if estado != 200:  # la copia se conserva (ya se cobró) y queda lista en el paso 5
            return _json(False, mensaje + ' La copia quedó lista en el paso 5 sin cambios.', estado,
                         continuar_url=_url_paso(borrador))
        if not mensaje:
            return _json(True, 'Se copió el APU. La IA propuso cambios: revísalos antes de aplicarlos.',
                         continuar_url=reverse('apu_generador:revision', args=[borrador.pk]))
    return _json(True, f'Se copió el APU a «{destino.nombre}». Revisa los precios y guárdalo.',
                 continuar_url=_url_paso(borrador))


@acceso_apu('apu.catalogo.manage')
@require_POST
def modificar_apu(request, pk):
    """«Modificar con IA» desde la ficha: edita ese mismo APU (1 crédito)."""
    item = _apu_de_la_empresa(request, pk)
    if item.proyecto_id is None:
        return _json(False, 'Este APU no pertenece a un proyecto, así que no se puede modificar con IA.', 400)
    instruccion = str(_datos(request).get('instruccion') or '').strip()
    if len(instruccion) < 5:
        return _json(False, 'Escribe qué quieres cambiar del APU.', 400)
    borrador = asistente.crear_borrador_reutilizado(item, item.proyecto, request.user, request.empresa,
                                                    edita_el_mismo=True)
    mensaje, estado = _proponer_modificacion(request, borrador, instruccion)
    if estado != 200 or mensaje:
        borrador.delete()
        return _json(estado == 200, mensaje, estado, sin_cambios=estado == 200)
    return _json(True, 'La IA propuso cambios. Revísalos antes de aplicarlos.',
                 continuar_url=reverse('apu_generador:revision', args=[borrador.pk]))
