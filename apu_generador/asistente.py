"""Lógica del generador de APU (sin vistas): vocabulario de la empresa, guardado de pasos, vista previa, guardado
idempotente del APU y reutilización. La IA no vive aquí: ver `ia.py` y los workflows de n8n."""
import copy
import re
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q

from apu_catalogo import calculo, categorias as cats, unidades
from apu_catalogo.models import Insumo, ItemModelo, LineaComposicion, PerfilCalculo, PrecioInsumo, ProyectoAPU, Tipo

from . import creditos, ia
from .ia import CODIGO_TIPO, clave_texto, numero
from .models import APUBorrador, ConsumoAPU

PASOS = [(2, 'materiales', 'Materiales'), (3, 'mano_obra', 'Mano de obra'), (4, 'equipos', 'Equipos'),
         (5, 'resultado', 'Precios y resultado')]
PASO_DE = {t: n for n, t, _ in PASOS}
TIPO_DE_PASO = {n: t for n, t, _ in PASOS}
SLUG_URL = {'materiales': 'materiales', 'mano_obra': 'mano-obra', 'equipos': 'equipos'}
TIPO_DE_SLUG = {v: k for k, v in SLUG_URL.items()}
TIPO_INSUMO = {'materiales': Tipo.MATERIAL, 'mano_obra': Tipo.MANO_OBRA, 'equipos': Tipo.EQUIPO}
MAX_REPETICIONES = 3        # «proponer de nuevo» / respuestas a dudas, además de la primera propuesta de cada paso
MIN_PALABRAS_DESCRIPCION = 15
LIMITE_CATALOGO_MATERIALES = 120   # filas de catálogo que se mandan a la IA (las más parecidas a la actividad)
LIMITE_CATALOGO_ITEMS = 40          # APU del catálogo (sub-análisis) que se mandan a la IA
LIMITE_DECISIONES_PREVIAS = 5


class ErrorPaso(Exception):
    """Dato inválido al guardar un paso. El mensaje es apto para mostrar."""


# ── Proyecto ──────────────────────────────────────────────────────────────────

def descripcion_suficiente(proyecto):
    return len(re.findall(r'\w+', proyecto.descripcion or '')) >= MIN_PALABRAS_DESCRIPCION


def asegurar_proyecto_apu(proyecto, perfil_id, empresa, region=None):
    """El `ProyectoAPU` del proyecto con el perfil elegido (siempre uno de la empresa: una plantilla se copia a la
    empresa). Sin `perfil_id` se conserva el que ya tiene; si no tiene ninguno, es obligatorio."""
    existente = ProyectoAPU.objects.select_related('perfil').filter(proyecto=proyecto).first()
    if not perfil_id:
        if existente:
            return existente
        raise ErrorPaso('Elige el perfil de cálculo del proyecto.')
    perfil = PerfilCalculo.para_empresa(empresa, perfil_id)
    if perfil is None:
        raise ErrorPaso('Ese perfil de cálculo no existe.')
    region = (region or '').strip()[:80]
    if existente is None:
        return ProyectoAPU.objects.create(proyecto=proyecto, perfil=perfil, region=region)
    if existente.perfil_id != perfil.pk:   # cambiar de perfil: los ajustes que ya no existan en él se ignoran
        existente.perfil = perfil
        existente.save(update_fields=['perfil'])
    return existente


# ── Catálogo y vocabulario de la empresa ──────────────────────────────────────

def catalogo_para_ia(empresa, tipo, texto=''):
    """Insumos de la empresa del tipo pedido, como los recibe la IA. Mano de obra y equipos van completos; en
    materiales se priorizan los que comparten palabras con la actividad (hasta `LIMITE_CATALOGO_MATERIALES`)."""
    qs = Insumo.objects.filter(empresa=empresa, tipo=TIPO_INSUMO[tipo], activo=True).order_by('codigo')
    filas = [{'codigo': i.codigo, 'descripcion': i.descripcion, 'unidad': i.unidad} for i in qs[:3000]]
    if tipo == 'materiales' and len(filas) > LIMITE_CATALOGO_MATERIALES:
        palabras = {w for w in clave_texto(texto).split() if len(w) > 3}
        filas.sort(key=lambda f: -len(palabras & set(clave_texto(f['descripcion']).split())))
        filas = filas[:LIMITE_CATALOGO_MATERIALES]
    return filas


def catalogo_items_para_ia(empresa, excluir_pk=None, texto=''):
    """APU de la empresa (posibles sub-análisis). Se mandan los `LIMITE_CATALOGO_ITEMS` más parecidos al `texto`
    (palabras en común); sin texto, los primeros por código."""
    qs = ItemModelo.objects.filter(empresa=empresa, activo=True).order_by('codigo')
    if excluir_pk:
        qs = qs.exclude(pk=excluir_pk)
    filas = [{'codigo': i.codigo, 'descripcion': i.descripcion, 'unidad': i.unidad} for i in qs[:300]]
    if len(filas) > LIMITE_CATALOGO_ITEMS:
        palabras = {w for w in clave_texto(texto).split() if len(w) > 3}
        filas.sort(key=lambda f: -len(palabras & set(clave_texto(f['descripcion']).split())))
        filas = filas[:LIMITE_CATALOGO_ITEMS]
    return filas


def decisiones_previas(empresa, excluir_pk=None, limite=LIMITE_DECISIONES_PREVIAS):
    """Lo que la empresa ya decidió en consultas de otros APU, para que la IA recomiende lo mismo."""
    salida = []
    for b in APUBorrador.objects.filter(empresa=empresa, eliminado=False).exclude(pk=excluir_pk).order_by('-actualizado')[:40]:
        for datos in (b.consultas or {}).values():
            for d in (datos.get('decisiones') or {}).values():
                if d.get('pregunta') and d.get('elegida'):
                    salida.append({'pregunta': d['pregunta'], 'elegida': d['elegida']})
    return salida[:limite]


def aclaraciones(borrador, excepto):
    """Lo que la persona ya respondió a la IA en los OTROS pasos de este APU (respuestas a dudas y opciones elegidas), para
    que no se vuelva a preguntar lo mismo."""
    salida = []
    for tipo in ia.TIPOS_INSUMO:
        if tipo == excepto:
            continue
        datos = (borrador.consultas or {}).get(tipo, {})
        salida += [{'pregunta': h['pregunta'], 'respuesta': h['respuesta']} for h in datos.get('historial', [])]
        salida += [{'pregunta': d['pregunta'], 'respuesta': d['elegida']} for d in (datos.get('decisiones') or {}).values()
                   if d.get('pregunta') and d.get('elegida')]
    return salida


def _siguiente_codigo(empresa, prefijo):
    ultimo = 0
    for c in Insumo.objects.filter(empresa=empresa, codigo__startswith=f'{prefijo}-').values_list('codigo', flat=True):
        m = re.fullmatch(rf'{prefijo}-(\d+)', c)
        if m:
            ultimo = max(ultimo, int(m.group(1)))
    return f'{prefijo}-{ultimo + 1:03d}'


def resolver_insumo(empresa, tipo, fila):
    """El `Insumo` de la empresa para una fila confirmada: el del catálogo (por código), uno con la misma descripción
    (sin distinguir mayúsculas, tildes ni espacios) o uno nuevo, sin precio, con código por tipo (MO-001…)."""
    tipo_db = TIPO_INSUMO[tipo]
    codigo = fila.get('codigo_catalogo')
    if codigo:
        insumo = Insumo.objects.filter(empresa=empresa, codigo=codigo, tipo=tipo_db).first()
        if insumo:
            return insumo
    objetivo = clave_texto(fila['descripcion'])
    for insumo in Insumo.objects.filter(empresa=empresa, tipo=tipo_db):
        if clave_texto(insumo.descripcion) == objetivo:
            return insumo
    if not fila.get('unidad'):
        raise ErrorPaso(f'Falta la unidad de «{fila["descripcion"]}».')
    prefijo = CODIGO_TIPO[tipo]
    for _ in range(5):
        try:
            with transaction.atomic():
                return Insumo.objects.create(empresa=empresa, codigo=_siguiente_codigo(empresa, prefijo),
                                             descripcion=fila['descripcion'], unidad=unidades.normalizar(fila['unidad'])[:20], tipo=tipo_db)
        except IntegrityError:
            continue
    raise ErrorPaso('No se pudo crear el insumo. Inténtalo de nuevo.')


# ── Guardar un paso ───────────────────────────────────────────────────────────

def consultas_pendientes(borrador, tipo, decisiones):
    """Consultas de la última propuesta del paso que aún no tienen respuesta."""
    propuesta = (borrador.consultas or {}).get(tipo, {}).get('propuesta') or {}
    return [c for c in propuesta.get('consultas', []) if not str((decisiones or {}).get(c['id']) or '').strip()]


def guardar_paso(borrador, tipo, datos):
    """Valida y guarda lo confirmado en el paso `tipo` (materiales | mano_obra | equipos) y avanza `paso`.
    `datos`: {filas, decisiones, rendimiento?, horas_jornada?}. Solo se guardan las filas marcadas."""
    empresa = borrador.empresa
    decisiones = datos.get('decisiones') or {}
    if consultas_pendientes(borrador, tipo, decisiones):
        raise ErrorPaso('Responde las consultas pendientes antes de continuar.')

    horas = rendimiento = None
    if tipo == 'mano_obra':
        horas, rendimiento = numero(datos.get('horas_jornada')), numero(datos.get('rendimiento'))
        if not horas or horas <= 0 or not rendimiento or rendimiento <= 0:
            raise ErrorPaso('Indica el rendimiento (unidades por jornada) y las horas de jornada.')

    confirmadas = []
    for crudo in datos.get('filas') or []:
        fila = ia.normalizar_fila(crudo, tipo)
        if fila is None or not crudo.get('check'):
            continue
        if fila.get('codigo_subitem'):
            sub = ItemModelo.objects.filter(empresa=empresa, codigo=fila['codigo_subitem'], activo=True).first()
            if sub is None:
                raise ErrorPaso(f'El sub-análisis «{fila["codigo_subitem"]}» no existe en tu catálogo de APU.')
            fila['subitem_id'] = sub.pk
        else:
            fila['insumo_id'] = resolver_insumo(empresa, tipo, fila).pk
        if tipo == 'mano_obra':
            personas = Decimal(fila['personas'])
            if personas <= 0:
                raise ErrorPaso(f'«{fila["descripcion"]}» necesita al menos una persona.')
            fila['cantidad'] = str((personas * horas / rendimiento).quantize(Decimal('0.000001')))
        elif Decimal(fila['cantidad']) <= 0:
            raise ErrorPaso(f'«{fila["descripcion"]}» necesita una cantidad mayor que cero.')
        confirmadas.append(fila)
    if not confirmadas:
        raise ErrorPaso('Marca al menos una fila para continuar.')

    guardado = {'filas': confirmadas}
    if tipo == 'mano_obra':
        guardado.update(rendimiento=str(rendimiento), horas_jornada=str(horas))
    setattr(borrador, tipo, guardado)

    propuesta = (borrador.consultas or {}).get(tipo, {})
    registro = {}
    for c in (propuesta.get('propuesta') or {}).get('consultas', []):
        elegida = str(decisiones.get(c['id']) or '').strip()
        etiqueta = next((o['etiqueta'] for o in c['opciones'] if o['clave'] == elegida), elegida)
        registro[c['id']] = {'pregunta': c['pregunta'], 'elegida': etiqueta, 'clave': elegida}
    propuesta['decisiones'] = registro
    borrador.consultas = {**(borrador.consultas or {}), tipo: propuesta}
    borrador.paso = PASO_DE[tipo] + 1
    borrador.save()


# ── Vista previa y resultado ──────────────────────────────────────────────────

def filas_resueltas(borrador):
    """Todas las filas confirmadas (de los tres pasos) con su insumo/sub-ítem cargado."""
    insumos = Insumo.objects.in_bulk(
        [f['insumo_id'] for t in ia.TIPOS_INSUMO for f in borrador.filas(t) if f.get('insumo_id')])
    subitems = ItemModelo.objects.in_bulk(
        [f['subitem_id'] for t in ia.TIPOS_INSUMO for f in borrador.filas(t) if f.get('subitem_id')])
    salida = []
    for tipo in ia.TIPOS_INSUMO:
        for f in borrador.filas(tipo):
            salida.append({**f, 'tipo_paso': tipo, 'insumo': insumos.get(f.get('insumo_id')),
                           'subitem': subitems.get(f.get('subitem_id'))})
    return salida


def previsualizar(borrador, perfil=None):
    """Precios por fila y precio unitario con el perfil efectivo del proyecto, sin guardar el APU."""
    perfil = perfil or calculo.perfil_del_proyecto(borrador.proyecto)
    acumulado = {t: Decimal(0) for t in Tipo.values}
    filas, sin_precio = [], []
    for f in filas_resueltas(borrador):
        cantidad = Decimal(f.get('cantidad') or 0)
        desperdicio = Decimal(f.get('desperdicio_pct') or 0)
        efectiva = cantidad * (1 + desperdicio / 100)
        precio = moneda = vigente = None
        if f['subitem']:
            grupos, faltan = calculo.grupos_de(f['subitem'], borrador.region, factor=efectiva)
            costo = sum(grupos.values(), Decimal(0))
            for t, v in grupos.items():
                acumulado[t] += v
            sin_precio += [i for i in faltan if i not in sin_precio]
        else:
            vigente = f['insumo'].precio_vigente(borrador.region)
            if vigente is None:
                costo = Decimal(0)
                if f['insumo'] not in sin_precio:
                    sin_precio.append(f['insumo'])
            else:
                precio, moneda = vigente.precio, vigente.moneda
                costo = efectiva * precio
            acumulado[f['insumo'].tipo] += costo
        filas.append({**f, 'precio': precio, 'moneda': moneda, 'costo': costo, 'sin_precio': f['insumo'] is not None and precio is None,
                      'estimado': bool(vigente.estimado) if not f['subitem'] and vigente else False})
    resultado = calculo.calcular(perfil, acumulado) if perfil else None
    return {'filas': filas, 'grupos': acumulado, 'sin_precio': sin_precio, 'n_estimados': sum(1 for f in filas if f['estimado']),
            'perfil': perfil, 'resultado': resultado,
            'moneda': perfil['moneda'] if perfil else ''}


def cargar_precio(empresa, insumo_pk, precio, moneda, region, fecha, estimado=False, fuente=''):
    """Guarda (o actualiza) el precio de un insumo de la empresa. Devuelve el `PrecioInsumo`."""
    insumo = Insumo.objects.filter(empresa=empresa, pk=insumo_pk).first()
    valor = numero(precio)
    moneda = (moneda or '').strip().upper()
    if insumo is None:
        raise ErrorPaso('El insumo no existe.')
    if valor is None or valor < 0:
        raise ErrorPaso('Indica un precio válido (cero o más).')
    if len(moneda) != 3:
        raise ErrorPaso('Indica la moneda con su código de 3 letras (p. ej. BOB).')
    obj, _ = PrecioInsumo.objects.update_or_create(insumo=insumo, region=(region or '').strip(), fecha=fecha,
                                                   defaults={'precio': valor, 'moneda': moneda, 'estimado': bool(estimado),
                                                                     'fuente': (fuente or '')[:200]})
    return obj


def _codigo_apu(empresa, proyecto):
    ultimo = 0
    for c in ItemModelo.objects.filter(empresa=empresa, proyecto=proyecto, codigo__startswith='APU-').values_list('codigo', flat=True):
        m = re.fullmatch(r'APU-(\d+)', c)
        if m:
            ultimo = max(ultimo, int(m.group(1)))
    return f'APU-{ultimo + 1:03d}'


@transaction.atomic
def _crear_o_actualizar_apu(borrador, user):
    empresa = borrador.empresa
    item = borrador.apu_guardado
    categoria = cats.obtener_o_crear(empresa, (borrador.clasificacion or {}).get('categoria', ''))
    if item is None:
        for _ in range(5):
            try:
                with transaction.atomic():
                    item = ItemModelo.objects.create(
                        empresa=empresa, proyecto=borrador.proyecto, codigo=_codigo_apu(empresa, borrador.proyecto),
                        descripcion=borrador.actividad[:250], unidad=borrador.unidad, categoria=categoria,
                        origen=borrador.origen, creado_por=user)
                break
            except IntegrityError:
                item = None
        if item is None:
            raise ErrorPaso('No se pudo crear el APU. Inténtalo de nuevo.')
    else:
        item.descripcion, item.unidad = borrador.actividad[:250], borrador.unidad
        if categoria:
            item.categoria = categoria
        item.save()
        item.lineas.all().delete()
    orden = 0
    for f in filas_resueltas(borrador):
        orden += 1
        ayuda = {}
        if f['tipo_paso'] == 'mano_obra':
            ayuda = {'personas': f.get('personas'), 'horas_jornada': borrador.mano_obra.get('horas_jornada'),
                     'rendimiento': borrador.mano_obra.get('rendimiento')}
        LineaComposicion.objects.create(
            item=item, insumo=f['insumo'], subitem=f['subitem'], cantidad=Decimal(f['cantidad']),
            desperdicio_pct=Decimal(f.get('desperdicio_pct') or 0), ayuda=ayuda, orden=orden)
    borrador.apu_guardado, borrador.guardado = item, True
    borrador.save(update_fields=['apu_guardado', 'guardado', 'actualizado'])
    return item


def guardar_apu(borrador, user):
    """Paso 5: cobra 1 crédito (una sola vez por borrador) y crea o actualiza el APU del proyecto. Si algo falla, el
    crédito se devuelve. Lanza `creditos.SinCreditos` (402), `ErrorPaso` (400) o `Conflicto` (409)."""
    if borrador.guardado and borrador.apu_guardado_id:   # guardar dos veces no duplica ni vuelve a cobrar
        return borrador.apu_guardado
    reservado = False
    if not borrador.credito_consumido:
        ok, motivo = creditos.puede_consumir(user, borrador.empresa)
        if not ok:
            raise creditos.SinCreditos(motivo)
        # Reserva atómica: de dos peticiones simultáneas solo una gana.
        if not APUBorrador.objects.filter(pk=borrador.pk, credito_consumido=False).update(credito_consumido=True):
            raise Conflicto('Este APU ya se está guardando.')
        try:
            creditos.consumir(user, borrador.empresa, ConsumoAPU.Tipo.GENERAR, referencia=f'APUBorrador#{borrador.pk}')
        except creditos.SinCreditos:
            APUBorrador.objects.filter(pk=borrador.pk).update(credito_consumido=False)
            raise
        reservado = True
    try:
        item = _crear_o_actualizar_apu(borrador, user)
    except Exception:
        if reservado:
            creditos.revertir(user, borrador.empresa, ConsumoAPU.Tipo.GENERAR, f'APUBorrador#{borrador.pk}')
            APUBorrador.objects.filter(pk=borrador.pk).update(credito_consumido=False)
        raise
    borrador.credito_consumido = True
    return item


class Conflicto(Exception):
    pass


# ── Reutilizar y modificar ────────────────────────────────────────────────────

def _region_del_proyecto(proyecto):
    pa = ProyectoAPU.objects.filter(proyecto=proyecto).first()
    return pa.region if pa else ''


def filas_de_apu(item):
    """La composición de un APU guardado como pasos del borrador: {materiales, mano_obra, equipos}."""
    pasos = {'materiales': {'filas': []}, 'mano_obra': {'filas': []}, 'equipos': {'filas': []}}
    for linea in item.lineas.select_related('insumo', 'subitem').all():
        if linea.subitem_id:
            pasos['materiales']['filas'].append({
                'descripcion': str(linea.subitem), 'unidad': linea.subitem.unidad, 'subitem_id': linea.subitem_id,
                'codigo_subitem': linea.subitem.codigo, 'cantidad': str(linea.cantidad),
                'desperdicio_pct': str(linea.desperdicio_pct), 'check': True, 'nuevo': False,
                'justificacion': '', 'codigo_catalogo': '', 'consulta': ''})
            continue
        tipo = {'MAT': 'materiales', 'MO': 'mano_obra', 'EQ': 'equipos'}[linea.insumo.tipo]
        fila = {'descripcion': linea.insumo.descripcion, 'unidad': linea.insumo.unidad, 'insumo_id': linea.insumo_id,
                'codigo_catalogo': linea.insumo.codigo, 'cantidad': str(linea.cantidad), 'check': True, 'nuevo': False,
                'justificacion': '', 'consulta': ''}
        if tipo == 'materiales':
            fila['desperdicio_pct'] = str(linea.desperdicio_pct)
        if tipo == 'mano_obra':
            fila['personas'] = str((linea.ayuda or {}).get('personas') or 1)
            for k in ('rendimiento', 'horas_jornada'):
                if (linea.ayuda or {}).get(k):
                    pasos['mano_obra'][k] = str(linea.ayuda[k])
        pasos[tipo]['filas'].append(fila)
    pasos['mano_obra'].setdefault('rendimiento', '1')
    pasos['mano_obra'].setdefault('horas_jornada', '8')
    return pasos


def crear_borrador_reutilizado(item, proyecto, user, empresa, *, edita_el_mismo=False):
    """Borrador en modo `reutilizar` con la composición de `item`, listo en el paso 5. Con `edita_el_mismo` el
    borrador actualiza ese mismo APU (modificarlo con IA desde su ficha) en vez de crear una copia."""
    pasos = filas_de_apu(item)
    return APUBorrador.objects.create(
        empresa=empresa, proyecto=proyecto, creado_por=user, actividad=item.descripcion, unidad=item.unidad,
        descripcion='', region=_region_del_proyecto(proyecto), modo=APUBorrador.Modo.REUTILIZAR, origen=item, paso=5, credito_consumido=True,
        clasificacion={'categoria': item.categoria.nombre if item.categoria_id else ''}, apu_guardado=item if edita_el_mismo else None, **pasos)


def limpiar_titulo(texto):
    """El título propuesto por la IA, sin la unidad ni aclaraciones entre paréntesis al final (p. ej. «(unidad: m3)»)."""
    texto = re.sub(r'\s*\((?:unidad|un\.?|u\.)[^)]*\)\s*$', '', str(texto or ''), flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', texto).strip()[:200]


def _clave_fila(fila):
    return clave_texto(fila.get('descripcion'))


def diferencias(borrador, propuesta):
    """Cambios entre lo actual y lo propuesto por `apu-modificar`: agregados, quitados y cambiados, por paso.
    Cada cambio lleva un `id` estable para que la persona marque cuáles aplica."""
    cambios = []
    nuevo_titulo = limpiar_titulo(propuesta.get('actividad'))
    if nuevo_titulo and clave_texto(nuevo_titulo) != clave_texto(borrador.actividad):
        cambios.append({'id': 'actividad', 'tipo': 'actividad', 'clase': 'cambiado', 'anterior': borrador.actividad,
                        'nuevo': nuevo_titulo, 'texto': 'Cambiar el título del APU',
                        'motivo': str(propuesta.get('motivo_titulo') or '')})
    nueva_unidad = ' '.join(str(propuesta.get('unidad') or '').split())[:20]
    if nueva_unidad and clave_texto(nueva_unidad) != clave_texto(borrador.unidad):
        cambios.append({'id': 'unidad', 'tipo': 'unidad', 'clase': 'cambiado', 'anterior': borrador.unidad,
                        'nuevo': nueva_unidad, 'texto': 'Cambiar la unidad del APU'})
    for tipo in ia.TIPOS_INSUMO:
        actuales = {_clave_fila(f): f for f in borrador.filas(tipo)}
        nuevas = {_clave_fila(f): f for f in (propuesta.get(tipo) or {}).get('filas', [])}
        campo = 'personas' if tipo == 'mano_obra' else 'cantidad'
        for k, f in nuevas.items():
            if k not in actuales:
                cambios.append({'id': f'{tipo}:+:{k}', 'tipo': tipo, 'clase': 'agregado', 'fila': f,
                                'texto': f'Agregar «{f["descripcion"]}»'})
            else:
                a = actuales[k]
                if any(numero(a.get(c)) != numero(f.get(c)) for c in (campo, 'desperdicio_pct') if c in f):
                    cambios.append({'id': f'{tipo}:~:{k}', 'tipo': tipo, 'clase': 'cambiado', 'fila': f, 'anterior': a,
                                    'texto': f'Cambiar «{f["descripcion"]}»'})
        for k, a in actuales.items():
            if k not in nuevas:
                cambios.append({'id': f'{tipo}:-:{k}', 'tipo': tipo, 'clase': 'quitado', 'fila': a,
                                'texto': f'Quitar «{a["descripcion"]}»'})
    nuevo_mo = propuesta.get('mano_obra') or {}
    for campo, etiqueta in (('rendimiento', 'el rendimiento'), ('horas_jornada', 'las horas de jornada')):
        antes, ahora = numero(borrador.mano_obra.get(campo)), numero(nuevo_mo.get(campo))
        if ahora is not None and antes != ahora:
            cambios.append({'id': f'mano_obra:r:{campo}', 'tipo': 'mano_obra', 'clase': 'cambiado', 'valor': str(ahora),
                            'campo': campo, 'texto': f'Cambiar {etiqueta}: {antes} → {ahora}'})
    return cambios


def con_ediciones(cambios, ediciones):
    """Copia de `cambios` con lo que la persona editó en la revisión (campos `ed:<id>:<campo>`). Un valor inválido deja
    el cambio con una clave `error` (con el valor escrito) en vez de lanzar: la página se vuelve a mostrar con el mensaje."""
    salida = []
    for original in cambios:
        c = copy.deepcopy(original)
        get = lambda campo: ediciones.get(f"ed:{c['id']}:{campo}")   # noqa: E731
        if c['id'] == 'actividad':
            v = get('valor')
            if v is not None:
                titulo = limpiar_titulo(v)
                c['nuevo'] = titulo or v
                if not titulo:
                    c['error'] = 'El título no puede quedar vacío.'
        elif c['id'] == 'unidad':
            v = get('valor')
            if v is not None:
                unidad = ' '.join(v.split())[:20]
                c['nuevo'] = unidad or v
                if not unidad:
                    c['error'] = 'La unidad no puede quedar vacía.'
        elif c.get('fila') is not None and c['clase'] != 'quitado':
            f = c['fila']
            if c['clase'] == 'agregado' and get('descripcion') is not None:
                f['descripcion'] = ' '.join(get('descripcion').split())[:200]
                if not f['descripcion']:
                    c['error'] = 'La descripción no puede quedar vacía.'
            campo = 'personas' if c['tipo'] == 'mano_obra' else 'cantidad'
            if get(campo) is not None:
                n = numero(get(campo))
                f[campo] = get(campo).strip()
                if n is None or n <= 0:
                    c['error'] = c.get('error') or ('Indica un número de personas mayor que cero.' if campo == 'personas' else 'Indica una cantidad mayor que cero.')
                else:
                    f[campo] = ia.texto_numero(n)
            if c['tipo'] == 'materiales' and get('desperdicio_pct') is not None:
                n = numero(get('desperdicio_pct'), Decimal(0))
                f['desperdicio_pct'] = get('desperdicio_pct').strip()
                if n is None or not 0 <= n <= 100:
                    c['error'] = c.get('error') or 'El desperdicio debe estar entre 0 y 100 %.'
                else:
                    f['desperdicio_pct'] = ia.texto_numero(n)
        elif 'valor' in c and get('valor') is not None:
            n = numero(get('valor'))
            c['valor'] = get('valor').strip()
            if n is None or n <= 0:
                c['error'] = 'Indica un número mayor que cero.'
            else:
                c['valor'] = ia.texto_numero(n)
        salida.append(c)
    return salida


def aplicar_cambios(borrador, propuesta, seleccionados, ediciones=None):
    """Aplica al borrador solo los cambios marcados. Las filas nuevas pasan por el vocabulario de la empresa."""
    por_id = {c['id']: c for c in con_ediciones(diferencias(borrador, propuesta), ediciones or {})}
    elegidos = [por_id[i] for i in seleccionados if i in por_id]
    for c in elegidos:
        if c.get('error'):
            raise ErrorPaso(f"{c['texto']}: {c['error']}")
    for c in elegidos:
        if c['id'] == 'actividad':
            borrador.actividad = c['nuevo']
        elif c['id'] == 'unidad':
            borrador.unidad = c['nuevo']
    for tipo in ia.TIPOS_INSUMO:
        filas = list(borrador.filas(tipo))
        for c in [c for c in elegidos if c['tipo'] == tipo and 'fila' in c]:
            clave = _clave_fila(c['fila'])
            if c['clase'] == 'quitado':
                filas = [f for f in filas if _clave_fila(f) != clave]
            elif c['clase'] == 'cambiado':
                filas = [{**f, **{k: v for k, v in c['fila'].items() if k in ('cantidad', 'personas', 'desperdicio_pct')}}
                         if _clave_fila(f) == clave else f for f in filas]
            else:
                nueva = dict(c['fila'], check=True)
                if nueva.get('codigo_subitem'):
                    sub = ItemModelo.objects.filter(empresa=borrador.empresa, codigo=nueva['codigo_subitem']).first()
                    if sub is None:
                        continue
                    nueva['subitem_id'] = sub.pk
                else:
                    nueva['insumo_id'] = resolver_insumo(borrador.empresa, tipo, nueva).pk
                filas.append(nueva)
        datos = dict(getattr(borrador, tipo) or {})
        datos['filas'] = filas
        for c in [c for c in elegidos if c['id'].startswith(f'{tipo}:r:')]:
            datos[c['campo']] = c['valor']
        setattr(borrador, tipo, datos)
    # Recalcula las horas por unidad de mano de obra con el rendimiento y las horas vigentes.
    mo = borrador.mano_obra or {}
    horas, rend = numero(mo.get('horas_jornada')), numero(mo.get('rendimiento'))
    if horas and rend:
        for f in mo.get('filas', []):
            f['cantidad'] = str((Decimal(f.get('personas') or 1) * horas / rend).quantize(Decimal('0.000001')))
    borrador.save()
