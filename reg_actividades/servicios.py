"""Motor de pasos: resuelve la plantilla de un registro, calcula el estado de cada paso y guarda sus datos."""
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from cuentas.capacidades import tiene_capacidad

from .models import DatoPaso, PasoAsignado, Plantilla
from .widgets import obtener
from .widgets.base import Contexto, _lleno


def plantilla_de(registro, clave):
    """Plantilla ACTIVA del tipo de registro para el tipo de proyecto del registro; si no hay, la general."""
    tipo = registro.proyecto.tipo_id if registro.proyecto_id else None
    base = Plantilla.objects.filter(empresa_id=registro.empresa_id, tipo_registro=clave, activa=True)
    return (base.filter(tipo_proyecto_id=tipo).first() if tipo else None) or base.filter(tipo_proyecto__isnull=True).first()


def asignados_de(registro, clave):
    """PasoAsignado de la plantilla del registro, en orden, con paso y widgets precargados."""
    plantilla = plantilla_de(registro, clave)
    if plantilla is None:
        return []
    return list(PasoAsignado.objects.filter(plantilla=plantilla).select_related('paso').prefetch_related('paso__widgets'))


FOTOS_SLUGS = ('camera_widget', 'camera_libro_widget', 'imgs_desc_widget')


def exige_metadatos(registro, clave, etapa):
    """True si el botón de fotos que gobierna `etapa` exige que cada foto traiga fecha y ubicación (EXIF), para
    rechazar las reenviadas por mensajería. La etapa efectiva de cada cámara se calcula como lo hace el widget
    (puede venir de `config['etapa']`). Las etapas sin botón detrás (`general`, hallazgos, verificaciones) → False."""
    for a in asignados_de(registro, clave):
        ctx = Contexto(registro=registro, paso=a.paso, clave=clave)
        for pw, w in widgets_de(a.paso):
            if pw.widget_slug in FOTOS_SLUGS and w.etapa(pw.config, ctx) == etapa and pw.config.get('exigir_metadatos'):
                return True
    return False


def minimo_fotos(registro, clave, etapa):
    """Mínimo de fotos que pide el botón que gobierna `etapa` (0 si no hay botón o no pide mínimo); para el contador
    «tomadas/mínimo» de la galería."""
    for a in asignados_de(registro, clave):
        ctx = Contexto(registro=registro, paso=a.paso, clave=clave)
        for pw, w in widgets_de(a.paso):
            if pw.widget_slug in FOTOS_SLUGS and w.etapa(pw.config, ctx) == etapa:
                return w.contexto({}, pw.config, ctx).get('minimo') or 0
    return 0


def descripciones_pedidas(registro, clave, etapa):
    """Descripciones que pide el widget de fotos con descripción que gobierna `etapa` ([] si no es de ese tipo)."""
    for a in asignados_de(registro, clave):
        ctx = Contexto(registro=registro, paso=a.paso, clave=clave)
        for pw, w in widgets_de(a.paso):
            if pw.widget_slug == 'imgs_desc_widget' and w.etapa(pw.config, ctx) == etapa:
                return w.descripciones(pw.config)
    return []


def _datos_por_paso(registro):
    ct = ContentType.objects.get_for_model(type(registro))
    return {d.paso_nombre: d for d in DatoPaso.objects.filter(content_type=ct, object_id=registro.pk)}


def widgets_de(paso):
    """[(PasoWidget, instancia)] del paso, ignorando los de tipo desconocido."""
    return [(pw, w) for pw in paso.widgets.all() if (w := obtener(pw.widget_slug)) is not None]


def nivel_paso(niveles, hay_datos):
    """Resumen de un paso a partir de los niveles de sus widgets OBLIGATORIOS (no marcados `opcional`):
    verde si todos están completos, rojo si ninguno tiene nada, amarillo en otro caso. Sin widgets obligatorios,
    verde si hay algún dato y rojo si no."""
    if not niveles:
        return 'verde' if hay_datos else 'rojo'
    if all(n >= 3 for n in niveles):
        return 'verde'
    return 'rojo' if all(n <= 1 for n in niveles) else 'amarillo'


def construir_paso(registro, clave, paso, dato, user, puede_escribir):
    """Widgets de un paso listos para pintar: config, datos, nivel y contexto de cada uno."""
    ctx = Contexto(registro=registro, paso=paso, clave=clave, user=user, puede_escribir=puede_escribir)
    datos = (dato.datos if dato else {}) or {}
    bloques, niveles, hay = [], [], False
    for pw, w in widgets_de(paso):
        d = datos.get(pw.widget_slug, {})
        nivel = w.nivel(d, pw.config, ctx)
        if not pw.config.get('opcional'):
            niveles.append(nivel)
        hay = hay or (not w.vacio(d) if w.guarda_datos else nivel > 1)
        bloques.append({'pw': pw, 'widget': w, 'nivel': nivel, 'plantilla': w.plantilla,
                        'datos': d, 'errores': [], **w.contexto(d, pw.config, ctx)})
    return bloques, nivel_paso(niveles, hay)


def resumen(registro, clave, user, puede_escribir):
    """Pasos de la plantilla del registro con su color, para la vista general."""
    datos = _datos_por_paso(registro)
    salida = []
    for a in asignados_de(registro, clave):
        bloques, color = construir_paso(registro, clave, a.paso, datos.get(a.paso.nombre), user, puede_escribir)
        salida.append({'paso': a.paso, 'color': color, 'n_widgets': len(widgets_de(a.paso)),
                       'botones': (botones := [_boton(b) for b in bloques]),
                       'con_imagenes': any(x['galeria'] for x in botones)})
    return salida


def contexto_pasos(request, registro, clave, escribe):
    """Contexto para pintar la línea de tiempo de pasos dentro de la pantalla del registro."""
    from reg_base import tipos
    return {'tipo': tipos.tipo(clave), 'pasos': resumen(registro, clave, request.user, escribe),
            'hay_plantilla': plantilla_de(registro, clave) is not None,
            'puede_configurar': tiene_capacidad(request.user, 'reg.config.manage', request.empresa)}


# Icono (components/icon.html) de cada tipo de widget, para el botón táctil de la vista de pasos.
ICONOS = {
    'camera_widget': 'camera', 'imgs_desc_widget': 'camera', 'camera_libro_widget': 'book',
    'ubicacion_widget': 'map-pin', 'mapa_1p': 'map-pin', 'mapa_2_puntos': 'desfase', 'distancia_widget': 'ruler',
    'lista_widget': 'list', 'comentario_widget': 'chat', 'form_dinamico_widget': 'clipboard',
    'poste_form_widget': 'clipboard', 'tabla_avance_widget': 'chart',
}


def _boton(b):
    """Botón de un componente del paso: color por estado (verde/amarillo/rojo; gris si es opcional y está vacío)."""
    nivel, opcional = b['nivel'], bool(b['pw'].config.get('opcional'))
    es_foto = b['pw'].widget_slug in ('camera_widget', 'camera_libro_widget', 'imgs_desc_widget')
    opcional = opcional or (es_foto and b.get('minimo') == 0)  # una cámara con mínimo 0 es opcional: gris si está vacía
    estado = 'opcional' if (opcional and nivel <= 1) else 'verde' if nivel >= 3 else 'amarillo' if nivel == 2 else 'rojo'
    total, minimo = b.get('total'), b.get('minimo')
    es_foto = b['pw'].widget_slug in ('camera_widget', 'camera_libro_widget', 'imgs_desc_widget')
    conteo = '' if total is None or not es_foto else (f'{total}/{minimo}' if minimo else str(total) if total else '')
    # Texto fijo en la esquina (p. ej. «Libro de Obras»): por configuración del botón o por tipo de widget.
    texto = b['pw'].config.get('insignia') or getattr(b['widget'], 'insignia_texto', '')
    slug = b['pw'].widget_slug
    # Icono: el de la configuración del botón (clave `icono`, p. ej. «drone»), si no el de su tipo de widget.
    icono = b['pw'].config.get('icono') or ICONOS.get(slug) or b['widget'].icono or 'clipboard'
    imagen = b.get('imagen')
    if slug == 'mapa_2_puntos' and imagen is not None and imagen.desfase_metros is not None:
        from reg_base.geo import formatear_distancia   # desfase ya guardado: la esquina del botón dice los metros (p. ej. «180 m»)
        conteo = formatear_distancia(imagen.desfase_metros)
    return {'slug': slug, 'galeria': b.get('etapa', '') if slug in FOTOS_SLUGS else '', 'icono': icono, 'estado': estado,
            'icono_clase': 'size-8' if icono in ('desfase', 'drone') else 'size-6',   # el desfase (dos marcadores y regla) necesita más tamaño para leerse
            'etiqueta': b.get('etiqueta') or b['widget'].nombre, 'insignia': texto or conteo,
            'insignia_texto': bool(texto), 'conteo': conteo}


@transaction.atomic
def guardar_paso(registro, paso, post, files, user=None, solo=None):
    """Valida los widgets que guardan datos (solo los de `solo`, si se indica) y persiste el paso. Devuelve (ok, errores_por_widget). Si algún widget
    falla no se guarda NADA (el usuario corrige y reenvía)."""
    ct = ContentType.objects.get_for_model(type(registro))
    dato, _ = DatoPaso.objects.get_or_create(
        empresa_id=registro.empresa_id, content_type=ct, object_id=registro.pk, paso_nombre=paso.nombre)
    nuevos, errores, por_persistir = dict(dato.datos or {}), {}, []
    from reg_base import tipos
    t = tipos.tipo_de_modelo(type(registro))
    for pw, w in widgets_de(paso):
        if not w.guarda_datos or (solo is not None and pw.widget_slug not in solo):
            continue   # `solo`: se guarda un componente suelto sin tocar los demás del paso
        contexto = Contexto(registro=registro, paso=paso, clave=t.clave if t else '', user=user, puede_escribir=True,
                            extra={'previos': (dato.datos or {}).get(pw.widget_slug, {})})
        datos, errs = w.leer(post, files, pw.config, contexto)
        if errs:
            errores[pw.widget_slug] = errs
        else:
            nuevos[pw.widget_slug] = datos
            por_persistir.append((w, datos, pw.config, contexto))
    if errores:
        transaction.set_rollback(True)
        return False, errores
    for w, datos, config, contexto in por_persistir:
        w.persistir(datos, config, contexto)
    dato.datos = nuevos
    dato.tiene_datos = any(_lleno(v) for bloque in nuevos.values() for v in bloque.values())
    dato.save()
    if t is not None:
        from . import mapas
        if t.clave in mapas.AUTOMATICOS:   # TX/TSS: sus mapas se generan solos en cuanto hay coordenadas
            transaction.on_commit(lambda: mapas.generar_automaticas(registro, t.clave))
        else:   # un mapa de 2 puntos que use este paso como origen se regenera si sus coordenadas cambiaron
            transaction.on_commit(lambda: mapas.regenerar_afectados(registro, t.clave, paso.nombre))
    return True, {}


# ── Configuración de ejemplo ──────────────────────────────────────────────────

# Plantilla de ítems «Torre estándar» del original (14 partidas; las incidencias suman 100).
PLANTILLA_TORRE = {'nombre': 'Torre estándar', 'partidas': [
    {'nombre': n, 'incidencia': i} for n, i in (
        ('Instalación de faenas', 5), ('Replanteo y Trazado', 5), ('Excavación para la fundación', 5),
        ('Enfierradura de la fundación', 15), ('Hormigonado de la fundación', 15), ('Relleno y compactado', 5),
        ('Montaje de la Torre', 15), ('Losa Radier de Equipos', 5), ('Cierre perimetral', 5),
        ('Sistema puesta a tierra', 5), ('Sistema Eléctrico', 5), ('Línea Eléctrica Provisoria', 5),
        ('Línea Eléctrica definitiva', 5), ('Trabajos Finales / Adicionales', 5))]}

def sembrar_ejemplo(empresa):
    """Crea (de forma idempotente) pasos y plantillas de ejemplo para TX/TSS y Construcción. Devuelve cuántos
    pasos y plantillas nuevos se crearon. La empresa los edita después a su medida."""
    from .models import Paso, PasoWidget, Plantilla

    pasos = {
        'sitio': ('Datos del sitio', 'Ubicación y registro fotográfico del sitio.', [
            ('ubicacion_widget', {'label': 'Ubicación GPS'}),
            ('camera_widget', {'label': 'Fotos del sitio', 'foto_min': 1}),
            ('comentario_widget', {'label': 'Comentarios'}),
        ]),
        'inspeccion': ('Inspección', 'Características de la estructura.', [
            ('form_dinamico_widget', {'label': 'Estructura', 'campos': (
                'tipo_estructura | text | Tipo de estructura | | *\n'
                'altura | number | Altura (m)\n'
                'estado | select | Estado | Bueno,Regular,Malo | *\n'
                'acceso_camion | toggle | Acceso para camión grúa')}),
        ]),
        # Construcción: mismos pasos y claves que reg.tekon-rl.cl (obra_objetivos…), para que los datos migrados encajen.
        'obra_objetivos': ('Actividades', 'Actividades inspeccionadas, fotos y libro de obras.', [
            ('lista_widget', {'label': 'Actividades inspeccionadas', 'placeholder': 'Ej.: Revisión de izaje y montaje de torre', 'max_items': 30}),
            ('camera_widget', {'label': 'Fotos', 'foto_min': 4}),
            ('camera_libro_widget', {'label': 'Libro de obras', 'foto_min': 0, 'etapa': 'obra_libro', 'opcional': True}),
        ]),
        'obra_avance': ('Ítems y avance', 'Avance por ítem de la obra.', [
            ('tabla_avance_widget', {'label': 'Avance por ítem', 'plantillas': [PLANTILLA_TORRE]}),
        ]),
        'obra_electrico': ('Eléctrico', 'Opcional: comentario y fotos de la parte eléctrica.', [
            ('comentario_widget', {'label': 'Eléctrico', 'opcional': True}),
            ('camera_widget', {'label': 'Fotos', 'foto_min': 0, 'opcional': True}),
        ]),
        'obra_comentarios': ('Comentarios y acciones', 'Observaciones y acciones de la visita.', [
            ('lista_widget', {'label': 'Comentarios y acciones', 'placeholder': 'Comentario o acción de la visita',
                              'max_items': 50, 'numerada': False}),
        ]),
    }
    plantillas = {
        ('txtss', 'TX/TSS (ejemplo)'): ['sitio', 'inspeccion'],
        ('construccion', 'Construcción (ejemplo)'): ['obra_objetivos', 'obra_avance', 'obra_electrico', 'obra_comentarios'],
    }
    nuevos_pasos = nuevas_plantillas = 0
    with transaction.atomic():
        objetos = {}
        for nombre, (titulo, descripcion, widgets) in pasos.items():
            paso, creado = Paso.objects.get_or_create(
                empresa=empresa, nombre=nombre, defaults={'titulo': titulo, 'descripcion': descripcion})
            nuevos_pasos += creado
            objetos[nombre] = paso
            if creado:
                for orden, (slug, config) in enumerate(widgets, start=1):
                    PasoWidget.objects.create(paso=paso, widget_slug=slug, orden=orden, config=config)
        for (clave, nombre), nombres in plantillas.items():
            existe = Plantilla.objects.filter(empresa=empresa, tipo_registro=clave, tipo_proyecto__isnull=True, activa=True).exists()
            if existe:
                continue
            plantilla = Plantilla.objects.create(empresa=empresa, nombre=nombre, tipo_registro=clave)
            nuevas_plantillas += 1
            for orden, n in enumerate(nombres, start=1):
                PasoAsignado.objects.create(plantilla=plantilla, paso=objetos[n], orden=orden)
    return nuevos_pasos, nuevas_plantillas


def pasos_obligatorios_completos(registro, clave, user=None):
    """True si la plantilla del registro tiene elementos obligatorios y TODOS están completos (nivel 3). Los marcados
    `opcional` no se exigen. Sin plantilla o sin elementos obligatorios, False."""
    datos = _datos_por_paso(registro)
    niveles = []
    for a in asignados_de(registro, clave):
        bloques, _color = construir_paso(registro, clave, a.paso, datos.get(a.paso.nombre), user, False)
        niveles += [b['nivel'] for b in bloques if not b['pw'].config.get('opcional')]
    return bool(niveles) and all(n >= 3 for n in niveles)
