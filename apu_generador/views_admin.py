"""Pantallas de administración de APU: límites por empresa y persona (superusuario y administradores) y consumo de la
IA con sus tarifas (solo superusuario)."""
import json
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apu_catalogo.acceso import acceso_apu, es_admin_o_super
from core.n8n import N8NError
from cuentas.models import Membresia

from . import creditos, ia
from .models import ConsumoAPU, LimiteAPU, LimiteEmpresaAPU, LlamadaIA, TarifaModeloIA


def _json(ok, message='', status=200, **extra):
    return JsonResponse({'success': ok, 'message': message, **extra}, status=status)


def _datos(request):
    try:
        datos = json.loads(request.body or b'{}')
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _entero(valor, nombre):
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f'«{nombre}» debe ser un número entero.')
    if not 0 <= n <= 100000:
        raise ValueError(f'«{nombre}» debe estar entre 0 y 100000.')
    return n


def _solo_admins(request):
    if not es_admin_o_super(request.user, request.empresa):
        raise PermissionDenied


def _solo_super(request):
    if not request.user.is_superuser:
        raise PermissionDenied


# ── Usuarios: límites ─────────────────────────────────────────────────────────

@acceso_apu('apu.ver')
def usuarios(request):
    _solo_admins(request)
    empresa = request.empresa
    tope = creditos.limite_empresa(empresa)
    usado_dia, usado_mes = creditos.usado_empresa(empresa)
    fila_empresa = LimiteEmpresaAPU.objects.filter(empresa=empresa).first()
    miembros = []
    for m in empresa.membresias.filter(activa=True).select_related('user', 'rol').order_by('user__first_name', 'user__email'):
        max_dia, max_mes = creditos.limite_persona(m)
        dia, mes = creditos.usado_persona(m.user, empresa)
        miembros.append({'m': m, 'max_dia': max_dia, 'max_mes': max_mes, 'dia': dia, 'mes': mes,
                         'exento': es_admin_o_super(m.user, empresa)})
    return render(request, 'apu_generador/usuarios.html', {
        'empresa_limite': {'max_dia': fila_empresa.max_dia if fila_empresa else creditos.DEFECTO_EMPRESA[0],
                           'max_mes': fila_empresa.max_mes if fila_empresa else creditos.DEFECTO_EMPRESA[1],
                           'activo': fila_empresa.activo if fila_empresa else True, 'dia': usado_dia, 'mes': usado_mes},
        'sin_tope': tope is None, 'miembros': miembros, 'puede_empresa': request.user.is_superuser,
        'consumos': ConsumoAPU.objects.filter(empresa=empresa).select_related('usuario')[:50]})


@acceso_apu('apu.ver')
@require_POST
def limite_empresa(request):
    _solo_super(request)
    d = _datos(request)
    try:
        max_dia, max_mes = _entero(d.get('max_dia'), 'Por día'), _entero(d.get('max_mes'), 'Por mes')
    except ValueError as e:
        return _json(False, str(e), 400)
    LimiteEmpresaAPU.objects.update_or_create(empresa=request.empresa, defaults={
        'max_dia': max_dia, 'max_mes': max_mes, 'activo': bool(d.get('activo', True))})
    return _json(True, f'Límite de la empresa guardado: {max_dia} por día y {max_mes} por mes.')


@acceso_apu('apu.ver')
@require_POST
def limite_persona(request, pk):
    _solo_admins(request)
    membresia = get_object_or_404(Membresia, pk=pk, empresa=request.empresa, activa=True)
    d = _datos(request)
    try:
        max_dia, max_mes = _entero(d.get('max_dia'), 'Por día'), _entero(d.get('max_mes'), 'Por mes')
    except ValueError as e:
        return _json(False, str(e), 400)
    LimiteAPU.objects.update_or_create(membresia=membresia, defaults={'max_dia': max_dia, 'max_mes': max_mes})
    return _json(True, f'Límite de {membresia.user} guardado: {max_dia} por día y {max_mes} por mes.')


# ── Consumo de IA y tarifas ───────────────────────────────────────────────────

@acceso_apu('apu.ver')
def consumo_ia(request):
    _solo_super(request)
    ia.sincronizar_uso(list(LlamadaIA.objects.filter(uso__isnull=True).exclude(ejecucion_id='')[:50]))
    llamadas = LlamadaIA.objects.select_related('empresa', 'usuario').order_by('-fecha')[:1000]
    por_empresa, por_persona, por_mes = {}, {}, {}
    for ll in llamadas:
        for clave, destino in ((ll.empresa.nombre, por_empresa), (str(ll.usuario or '—'), por_persona),
                               (timezone.localtime(ll.fecha).strftime('%Y-%m'), por_mes)):
            fila = destino.setdefault(clave, {'nombre': clave, 'llamadas': 0, 'entrada': 0, 'salida': 0, 'costo': Decimal(0)})
            fila['llamadas'] += 1
            for v in (ll.uso or {}).values():
                fila['entrada'] += v.get('entrada', 0)
                fila['salida'] += v.get('salida', 0)
            fila['costo'] += ll.costo_usd or Decimal(0)
    return render(request, 'apu_generador/consumo_ia.html', {
        'total': ia.resumen_uso(llamadas), 'por_empresa': sorted(por_empresa.values(), key=lambda f: -f['costo']),
        'por_persona': sorted(por_persona.values(), key=lambda f: -f['costo']),
        'por_mes': sorted(por_mes.values(), key=lambda f: f['nombre'], reverse=True),
        'tarifas': TarifaModeloIA.objects.all(), 'medicion_activa': bool(settings.N8N_API_KEY)})


@acceso_apu('apu.ver')
@require_POST
def tarifas_verificar(request):
    """Pide a `apu-tarifas` las tarifas publicadas y devuelve las diferencias con las guardadas. No cobra créditos."""
    _solo_super(request)
    modelos = sorted({t.modelo for t in TarifaModeloIA.objects.all()} | {m for ll in LlamadaIA.objects.exclude(uso__isnull=True)[:200]
                                                                           for m in (ll.uso or {})})
    try:
        datos = ia.llamar('tarifas', {'modelos': modelos}, empresa=request.empresa, usuario=request.user, paso='tarifas')
    except N8NError as e:
        return _json(False, str(e), 502)
    guardadas = {t.modelo: t for t in TarifaModeloIA.objects.all()}
    cambios, revisadas = [], 0
    for t in datos.get('tarifas') or []:
        entrada, salida = ia.numero(t.get('entrada_usd_mtok')), ia.numero(t.get('salida_usd_mtok'))
        modelo = str(t.get('modelo') or '').strip()
        if not modelo or entrada is None or salida is None:
            continue
        revisadas += 1
        actual = guardadas.get(modelo)
        if actual is None or actual.entrada_usd_mtok != entrada or actual.salida_usd_mtok != salida:
            cambios.append({'modelo': modelo, 'entrada': str(entrada), 'salida': str(salida),
                            'actual': {'entrada': str(actual.entrada_usd_mtok), 'salida': str(actual.salida_usd_mtok)} if actual else None})
        elif actual:
            actual.verificada_en = timezone.now()
            actual.save(update_fields=['verificada_en'])
    if not revisadas:
        return _json(False, 'La IA no devolvió tarifas legibles. Inténtalo de nuevo.', 502)
    if not cambios:
        return _json(True, f'Las tarifas no cambiaron (verificadas el {timezone.localtime():%d/%m/%Y %H:%M}).', cambios=[])
    return _json(True, f'Se encontraron {len(cambios)} diferencia(s) de tarifa.', cambios=cambios,
                 fuente=str(datos.get('fuente') or ''))


@acceso_apu('apu.ver')
@require_POST
def tarifas_aplicar(request):
    _solo_super(request)
    d = _datos(request)
    aplicadas = 0
    for c in d.get('cambios') or []:
        entrada, salida = ia.numero(c.get('entrada')), ia.numero(c.get('salida'))
        modelo = str(c.get('modelo') or '').strip()
        if modelo and entrada is not None and salida is not None and entrada >= 0 and salida >= 0:
            TarifaModeloIA.objects.update_or_create(modelo=modelo, defaults={
                'entrada_usd_mtok': entrada, 'salida_usd_mtok': salida, 'fuente': str(d.get('fuente') or '')[:200],
                'verificada_en': timezone.now()})
            aplicadas += 1
    if not aplicadas:
        return _json(False, 'No había tarifas válidas que aplicar.', 400)
    return _json(True, f'Se actualizaron {aplicadas} tarifa(s).')


@acceso_apu('apu.ver')
@require_POST
def tarifa_editar(request, pk):
    _solo_super(request)
    tarifa = get_object_or_404(TarifaModeloIA, pk=pk)
    d = _datos(request)
    entrada, salida = ia.numero(d.get('entrada')), ia.numero(d.get('salida'))
    if entrada is None or salida is None or entrada < 0 or salida < 0:
        return _json(False, 'Indica tarifas válidas (cero o más).', 400)
    tarifa.entrada_usd_mtok, tarifa.salida_usd_mtok = entrada, salida
    tarifa.save()
    return _json(True, f'Tarifa de {tarifa.modelo} guardada.')
