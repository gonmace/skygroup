"""Tabla de ítems y avance de obra (Construcción).

Cada visita guarda `{"plantilla": "<nombre>", "partidas": [{"id", "nombre", "incidencia", "actual"}]}`. Lo acumulado NO
se guarda: se calcula recorriendo las visitas del proyecto por fecha, así editar una visita antigua se propaga a las
siguientes.

    anterior  = acumulada de la visita previa (por id de ítem)
    acumulada = min(100, anterior + actual)
    total     = incidencia × acumulada / 100        total_general = Σ total
"""
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from cuentas.capacidades import tiene_capacidad

from . import registrar
from .base import WidgetBase, texto_numero

CIEN, CERO, DOS = Decimal('100'), Decimal('0'), Decimal('0.01')
MAX_ITEMS = 100


def _dec(valor, defecto=CERO):
    if valor in (None, ''):
        return defecto
    try:
        return Decimal(str(valor).replace(',', '.').strip())
    except (InvalidOperation, ValueError):
        return defecto


def _num(d):
    """Decimal → float con 2 decimales (apto JSON)."""
    return float(d.quantize(DOS, rounding=ROUND_HALF_UP))


def redondear(d, decimales=2):
    return d.quantize(Decimal('0.1') if decimales == 1 else DOS, rounding=ROUND_HALF_UP)


def calcular_serie(visitas):
    """`visitas`: listas de partidas guardadas, en orden cronológico. Devuelve una lista paralela de
    `{'filas': […], 'total': Decimal}`. Una visita sin partidas hereda la estructura de la anterior con actual = 0."""
    acumulado, estructura, serie = {}, [], []
    for partidas in visitas:
        if partidas:
            estructura = [{'id': p['id'], 'nombre': p['nombre'], 'incidencia': _dec(p.get('incidencia'))} for p in partidas]
            actuales = {p['id']: _dec(p.get('actual')) for p in partidas}
        else:
            actuales = {}
        filas, total = [], CERO
        for p in estructura:
            anterior = acumulado.get(p['id'], CERO)
            actual = actuales.get(p['id'], CERO)
            acumulada = min(CIEN, anterior + actual)
            fila_total = p['incidencia'] * acumulada / CIEN
            acumulado[p['id']] = acumulada
            total += fila_total
            filas.append({'id': p['id'], 'nombre': p['nombre'], 'incidencia': p['incidencia'], 'anterior': anterior,
                          'actual': actual, 'acumulada': acumulada, 'total': fila_total})
        serie.append({'filas': filas, 'total': total})
    return serie


def _guardadas(modelo, ids, paso_nombre):
    from reg_actividades.models import DatoPaso
    ct = ContentType.objects.get_for_model(modelo)
    return {d.object_id: ((d.datos or {}).get(TablaAvanceWidget.slug) or {}).get('partidas') or []
            for d in DatoPaso.objects.filter(content_type=ct, object_id__in=ids, paso_nombre=paso_nombre)}


def serie_proyecto(registro, paso_nombre, solo_hasta_registro=True, override=None):
    """Cálculo para las visitas del proyecto del `registro` (orden cronológico). Devuelve `[(registro_id, resultado)]`.
    `override`: `{registro_id: partidas}` para calcular con datos aún no guardados (repintado tras un error)."""
    modelo = type(registro)
    if not registro.proyecto_id:
        ids = [registro.pk]
    else:
        qs = modelo.objects.filter(proyecto_id=registro.proyecto_id, empresa_id=registro.empresa_id, is_deleted=False)
        if solo_hasta_registro:
            qs = qs.filter(Q(fecha__lt=registro.fecha) | Q(fecha=registro.fecha, id__lte=registro.id))
        ids = list(qs.order_by('fecha', 'id').values_list('id', flat=True))
        if solo_hasta_registro and registro.pk not in ids:
            ids.append(registro.pk)
    guardado = _guardadas(modelo, ids, paso_nombre)
    guardado.update(override or {})
    return list(zip(ids, calcular_serie([guardado.get(i, []) for i in ids])))


def recalcular_avance(modelo, proyecto_id, empresa_id, paso_nombre):
    """Reescribe `avance_pct` de TODAS las visitas del proyecto (el acumulado de una depende de las anteriores).
    Usa update() a propósito: no dispara señales."""
    if not proyecto_id:
        return
    ref = modelo.objects.filter(proyecto_id=proyecto_id, empresa_id=empresa_id, is_deleted=False).order_by('-fecha', '-id').first()
    if ref is None:
        return
    for registro_id, resultado in serie_proyecto(ref, paso_nombre, solo_hasta_registro=False):
        total = min(CIEN, max(CERO, redondear(resultado['total'])))
        modelo.objects.filter(pk=registro_id).update(avance_pct=total)


def _filas_vista(filas):
    return [{'id': f['id'], 'nombre': f['nombre'], 'incidencia': _num(f['incidencia']), 'anterior': _num(f['anterior']),
             'actual': _num(f['actual']), 'acumulada': _num(f['acumulada']), 'total': _num(f['total'])} for f in filas]


def _lista(post, nombre):
    return post.getlist(nombre) if hasattr(post, 'getlist') else list(post.get(nombre) or [])


def _plantillas(config):
    crudo = config.get('plantillas') or []
    return crudo if isinstance(crudo, list) else []


@registrar
class TablaAvanceWidget(WidgetBase):
    slug = 'tabla_avance_widget'
    nombre = 'Tabla de avance'
    plantilla = 'reg_actividades/widgets/tabla_avance.html'

    def validar_config(self, config):
        errores = []
        if 'plantillas' in config and not isinstance(config['plantillas'], list):
            return ['plantillas debe ser una lista.']
        nombres = set()
        for i, pl in enumerate(_plantillas(config), start=1):
            nombre = pl.get('nombre') if isinstance(pl, dict) else None
            if not nombre or not isinstance(nombre, str):
                errores.append(f'La plantilla {i} necesita un «nombre».')
                continue
            if nombre in nombres:
                errores.append(f'La plantilla «{nombre}» está repetida.')
            nombres.add(nombre)
            partidas = pl.get('partidas')
            if not isinstance(partidas, list) or not partidas or not all(isinstance(p, dict) and p.get('nombre') for p in partidas):
                errores.append(f'La plantilla «{nombre}» necesita ítems con «nombre» e «incidencia».')
                continue
            total = sum((_dec(p.get('incidencia')) for p in partidas), CERO)
            if total != CIEN:
                errores.append(f'La plantilla «{nombre}» suma {total}% de incidencia (debe sumar 100%).')
        return errores

    # ── Lectura del POST, con las reglas de cada rol ────────────────────────────────────────────────
    def _permisos(self, ctx):
        user, registro = (ctx.user if ctx else None), (ctx.registro if ctx else None)
        if user is None or registro is None:
            return False, False
        return (tiene_capacidad(user, 'reg.items_obra', registro.empresa_id),
                tiene_capacidad(user, 'reg.cargar_datos', registro.empresa_id))

    def leer(self, post, files, config, ctx=None):
        previos = (ctx.extra.get('previos') if ctx else None) or {}
        estructura_ok, cargar_ok = self._permisos(ctx)
        if not estructura_ok and not cargar_ok:
            return previos, ['No tienes permiso para modificar la tabla de avance.']

        # «Aplicar plantilla» reemplaza los ítems por los de la plantilla elegida (solo quien define la estructura).
        elegida = post.get(self.nombre_campo('plantilla'), '')
        if estructura_ok and post.get(self.nombre_campo('aplicar')):
            plantilla = next((p for p in _plantillas(config) if p.get('nombre') == elegida), None)
            if plantilla is None:
                return previos, ['Elige una plantilla para aplicar.']
            partidas = [{'id': uuid.uuid4().hex[:12], 'nombre': p['nombre'], 'incidencia': _num(_dec(p.get('incidencia'))),
                         'actual': 0.0} for p in plantilla['partidas']]
            return {'plantilla': elegida, 'partidas': partidas}, []

        ids = _lista(post, self.nombre_campo('id'))
        nombres = _lista(post, self.nombre_campo('nombre'))
        incidencias = _lista(post, self.nombre_campo('incidencia'))
        actuales = _lista(post, self.nombre_campo('actual'))
        filas, errores, vistos = [], [], set()
        for i in range(max(len(nombres), len(actuales))):
            nombre = (nombres[i] if i < len(nombres) else '').strip()
            if not nombre and not (incidencias[i:i + 1] and incidencias[i].strip()) and not (actuales[i:i + 1] and actuales[i].strip()):
                continue                                   # fila en blanco
            pid = (ids[i] if i < len(ids) else '').strip() or uuid.uuid4().hex[:12]
            if pid in vistos:
                errores.append('Hay ítems con el mismo id.')
                continue
            vistos.add(pid)
            fila = {'id': pid, 'nombre': nombre, 'incidencia': incidencias[i] if i < len(incidencias) else '',
                    'actual': actuales[i] if i < len(actuales) else ''}
            if estructura_ok and not nombre:
                errores.append(f'El ítem {len(filas) + 1} necesita un nombre.')
            elif estructura_ok and len(nombre) > 120:
                errores.append(f'«{nombre[:20]}…»: el nombre supera los 120 caracteres.')
            # Quien solo carga datos no cambia nombre ni incidencia: solo se valida su % actual.
            campos = (('incidencia', 'La incidencia'), ('actual', 'El % de ejecución actual')) if estructura_ok \
                else (('actual', 'El % de ejecución actual'),)
            for campo, etiqueta in campos:
                v = _dec(fila[campo], None) if str(fila[campo]).strip() else CERO
                if v is None or v < 0 or v > 100:
                    errores.append(f'{etiqueta} de «{nombre or i + 1}» debe estar entre 0 y 100.')
            filas.append(fila)
        if len(filas) > MAX_ITEMS:
            errores.append(f'Máximo {MAX_ITEMS} ítems.')
        if errores:
            return {'plantilla': elegida or previos.get('plantilla', ''), 'partidas': filas}, errores

        partidas = [{'id': f['id'], 'nombre': f['nombre'], 'incidencia': _num(_dec(f['incidencia'])),
                     'actual': _num(_dec(f['actual']))} for f in filas]
        plantilla = elegida if estructura_ok else previos.get('plantilla', '')
        if estructura_ok and cargar_ok:
            return {'plantilla': plantilla, 'partidas': partidas}, []
        if estructura_ok:
            # Define los ítems pero no carga datos: conserva el % actual ya guardado.
            guardado = {p.get('id'): p.get('actual', 0.0) for p in previos.get('partidas') or []}
            for p in partidas:
                p['actual'] = guardado.get(p['id'], 0.0)
            return {'plantilla': plantilla, 'partidas': partidas}, []
        # Quien solo carga datos (ITO, Buscador…): cambia únicamente el % actual de los ítems ya definidos.
        referencia = serie_proyecto(ctx.registro, ctx.paso.nombre)[-1][1]['filas']
        enviados = {p['id']: p for p in partidas}
        return {'plantilla': plantilla, 'partidas': [
            {'id': f['id'], 'nombre': f['nombre'], 'incidencia': _num(f['incidencia']),
             'actual': enviados.get(f['id'], {}).get('actual', 0.0)} for f in referencia]}, []

    def nivel(self, datos, config, ctx):
        return 3 if (datos or {}).get('partidas') else 1

    # ── Presentación ─────────────────────────────────────────────────────────────────────────────────
    def contexto(self, datos, config, ctx):
        datos = datos or {}
        estructura_ok, cargar_ok = self._permisos(ctx)
        actual_con_datos = datos.get('partidas')
        override = {ctx.registro.pk: actual_con_datos} if actual_con_datos is not None and ctx.registro.pk else None
        # Con datos aún no guardados (repintado tras un error) se calcula sobre lo escrito.
        resultado = serie_proyecto(ctx.registro, ctx.paso.nombre, override=override)[-1][1]
        filas = _filas_vista(resultado['filas'])
        suma = sum((f['incidencia'] for f in filas), 0.0)
        escrito = {p.get('id'): p for p in actual_con_datos or [] if isinstance(p, dict)}
        for f in filas:       # textos sin localizar para los <input>; tras un error se conserva lo que escribió la persona
            f['incidencia_txt'], f['actual_txt'] = texto_numero(f['incidencia']), texto_numero(f['actual'])
            for campo in ('incidencia', 'actual'):
                crudo = escrito.get(f['id'], {}).get(campo)
                if isinstance(crudo, str):
                    f[f'{campo}_txt'] = crudo
        return {
            'etiqueta': config.get('label', self.nombre), 'filas': filas, 'total': _num(resultado['total']),
            'suma_incidencia': round(suma, 2), 'incidencia_ok': abs(suma - 100) < 0.005 or not filas,
            'plantillas': [p['nombre'] for p in _plantillas(config) if isinstance(p, dict) and p.get('nombre')],
            'plantilla_actual': datos.get('plantilla', ''),
            'puede_estructura': estructura_ok and ctx.puede_escribir, 'puede_actual': cargar_ok and ctx.puede_escribir,
            'campo_id': self.nombre_campo('id'), 'campo_nombre': self.nombre_campo('nombre'),
            'campo_incidencia': self.nombre_campo('incidencia'), 'campo_actual': self.nombre_campo('actual'),
            'campo_plantilla': self.nombre_campo('plantilla'), 'campo_aplicar': self.nombre_campo('aplicar'),
        }
