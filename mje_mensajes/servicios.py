"""Reglas del chat. Es la ÚNICA puerta de escritura: las vistas y otros módulos pasan por aquí.

Visibilidad: General → toda la empresa · Proyecto → su equipo + quien tenga `mensajes.ver_todos_proyectos`
(coordinadores) · Directo → solo las dos personas.
No leídos: cada persona guarda hasta qué mensaje leyó (`Participacion.ultimo_leido`). Una conversación que
nunca abrió cuenta como leída hasta que llega algo nuevo (`enviar` crea la participación justo antes del mensaje).
"""
import hashlib
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Max, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from cuentas.capacidades import membresia_activa, tiene_capacidad, usuarios_con_capacidad
from cuentas.models import User
from notificaciones.services import notificar
from proyectos.models import Proyecto

from . import realtime
from .models import AdjuntoMensaje, Conversacion, Mensaje, Participacion

MAX_TEXTO = 4000
MAX_ADJUNTOS = 5
POR_PAGINA = 40
VER_TODOS = 'msj.ver_todos_proyectos'
_MENCION = re.compile(r'(?<![\w/.])@([\w.\-]+)')


class ErrorMensaje(Exception):
    """Mensaje que no se puede enviar (vacío, muy largo, adjunto inválido…); el texto es apto para el usuario."""


# ── Menciones ────────────────────────────────────────────────────────────────────────────────────

def handle(user):
    """Nombre con el que se menciona a alguien: la parte local de su correo, sin caracteres raros (ana@x.cl → ana)."""
    return re.sub(r'[^\w.\-]', '', (user.email or '').split('@')[0]).lower()


def handles_en(texto):
    """Conjunto de @nombres escritos en el texto (en minúsculas, sin el punto final de una frase)."""
    return {h.rstrip('.-').lower() for h in _MENCION.findall(texto or '') if h.rstrip('.-')}


# ── Quién ve qué ─────────────────────────────────────────────────────────────────────────────────

def _usuarios_activos(empresa):
    return User.objects.filter(is_active=True, membresias__empresa=empresa, membresias__activa=True).distinct()


def participantes(conv):
    """Usuarios que pueden leer la conversación (a ellos se les avisa y cuentan sus no leídos)."""
    if conv.tipo == Conversacion.Tipo.DIRECTO:
        return list(User.objects.filter(pk__in=[conv.directo_a_id, conv.directo_b_id], is_active=True))
    if conv.tipo == Conversacion.Tipo.GENERAL:
        return list(_usuarios_activos(conv.empresa))
    equipo = list(_usuarios_activos(conv.empresa).filter(membresias__proyectos=conv.proyecto_id))
    todos = {u.pk: u for u in equipo}
    for u in usuarios_con_capacidad(conv.empresa, VER_TODOS):
        todos.setdefault(u.pk, u)
    return list(todos.values())


def _en_equipo(user, proyecto_id):
    return Proyecto.objects.filter(pk=proyecto_id, equipo__user=user, equipo__activa=True).exists()


def puede_ver(user, conv):
    """¿Puede `user` leer y escribir en `conv`? (la empresa del request ya se validó al buscarla)."""
    if conv.tipo == Conversacion.Tipo.DIRECTO:
        return user.pk in (conv.directo_a_id, conv.directo_b_id)
    if not user.is_superuser and membresia_activa(user, conv.empresa_id) is None:
        return False
    if conv.tipo == Conversacion.Tipo.GENERAL:
        return True
    if conv.proyecto.is_deleted:
        return False
    return tiene_capacidad(user, VER_TODOS, conv.empresa) or _en_equipo(user, conv.proyecto_id)


def puede_ver_proyecto(user, empresa, proyecto):
    """¿Puede `user` abrir el canal de este proyecto? (sin crearlo; para decidir si se ofrece el botón)"""
    return tiene_capacidad(user, VER_TODOS, empresa) or _en_equipo(user, proyecto.pk)


def _filtro_visibles(user, empresa, prefijo=''):
    """Q sobre Conversacion (o sobre Mensaje con prefijo `conversacion__`) con lo que `user` puede ver."""
    q = Q(**{f'{prefijo}tipo': 'general'}) | (
        Q(**{f'{prefijo}tipo': 'directo'}) & (Q(**{f'{prefijo}directo_a': user}) | Q(**{f'{prefijo}directo_b': user})))
    proyectos = Q(**{f'{prefijo}tipo': 'proyecto', f'{prefijo}proyecto__is_deleted': False})
    if not tiene_capacidad(user, VER_TODOS, empresa):
        mios = Proyecto.objects.filter(equipo__user=user, equipo__activa=True)
        proyectos &= Q(**{f'{prefijo}proyecto__in': mios})
    return q | proyectos


# ── Conversaciones ───────────────────────────────────────────────────────────────────────────────

def general(empresa):
    return Conversacion.objects.get_or_create(empresa=empresa, tipo=Conversacion.Tipo.GENERAL)[0]


def de_proyecto(proyecto):
    return Conversacion.objects.get_or_create(
        proyecto=proyecto, tipo=Conversacion.Tipo.PROYECTO, defaults={'empresa_id': proyecto.empresa_id})[0]


def directo(empresa, user, otro):
    """El directo entre dos personas de la empresa (se crea la primera vez)."""
    if user.pk == otro.pk:
        raise ErrorMensaje('No puedes escribirte a ti mismo.')
    a, b = sorted((user, otro), key=lambda u: u.pk)
    return Conversacion.objects.get_or_create(
        empresa=empresa, tipo=Conversacion.Tipo.DIRECTO, directo_a=a, directo_b=b)[0]


def _contar_no_leidos(user, empresa, solo=None):
    """{conversacion_id: n} de mensajes ajenos posteriores a lo leído, en una sola consulta."""
    leido = Participacion.objects.filter(conversacion_id=OuterRef('conversacion_id'), user=user).values('ultimo_leido')[:1]
    tope = Mensaje.objects.filter(conversacion_id=OuterRef('conversacion_id')).order_by('-id').values('id')[:1]
    qs = Mensaje.objects.filter(conversacion__empresa=empresa).filter(_filtro_visibles(user, empresa, 'conversacion__'))
    if solo is not None:
        qs = qs.filter(conversacion_id__in=solo)
    filas = (qs.exclude(autor=user).annotate(leido=Coalesce(Subquery(leido), Subquery(tope)))
             .filter(id__gt=F('leido')).values('conversacion_id').annotate(n=Count('id')))
    return {f['conversacion_id']: f['n'] for f in filas}


def no_leidos(user, empresa):
    """(total, {conversacion_id: n}) para la barra superior."""
    por_conv = _contar_no_leidos(user, empresa)
    return sum(por_conv.values()), por_conv


def conversaciones_visibles(user, empresa):
    """Lista para el panel: General, proyectos y directos, cada una con `.no_leidos`, `.titulo_para` y
    `.ultimo` (último mensaje). Orden: con actividad reciente primero dentro de cada grupo."""
    gen = general(empresa)
    visibles = [p for p in Proyecto.objects.de_empresa(empresa).activos().order_by('nombre')
                if tiene_capacidad(user, VER_TODOS, empresa) or _en_equipo(user, p.pk)]
    existentes = {c.proyecto_id: c for c in Conversacion.objects.filter(
        empresa=empresa, tipo=Conversacion.Tipo.PROYECTO, proyecto__in=[p.pk for p in visibles])}
    faltan = [Conversacion(empresa=empresa, tipo=Conversacion.Tipo.PROYECTO, proyecto=p)
              for p in visibles if p.pk not in existentes]
    if faltan:
        Conversacion.objects.bulk_create(faltan, ignore_conflicts=True)
        existentes = {c.proyecto_id: c for c in Conversacion.objects.filter(
            empresa=empresa, tipo=Conversacion.Tipo.PROYECTO, proyecto__in=[p.pk for p in visibles])}
    proyectos = [existentes[p.pk] for p in visibles if p.pk in existentes]
    for c, p in zip(proyectos, [p for p in visibles if p.pk in existentes]):
        c.proyecto = p
    directos = list(Conversacion.objects.filter(
        Q(directo_a=user) | Q(directo_b=user), empresa=empresa, tipo=Conversacion.Tipo.DIRECTO,
    ).select_related('directo_a', 'directo_b'))
    todas = [gen, *proyectos, *directos]
    nl = _contar_no_leidos(user, empresa, solo=[c.pk for c in todas])
    ids_ultimos = list(Mensaje.objects.filter(conversacion__in=todas).values('conversacion_id')
                       .annotate(m=Max('id')).values_list('m', flat=True))
    ultimos = {m.conversacion_id: m for m in Mensaje.objects.filter(id__in=ids_ultimos).select_related('autor')}
    for c in todas:
        c.no_leidos = nl.get(c.pk, 0)
        c.titulo_para = c.titulo(user)
        c.otro_usuario = c.otro(user)
        c.ultimo = ultimos.get(c.pk)
    directos.sort(key=lambda c: c.ultimo_mensaje_en or c.creada, reverse=True)
    proyectos.sort(key=lambda c: (-(c.no_leidos > 0), -(c.ultimo_mensaje_en.timestamp() if c.ultimo_mensaje_en else 0),
                                  c.titulo_para.lower()))
    return {'general': gen, 'proyectos': proyectos, 'directos': directos, 'total': sum(nl.values())}


def marcar_leido(conv, user):
    """Marca como leída la conversación hasta su último mensaje y avisa a las otras pestañas de la persona."""
    ultimo = conv.mensajes.order_by('-id').values_list('id', flat=True).first() or 0
    Participacion.objects.update_or_create(conversacion=conv, user=user, defaults={'ultimo_leido': ultimo})
    realtime.leido(conv, user)
    return ultimo


# ── Enviar / editar / borrar ─────────────────────────────────────────────────────────────────────

def _validar_archivos(archivos):
    from tar_adjuntos.servicios import validar_subida
    if len(archivos) > MAX_ADJUNTOS:
        raise ErrorMensaje(f'Máximo {MAX_ADJUNTOS} archivos por mensaje.')
    for f in archivos:
        try:
            validar_subida(f)
        except ValidationError as exc:
            raise ErrorMensaje('; '.join(exc.messages)) from exc


def _guardar_adjunto(mensaje, archivo):
    from tar_adjuntos.servicios import nombre_seguro
    h = hashlib.sha256()
    for bloque in archivo.chunks():
        h.update(bloque)
    archivo.seek(0)
    nombre = nombre_seguro(archivo.name)
    adj = AdjuntoMensaje(mensaje=mensaje, nombre=nombre, sha256=h.hexdigest(), tamano=archivo.size or 0,
                         mime_type=(archivo.content_type or 'application/octet-stream')[:100])
    adj.archivo.save(nombre, archivo, save=False)
    adj.save()
    return adj


def _hay_sin_leer(conv, user, excepto):
    """¿Ya tenía `user` mensajes ajenos sin leer en `conv` antes de `excepto`? (para no avisar en cada mensaje)"""
    leido = Participacion.objects.filter(conversacion=conv, user=user).values_list('ultimo_leido', flat=True).first() or 0
    return conv.mensajes.filter(id__gt=leido).exclude(autor=user).exclude(pk=excepto.pk).exists()


def enviar(conv, autor, texto, archivos=()):
    """Guarda el mensaje (con sus adjuntos y menciones), avisa a quien corresponda y lo empuja en vivo."""
    texto = (texto or '').strip()
    archivos = list(archivos)
    if not texto and not archivos:
        raise ErrorMensaje('Escribe un mensaje o adjunta un archivo.')
    if len(texto) > MAX_TEXTO:
        raise ErrorMensaje(f'El mensaje supera los {MAX_TEXTO} caracteres.')
    _validar_archivos(archivos)
    with transaction.atomic():
        msg = Mensaje.objects.create(conversacion=conv, autor=autor, texto=texto)
        gente = participantes(conv)
        # Todos los que pueden verlo tienen participación: este mensaje queda sin leer para ellos.
        Participacion.objects.bulk_create(
            [Participacion(conversacion=conv, user=u, ultimo_leido=msg.pk - 1) for u in gente], ignore_conflicts=True)
        if autor is not None:
            Participacion.objects.update_or_create(conversacion=conv, user=autor, defaults={'ultimo_leido': msg.pk})
        pedidos = handles_en(texto)
        mencionados = [u for u in gente if autor is None or u.pk != autor.pk if handle(u) in pedidos]
        if mencionados:
            msg.menciones.set(mencionados)
        for f in archivos:
            _guardar_adjunto(msg, f)
        Conversacion.objects.filter(pk=conv.pk).update(ultimo_mensaje_en=msg.creado)
        _avisar(conv, msg, autor, gente, mencionados)
    realtime.mensaje_nuevo(conv, msg, [u.pk for u in gente])
    return msg


def _avisar(conv, msg, autor, gente, mencionados):
    """Campana: siempre a los mencionados; en un directo, al otro solo si era el primer mensaje sin leer."""
    url = f'/mensajes/?c={conv.pk}'
    quien = msg.nombre_autor
    resumen = (msg.texto[:100] + '…') if len(msg.texto) > 100 else (msg.texto or 'envió un archivo')
    vistos = set()
    for u in mencionados:
        notificar(u, conv.empresa, f'{quien} te mencionó en {conv.titulo(u)}: {resumen}', url=url, actor=autor)
        vistos.add(u.pk)
    if conv.tipo == Conversacion.Tipo.DIRECTO:
        for u in gente:
            if u.pk not in vistos and not _hay_sin_leer(conv, u, msg):
                notificar(u, conv.empresa, f'{quien}: {resumen}', url=url, actor=autor)


def editar(msg, texto):
    texto = (texto or '').strip()
    if not texto and not msg.adjuntos.exists():
        raise ErrorMensaje('El mensaje no puede quedar vacío.')
    if len(texto) > MAX_TEXTO:
        raise ErrorMensaje(f'El mensaje supera los {MAX_TEXTO} caracteres.')
    msg.texto, msg.editado = texto, timezone.now()
    msg.save(update_fields=['texto', 'editado'])
    msg.menciones.set([u for u in participantes(msg.conversacion)
                       if u.pk != msg.autor_id and handle(u) in handles_en(texto)])
    realtime.mensaje_cambio(msg.conversacion, msg.pk)
    return msg


def borrar(msg):
    conv, pk = msg.conversacion, msg.pk
    msg.delete()   # los archivos se borran con la señal post_delete
    realtime.mensaje_cambio(conv, pk)


def puede_moderar(user, msg):
    """Solo la autora o el autor edita o borra su propio mensaje."""
    return msg.autor_id is not None and msg.autor_id == user.pk


# ── Avisos del sistema (reemplazan a los de skyBot de la antigua bandeja) ────────────────────────

def aviso_sistema(empresa, user, texto, url=''):
    """Aviso automático a una persona: va a la campana de notificaciones."""
    return notificar(user, empresa, texto, url=url)


# ── Mención: a quién se puede mencionar / escribir ───────────────────────────────────────────────

def personas(empresa, user, conv=None, q=''):
    """Personas a las que se puede mencionar (participantes de `conv`) o escribir (toda la empresa)."""
    gente = participantes(conv) if conv is not None else list(_usuarios_activos(empresa))
    q = (q or '').strip().lower()
    salida = [u for u in gente if u.pk != user.pk and (
        not q or q in handle(u) or q in (u.get_full_name() or '').lower() or q in u.email.lower())]
    salida.sort(key=lambda u: (u.get_full_name() or u.email).lower())
    return salida[:20]
