"""Menú por aplicaciones.

Cada módulo (Registros, Tareas, Asistencia) se presenta como una APLICACIÓN con su icono,
su color y su propia barra lateral. La cabecera trae un selector de aplicaciones y la barra
lateral muestra solo las entradas de la aplicación activa. «Inicio» es el menú principal de la
empresa: reúne toda su información (proyectos, usuarios, contratistas, roles y marca, según los
permisos). «Plataforma» (superusuario) queda fuera de las empresas: se entra por el menú de usuario
y solo aparece en el selector mientras se está en ella.

La aplicación activa se deduce del primer segmento de la ruta (sin el prefijo de empresa):
/registros/…, /tareas/…, /jornadas/…, /panel/…; cualquier otra (incluida /config/…) → «Inicio».

Cada módulo registra sus entradas (normalmente en `AppConfig.ready()`):

    registrar_item('tar', 'Tablero', 'tar_tickets:tablero', 'kanban', capacidad='tar.tickets.view_all')

Una aplicación de módulo está «disponible» si tiene al menos una entrada visible para el
usuario; si la empresa tiene el módulo pero aún no hay entradas, se muestra «Próximamente».
"""
from django.urls import NoReverseMatch, reverse

from cuentas.capacidades import tiene_capacidad

# El color de cada módulo (pastel fijo) vive en theme/static_src/src/styles.css: `.mod-chip` + `.mod-<código>`.
# El orden de este diccionario es el del selector de aplicaciones y el del lanzador de Inicio.
MODULOS = {
    'jor': dict(nombre='Asistencia', icono='clock', segmento='jornadas',   # la ruta /jornadas/ y el código `jor` no cambian
                descripcion='Control de asistencia: inicio y cierre de jornada, reportes diarios, ausencias y estadísticas del equipo.',
                clases='mod-chip mod-jor'),
    'reg': dict(nombre='Registros', icono='clipboard', segmento='registros',
                descripcion='Inspecciones y visitas de campo con fotos, mapas y reportes en PDF.',
                clases='mod-chip mod-reg'),
    'tar': dict(nombre='Tareas', icono='check-square', segmento='tareas',
                descripcion='Tablero de tickets con responsables, aprobación y seguimiento en tiempo real.',
                clases='mod-chip mod-tar'),
    'msj': dict(nombre='Mensajería', icono='chat', segmento='mensajes',
                descripcion='Chat del equipo: canal general, un canal por proyecto y mensajes directos, en tiempo real.',
                clases='mod-chip mod-msj',
                # No tiene páginas ni entradas de barra lateral: abre una ventana flotante sobre la pantalla actual.
                flotante=True, capacidad='msj.usar', accion='mensajeria', url_name='mje_mensajes:bandeja'),
    # Aún sin pantallas: el lanzador lo muestra como «Próximamente» (módulo activo sin entradas de menú).
    'apu': dict(nombre='APU IA', icono='calculator', segmento='apu', resalte='IA',
                descripcion='Análisis de Precios Unitarios con IA: costo de cada partida con materiales, mano de obra, equipos y rendimientos, calculado con inteligencia artificial.',
                clases='mod-chip mod-apu'),
}
SISTEMA = {
    'inicio': dict(nombre='Inicio', icono='home', clases='bg-base-300 text-base-content'),
    'plataforma': dict(nombre='Plataforma', icono='building', clases='bg-base-300 text-base-content'),
}
SEGMENTOS = {m['segmento']: codigo for codigo, m in MODULOS.items()}

_ITEMS = []  # dicts: modulo, nombre, url_name, icono, capacidad, orden


def registrar_item(modulo, nombre, url_name, icono, capacidad=None, orden=100, exacto=False,
                   solo_superusuario=False, por_tipo=False, seccion=None, activo_en=(), condicion=None):
    """`exacto=True`: la entrada solo se marca activa en su URL exacta (p. ej. el tablero, que es
    prefijo de las demás rutas del módulo). `solo_superusuario=True`: la entrada es de administración de la
    plataforma; se separa con una línea del resto del menú y solo la ve el superusuario. `por_tipo=True`: la
    entrada se desdobla en una por cada tipo de proyecto de la empresa («TX/TSS Poste», «TX/TSS Torre»…), que
    abre la lista con `?tipo=<id>`; si la empresa no definió tipos, queda la entrada única.
    `capacidad` puede ser una tupla: basta con tener cualquiera. `seccion`: encabezado bajo el que se agrupa
    la entrada en la barra lateral (las entradas sin sección van primero, sin encabezado; el orden lo da `orden`).
    `activo_en`: url_names adicionales cuyas rutas también marcan activa esta entrada (p. ej. las pestañas).
    `condicion`: `fn(request) -> bool`; la entrada solo se muestra si devuelve True (p. ej. que la empresa tenga
    activo un tipo de registro)."""
    _ITEMS.append(dict(modulo=modulo, nombre=nombre, url_name=url_name, icono=icono, capacidad=capacidad,
                       orden=orden, exacto=exacto, solo_superusuario=solo_superusuario, por_tipo=por_tipo,
                       seccion=seccion, activo_en=tuple(activo_en), condicion=condicion))


def _terminos(texto, empresa):
    """Sustituye los términos propios de la empresa en nombres de menú: «{proyectos}» y «{certificado}»."""
    return texto.replace('{proyectos}', empresa.termino_proyecto_plural).replace('{certificado}', empresa.nombre_certificado)


def _url(url_name):
    try:
        return reverse(url_name)
    except NoReverseMatch:
        return None


def _item(request, nombre, url_name, icono, exacto=False, grupo='general', seccion='', activo_en=()):
    url = _url(url_name)
    if url is None:
        return None
    activo = request.path == url if exacto else request.path.startswith(url)
    activo = activo or any(u and request.path.startswith(u) for u in map(_url, activo_en))
    return {'nombre': nombre, 'url': url, 'icono': icono, 'activo': activo, 'grupo': grupo, 'seccion': seccion or ''}


def app_activa_codigo(request):
    primero = request.path_info.lstrip('/').split('/', 1)[0]
    if primero == 'proyectos':
        return 'inicio'
    if primero in SEGMENTOS:
        return SEGMENTOS[primero]
    return 'plataforma' if primero == 'panel' else 'inicio'


def _permitido(user, capacidad, empresa):
    if capacidad is None:
        return True
    if isinstance(capacidad, (tuple, list)):
        return any(tiene_capacidad(user, c, empresa) for c in capacidad)
    return tiene_capacidad(user, capacidad, empresa)


def _items_modulo(request, codigo):
    user, empresa = request.user, request.empresa
    visibles = [i for i in _ITEMS if i['modulo'] == codigo
                and (not i.get('solo_superusuario') or user.is_superuser)
                and (i.get('condicion') is None or i['condicion'](request))
                and _permitido(user, i['capacidad'], empresa)]
    # Primero las entradas generales y al final las de superusuario (el menú las separa con una línea).
    visibles.sort(key=lambda i: (bool(i.get('solo_superusuario')), i['orden']))
    salida = []
    for i in visibles:
        tipos = list(empresa.tipos_proyecto.all()) if i.get('por_tipo') else []
        if not tipos:
            item = _item(request, _terminos(i['nombre'], empresa), i['url_name'], i['icono'], exacto=i.get('exacto', False),
                         grupo='superusuario' if i.get('solo_superusuario') else 'general',
                         seccion=_terminos(i.get('seccion') or '', empresa),
                         activo_en=i.get('activo_en', ()))
            if item:
                salida.append(item)
            continue
        base = _url(i['url_name'])
        if base is None:
            continue
        elegido = request.GET.get('tipo', '')
        for t in tipos:
            salida.append({'nombre': f"{i['nombre']} {t.nombre}", 'url': f'{base}?tipo={t.pk}', 'icono': i['icono'],
                           'activo': request.path.startswith(base) and elegido == str(t.pk), 'grupo': 'general',
                           'seccion': i.get('seccion') or ''})
    return salida


def _items_config(request):
    """Entradas de configuración de la empresa, agrupadas en secciones del menú lateral."""
    user, empresa = request.user, request.empresa
    candidatos = []
    if tiene_capacidad(user, 'cuentas.usuarios.manage', empresa):
        candidatos.append(('Usuarios', 'panel:miembros', 'users', False, 'general', 'Usuarios y accesos'))
        candidatos.append(('Sedes', 'panel:sedes', 'map-pin', False, 'general', 'Usuarios y accesos'))
        candidatos.append(('Alta por dominio', 'panel:acceso', 'lock', False, 'general', 'Usuarios y accesos'))
    if tiene_capacidad(user, 'cuentas.roles.manage', empresa):
        candidatos.append(('Cargos y permisos', 'panel:roles', 'shield', False, 'general', 'Usuarios y accesos'))
    if tiene_capacidad(user, 'empresas.marca.manage', empresa):
        candidatos.append(('Marca', 'panel:marca', 'palette', False, 'general', 'Empresa'))
    return [x for x in (_item(request, *c) for c in candidatos) if x]


def _items_plataforma(request):
    # La lista de empresas vive en /panel/, prefijo de todas las demás rutas de plataforma: solo se marca en su URL
    # exacta y en las de crear/editar empresa (/panel/empresas/…).
    empresas = _item(request, 'Empresas', 'panel:empresas', 'building', exacto=True)
    if empresas and request.path.startswith(empresas['url'] + 'empresas/'):
        empresas['activo'] = True
    candidatos = [('Administradores', 'panel:administradores', 'shield'), ('Almacenamiento', 'panel:almacenamiento', 'database')]
    return [x for x in [empresas, *(_item(request, *c) for c in candidatos)] if x]


def construir_menu(request):
    """{'apps': [...], 'app_activa': {...}, 'items': [...]} para el usuario y la empresa del request."""
    user = request.user
    empresa = getattr(request, 'empresa', None)
    activa = app_activa_codigo(request)
    apps, items_por_app = [], {}

    def agregar(codigo, meta, items, url, disponible=True, nivel='todos'):
        # nivel: quién accede → 'todos' · 'coordinadores' · 'superusuario'; el selector separa los grupos con una línea
        items_por_app[codigo] = items
        apps.append({'nivel': nivel,
            'codigo': codigo, 'nombre': meta['nombre'], 'icono': meta['icono'], 'clases': meta['clases'],
            'url': url, 'disponible': disponible, 'activa': codigo == activa,
        })

    if empresa is not None:
        inicio = _item(request, 'Módulos', 'home', 'home', exacto=True)
        items_inicio = [inicio] if inicio else []
        if tiene_capacidad(user, 'proyectos.view', empresa):
            proyectos = _item(request, empresa.termino_proyecto_plural, 'proyectos:lista', 'folder')
            if proyectos:
                items_inicio.append(proyectos)
        if tiene_capacidad(user, 'empresas.contratistas.manage', empresa):
            contratistas = _item(request, 'Contratistas', 'panel:contratistas', 'hardhat')
            if contratistas:
                items_inicio.append(contratistas)
        items_inicio += _items_config(request)
        agregar('inicio', SISTEMA['inicio'], items_inicio, inicio['url'] if inicio else '#')
        for codigo, meta in MODULOS.items():
            if not empresa.tiene_modulo(codigo) or meta.get('flotante'):
                continue
            items = _items_modulo(request, codigo)
            if not items and any(i['modulo'] == codigo for i in _ITEMS):
                continue  # el módulo tiene entradas pero ninguna para este usuario
            agregar(codigo, meta, items, items[0]['url'] if items else '#', disponible=bool(items))
    if user.is_superuser and (empresa is None or activa == 'plataforma'):
        plataforma = _items_plataforma(request)
        if plataforma:
            agregar('plataforma', SISTEMA['plataforma'], plataforma, plataforma[0]['url'], nivel='superusuario')

    activa_app = next((a for a in apps if a['activa']), None)
    return {
        'apps': apps,
        'app_activa': activa_app,
        'items': items_por_app.get(activa_app['codigo'], []) if activa_app else [],
    }


def construir_lanzador(request, apps):
    """Todos los módulos SIEMPRE, cada uno con su estado para la empresa y el usuario:
    disponible | proximamente (activo, sin pantallas aún) | sin_acceso | no_habilitado."""
    empresa = getattr(request, 'empresa', None)
    por_codigo = {a['codigo']: a for a in apps}
    tarjetas = []
    for codigo, meta in MODULOS.items():
        app = por_codigo.get(codigo)
        if empresa is None or not empresa.tiene_modulo(codigo):
            estado = 'no_habilitado'
        elif meta.get('flotante'):
            estado = 'disponible' if tiene_capacidad(request.user, meta['capacidad'], empresa) else 'sin_acceso'
        elif app is None:
            estado = 'sin_acceso'
        else:
            estado = 'disponible' if app['disponible'] else 'proximamente'
        tarjetas.append({
            'codigo': codigo, 'nombre': meta['nombre'], 'icono': meta['icono'], 'clases': meta['clases'],
            'descripcion': meta['descripcion'], 'estado': estado,
            # `resalte`: parte final del nombre que la tarjeta destaca (p. ej. «con IA»); `nombre_base` es el resto.
            'resalte': meta.get('resalte', ''), 'nombre_base': meta['nombre'].removesuffix(meta.get('resalte', '')).rstrip(),
            # `accion`: la tarjeta no navega, abre la ventana flotante (el href queda como respaldo sin JS).
            'accion': meta.get('accion', '') if estado == 'disponible' else '',
            'url': (_url(meta['url_name']) if meta.get('flotante') else app['url']) if estado == 'disponible' else '',
        })
    return tarjetas


def menu_lateral(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    menu = construir_menu(request)
    return {
        'apps_menu': menu['apps'], 'app_activa': menu['app_activa'], 'menu_lateral': menu['items'],
        'lanzador_modulos': construir_lanzador(request, menu['apps']),
    }
