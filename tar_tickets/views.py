import json
import logging
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import (Avg, Case, Count, DurationField, ExpressionWrapper, F, IntegerField, OuterRef, Q,
                              Subquery, Value, When)
from django.db.models.functions import TruncWeek
from django.http import (FileResponse, Http404, HttpResponse, HttpResponseBadRequest, HttpResponseNotModified,
                         JsonResponse)
from django.template.loader import render_to_string
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from empresas.acceso import acceso_modulo
from proyectos.models import Proyecto

from . import servicios as sv
from tar_adjuntos import servicios as adj
from tar_adjuntos.models import Adjunto

from .forms import ComentarioForm, TicketForm
from .models import Asignacion, Comentario, Etiqueta, Evento, Ticket

logger = logging.getLogger(__name__)
E = Ticket.Estado


def _empresa(request):
    empresa = getattr(request, 'empresa', None)
    if empresa is None:
        raise Http404
    return empresa


def _ticket(request, pk, qs=None):
    """Ticket `pk` DE LA EMPRESA del request, o 404: un id de otra empresa no existe para este
    usuario (ni siquiera con view_all)."""
    return get_object_or_404(qs if qs is not None else Ticket.objects, pk=pk, empresa=_empresa(request))


def _contexto_filtros(request):
    empresa = _empresa(request)
    return {
        'users': sv.personas_de_la_empresa(empresa),
        'projects': Proyecto.objects.de_empresa(empresa).activos(),
        'q': request.GET.get('q', ''),
        'assignee': request.GET.get('asignado', ''),
        'project': request.GET.get('proyecto', ''),
    }


# ── Tablero ───────────────────────────────────────────────────────────────────

def acceso_tareas(*capacidades):
    """Acceso a una vista del módulo Tareas (ver `empresas.acceso.acceso_modulo`)."""
    return acceso_modulo('tar', *capacidades)


@acceso_tareas()
def tablero(request):
    empresa = _empresa(request)
    ctx = sv.contexto_tablero(request)
    ctx.update({
        'filters': _contexto_filtros(request),
        'can_create': tiene_capacidad(request.user, 'tar.tickets.create', empresa),
        'status_legend': sv.leyenda_visibilidad(empresa),
        'show_status_legend': (tiene_capacidad(request.user, 'tar.tickets.assign', empresa)
                               or tiene_capacidad(request.user, 'tar.tickets.view_waiting', empresa)),
    })
    return render(request, 'tar_tickets/tablero.html', ctx)


@acceso_tareas()
def fragmento(request):
    return render(request, 'tar_tickets/parciales/_columnas.html', sv.contexto_tablero(request))


def _contexto_formulario(request, empresa, form):
    multiselects = []
    if 'ejecutores' in form.fields:
        multiselects = [
            (form['ejecutores'], 'Ejecutores (R)', 'No hay ejecutores registrados.'),
            (form['expertos'], 'Expertos (C)', 'No hay expertos registrados.'),
        ]
    return {
        'puede_gestionar_etiquetas': tiene_capacidad(request.user, 'tar.etiquetas.manage', empresa),
        'colores_etiqueta': Etiqueta.Color.choices,
        'multiselects': multiselects,
    }


# ── Crear / detalle ───────────────────────────────────────────────────────────

@acceso_tareas('tar.tickets.create')
@transaction.atomic
def crear(request):
    empresa = _empresa(request)
    puede_asignar = tiene_capacidad(request.user, 'tar.tickets.assign', empresa)
    form = TicketForm(request.POST or None, puede_asignar=puede_asignar, user=request.user, empresa=empresa)
    if request.method == 'POST' and form.is_valid():
        ticket = form.save(commit=False)
        ticket.creador = request.user
        ticket.empresa = empresa
        ticket.save()
        form.save_m2m()
        sv.registrar_evento(ticket, request.user, 'created', 'creó el ticket')
        if puede_asignar:
            # Con ejecutores en el mismo formulario el ticket pasa directo a «Por hacer»; sin ellos
            # queda en «Entrada».
            nuevos, _cons, _rem = sv.sincronizar_asignaciones(
                ticket, form.cleaned_data.get('ejecutores', []), form.cleaned_data.get('expertos', []),
            )
            sv.avisar(ticket, nuevos, request.user, 'te asignó')
        messages.success(request, f'{ticket.clave} creado.')
        return redirect('tar_tickets:detalle', pk=ticket.pk)
    return render(request, 'tar_tickets/formulario.html', {
        'form': form, 'creando': True, **_contexto_formulario(request, empresa, form),
    })


# ── Movimiento ────────────────────────────────────────────────────────────────

def _json(request):
    try:
        return json.loads(request.body)
    except ValueError:
        return None


@require_POST
@acceso_tareas('tar.tickets.move', 'tar.tickets.board_by_ticket')
def mover(request):
    """Mueve tarjetas de TICKET completo (tablero por ticket). Exige AMBAS capacidades: un ejecutor
    tiene `move` (para su tablero por subticket) pero no `board_by_ticket`, así que no toca tarjetas
    ajenas por aquí."""
    datos = _json(request)
    try:
        estado, orden = datos['status'], [int(i) for i in datos.get('order', [])]
    except (TypeError, KeyError, ValueError):
        return HttpResponseBadRequest('payload inválido')
    try:
        sv.mover_tickets(request.user, _empresa(request), estado, orden)
    except sv.ErrorDeMovimiento as exc:
        return HttpResponseBadRequest(str(exc))
    return JsonResponse({'ok': True})


@require_POST
@acceso_tareas('tar.tickets.move')
def mover_subticket(request):
    datos = _json(request)
    try:
        estado = datos['status']
        crudo = datos.get('assignments')
        if crudo is None:
            crudo = [datos['assignment']]
        if not isinstance(crudo, list) or not crudo:
            return HttpResponseBadRequest('payload inválido')
        ids = [int(i) for i in crudo]
    except (TypeError, KeyError, ValueError):
        return HttpResponseBadRequest('payload inválido')
    try:
        ticket = sv.mover_subtickets(request.user, _empresa(request), estado, ids)
    except sv.ErrorDeMovimiento as exc:
        return HttpResponseBadRequest(str(exc))
    return JsonResponse({'ok': True, 'parent_status': ticket.estado})


@require_POST
@acceso_tareas()
def concluir_subticket(request, pk):
    """Concluye el subticket PROPIO (la conclusión —texto o link— es opcional)."""
    conclusion = request.POST.get('conclusion', '').strip()
    with transaction.atomic():
        a = get_object_or_404(Asignacion, pk=pk, user=request.user, tipo=Asignacion.Tipo.EJECUTOR,
                              ticket__empresa=_empresa(request))
        a.ticket = sv.bloquear_ticket(a.ticket_id)
        a.refresh_from_db()
        if a.ticket.esta_suspendido:
            messages.error(request, 'El ticket está suspendido por el coordinador.')
            return redirect('tar_tickets:detalle', pk=a.ticket_id)
        sv.concluir_asignaciones(a, request.user, conclusion)
    messages.success(request, 'Subticket concluido. Pendiente de aprobación.' if a.ticket.tiene_subproductos
                     else 'Tarea concluida. Pendiente de aprobación.')
    return redirect('tar_tickets:tablero')


@require_POST
@acceso_tareas('tar.tickets.close')
def aprobar(request, pk):
    ticket, aprobadas = sv.aprobar(_ticket_visible(request, pk), request.user)
    if aprobadas:
        messages.success(request, f'{ticket.clave}: conclusión aprobada.')
    else:
        messages.info(request, 'No hay subtickets concluidos pendientes de aprobación.')
    return redirect('tar_tickets:detalle', pk=ticket.pk)


@require_POST
@acceso_tareas('tar.tickets.close')
def rechazar(request, pk):
    ticket = _ticket_visible(request, pk)
    try:
        ticket, rechazadas = sv.rechazar(ticket, request.user, request.POST.get('feedback', ''))
    except sv.ErrorDeMovimiento as exc:
        messages.error(request, str(exc))
        return redirect('tar_tickets:detalle', pk=pk)
    if rechazadas:
        messages.success(request, f'{ticket.clave}: conclusión rechazada; vuelve a «En progreso».')
    else:
        messages.info(request, 'No hay conclusiones pendientes de aprobación para rechazar.')
    return redirect('tar_tickets:detalle', pk=ticket.pk)


@require_POST
@acceso_tareas('tar.tickets.close')
def suspender(request, pk):
    ticket = _ticket_visible(request, pk)
    suspendido = sv.alternar_suspension(ticket, request.user)
    messages.success(request, f'{ticket.clave} ' + ('suspendido/cancelado.' if suspendido else 'reactivado.'))
    return redirect('tar_tickets:detalle', pk=ticket.pk)


# ── Detalle ───────────────────────────────────────────────────────────────────

# Tamaños de página del chat y la galería; el resto llega por fragmentos («cargar más»).
TAMANO_CHAT = 20
TAMANO_GALERIA = 18   # 3 filas de 6 columnas fijas
TAMANO_ARCHIVOS = 20
_CON_MINIATURA = Q(mime_type__startswith='image/') | Q(mime_type='application/pdf')


def _fmt_delta(delta):
    """timedelta → 'Xd Yh Zm' legible (None si no hay tiempo)."""
    if not delta:
        return None
    seg = int(delta.total_seconds())
    if seg <= 0:
        return None
    dias, resto = divmod(seg, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, _ = divmod(resto, 60)
    partes = []
    if dias:
        partes.append(f'{dias}d')
    if horas:
        partes.append(f'{horas}h')
    if minutos and not dias:
        partes.append(f'{minutos}m')
    return ' '.join(partes) or '0m'


def _transcurrido(a):
    if not a.iniciado_en:
        return None
    return _fmt_delta((a.cerrado_en or timezone.now()) - a.iniciado_en) or '0m'


def _adjuntos_del_chat(ticket):
    """Adjuntos de los mensajes del hilo (los del ticket sin mensaje van aparte)."""
    return Adjunto.objects.filter(ticket_id__in=ticket.ids_hilo(), comentario__isnull=False).select_related('subido_por')


@acceso_tareas()
def detalle(request, pk):
    empresa = _empresa(request)
    ticket = _ticket(request, pk, Ticket.objects.select_related('creador', 'proyecto', 'padre'))
    if not sv.puede_ver(request.user, ticket):
        raise PermissionDenied
    user = request.user
    hilo = ticket.ids_hilo()
    qs_chat = sv.comentarios_del_hilo(ticket)
    comentarios = list(qs_chat.order_by('-pk')[:TAMANO_CHAT])[::-1]
    for c in comentarios:
        c.heredado = c.ticket_id != ticket.pk
    mas_antiguo = comentarios[0].pk if comentarios else None
    hay_anteriores = bool(mas_antiguo) and qs_chat.filter(pk__lt=mas_antiguo).exists()

    base = _adjuntos_del_chat(ticket).order_by('-pk')
    miniaturas = list(base.filter(_CON_MINIATURA)[:TAMANO_GALERIA])
    archivos = list(base.exclude(_CON_MINIATURA)[:TAMANO_ARCHIVOS])
    pk_min = miniaturas[-1].pk if miniaturas else None
    pk_arch = archivos[-1].pk if archivos else None

    ejecutores = list(ticket.ejecutores.select_related('user'))
    expertos = list(ticket.expertos.select_related('user'))
    ahora = timezone.now()
    for a in ejecutores:
        a.transcurrido = _transcurrido(a)
        a.t_por_hacer = _fmt_delta(a.tiempo_en(E.POR_HACER, ahora))
        a.t_en_progreso = _fmt_delta(a.tiempo_en(E.EN_PROGRESO, ahora))
    mi_asignacion = next((a for a in ejecutores if a.user_id == user.id), None)

    puede_cerrar = tiene_capacidad(user, 'tar.tickets.close', empresa)
    pendiente = any(a.necesita_aprobacion for a in ejecutores)
    hijos = list(ticket.hijos.all())
    puede_crear = tiene_capacidad(user, 'tar.tickets.create', empresa)
    eventos = list(Evento.objects.filter(ticket_id__in=hilo).select_related('actor', 'ticket').order_by('-creado', '-pk'))
    for e in eventos:
        e.heredado = e.ticket_id != ticket.pk
    return render(request, 'tar_tickets/detalle.html', {
        't': ticket,
        'comentarios': comentarios,
        'hay_anteriores': hay_anteriores, 'mas_antiguo': mas_antiguo,
        'adj_miniaturas': miniaturas, 'adj_archivos': archivos,
        'hay_mas_miniaturas': bool(pk_min) and base.filter(_CON_MINIATURA, pk__lt=pk_min).exists(), 'pk_min': pk_min,
        'hay_mas_archivos': bool(pk_arch) and base.exclude(_CON_MINIATURA).filter(pk__lt=pk_arch).exists(), 'pk_arch': pk_arch,
        'adj_ticket': Adjunto.objects.filter(ticket=ticket, comentario__isnull=True),
        'eventos': eventos, 'hilo': hilo,
        'claves_padres': [t.clave for t in Ticket.objects.filter(pk__in=hilo[1:]).order_by('pk')],
        'hijos': hijos, 'hijos_divididos': any(c.es_parte_dividida for c in hijos),
        'ejecutores': ejecutores, 'expertos': expertos, 'mi_asignacion': mi_asignacion,
        'form_comentario': ComentarioForm(),
        'puede_escribir_chat': sv.puede_escribir_chat(user, ticket),
        'puede_moderar_chat': tiene_capacidad(user, 'tar.tickets.edit_any', empresa),
        'puede_editar': sv.puede_editar(user, ticket),
        'pendiente_aprobacion': pendiente,
        'padre_dividido': bool(ticket.es_parte_dividida or (ticket.padre_id and ticket.padre.esta_dividido)),
        'puede_dividir': puede_crear, 'puede_derivar': puede_crear,
        'puede_archivar': (sv.puede_archivar(user, ticket) and ticket.estado in (E.CONCLUIDO, E.SUSPENDIDO)
                           and not ticket.esta_archivado),
        'puede_aprobar': puede_cerrar and pendiente,
        'puede_suspender': puede_cerrar and ticket.estado != E.CONCLUIDO,
        'puede_concluir': bool(mi_asignacion and mi_asignacion.estado != E.CONCLUIDO and not ticket.esta_suspendido),
        'puede_cerrar': puede_cerrar,
    })


# ── Chat ──────────────────────────────────────────────────────────────────────

def _ticket_visible(request, pk):
    ticket = _ticket(request, pk)
    if not sv.puede_ver(request.user, ticket):
        raise PermissionDenied
    return ticket


@acceso_tareas()
def historial_chat(request, pk):
    """Los `TAMANO_CHAT` mensajes anteriores a `?before=<pk>` («Cargar mensajes anteriores»)."""
    ticket = _ticket_visible(request, pk)
    try:
        antes = int(request.GET.get('before', ''))
    except ValueError:
        return HttpResponseBadRequest('Falta o es inválido el parámetro «before».')
    qs = sv.comentarios_del_hilo(ticket)
    previos = list(qs.filter(pk__lt=antes).order_by('-pk')[:TAMANO_CHAT])[::-1]
    for c in previos:
        c.heredado = c.ticket_id != ticket.pk
    mas_antiguo = previos[0].pk if previos else None
    html = render_to_string('tar_tickets/parciales/_fragmento_mensajes.html', {
        'comentarios': previos, 'es_ultimo_lote': False,
        'puede_moderar_chat': tiene_capacidad(request.user, 'tar.tickets.edit_any', _empresa(request)),
    }, request=request)
    return JsonResponse({'ok': True, 'html': html, 'oldest': mas_antiguo,
                         'has_older': bool(mas_antiguo) and qs.filter(pk__lt=mas_antiguo).exists()})


@acceso_tareas()
def comentarios_desde(request, pk):
    """Mensajes posteriores a `?after=<pk>`, para agregarlos al chat en vivo."""
    ticket = _ticket_visible(request, pk)
    try:
        despues = int(request.GET.get('after', ''))
    except ValueError:
        return HttpResponseBadRequest('Falta o es inválido el parámetro «after».')
    nuevos = list(sv.comentarios_del_hilo(ticket).filter(pk__gt=despues).order_by('pk'))
    for c in nuevos:
        c.heredado = c.ticket_id != ticket.pk
    html = render_to_string('tar_tickets/parciales/_fragmento_mensajes.html', {
        'comentarios': nuevos, 'es_ultimo_lote': True,
        'puede_moderar_chat': tiene_capacidad(request.user, 'tar.tickets.edit_any', _empresa(request)),
    }, request=request)
    return JsonResponse({'ok': True, 'html': html})


@acceso_tareas()
def mas_adjuntos(request, pk):
    """Adjuntos del seguimiento anteriores a `?before=<pk>`; `?kind=thumbs|files` pagina cada tipo."""
    ticket = _ticket_visible(request, pk)
    tipo = request.GET.get('kind', 'thumbs')
    if tipo not in ('thumbs', 'files'):
        return HttpResponseBadRequest('Parámetro «kind» inválido.')
    try:
        antes = int(request.GET.get('before', ''))
    except ValueError:
        return HttpResponseBadRequest('Falta o es inválido el parámetro «before».')
    qs = _adjuntos_del_chat(ticket).filter(pk__lt=antes).order_by('-pk')
    qs = qs.filter(_CON_MINIATURA) if tipo == 'thumbs' else qs.exclude(_CON_MINIATURA)
    tam = TAMANO_GALERIA if tipo == 'thumbs' else TAMANO_ARCHIVOS
    previos = list(qs[:tam])
    mas_antiguo = previos[-1].pk if previos else None
    html = render_to_string('tar_tickets/parciales/_fragmento_galeria.html', {
        'adjuntos': previos, 'puede_escribir_chat': sv.puede_escribir_chat(request.user, ticket),
    }, request=request)
    return JsonResponse({'ok': True, 'html': html, 'oldest': mas_antiguo,
                         'has_more': bool(mas_antiguo) and qs.filter(pk__lt=mas_antiguo).exists()})


def _guardar_archivos(request, ticket, comentario):
    for f in request.FILES.getlist('files'):
        try:
            adj.guardar(f, autor=request.user, ticket=ticket, comentario=comentario)
        except adj.AdjuntoDuplicado:
            messages.info(request, f'«{f.name}» ya estaba adjunto (no se duplicó).')
        except ValidationError as exc:
            messages.error(request, f'{f.name}: {exc.messages[0]}')
        except Exception:
            logger.exception('No se pudo subir el adjunto %s', f.name)
            messages.error(request, f'No se pudo subir «{f.name}» (error de almacenamiento).')


@require_POST
@acceso_tareas()
def comentar(request, pk):
    ticket = _ticket(request, pk)
    if not sv.puede_escribir_chat(request.user, ticket):
        raise PermissionDenied
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    form = ComentarioForm(request.POST)
    if form.is_valid() and (form.cleaned_data['texto'].strip() or request.FILES):
        comentario = form.save(commit=False)
        comentario.ticket, comentario.autor = ticket, request.user
        comentario.texto = comentario.texto.strip()
        comentario.save()
        _guardar_archivos(request, ticket, comentario)
        sv.avisar_comentario(ticket, request.user)
        if ajax:
            comentario.heredado = False
            html = render_to_string('tar_tickets/parciales/_mensaje.html', {
                'c': comentario, 'es_ultimo': True,
                'puede_moderar_chat': tiene_capacidad(request.user, 'tar.tickets.edit_any', _empresa(request)),
            }, request=request)
            # Los avisos de _guardar_archivos (duplicado, error de subida) viajan como toasts en el JSON.
            avisos = [{'message': str(m), 'tag': m.level_tag} for m in messages.get_messages(request)]
            return JsonResponse({'ok': True, 'html': html, 'comment_id': comentario.pk, 'warnings': avisos})
    else:
        if ajax:
            return JsonResponse({'ok': False, 'error': 'El mensaje no puede estar vacío.'}, status=400)
        messages.error(request, 'El mensaje no puede estar vacío.')
    return redirect(f"{reverse('tar_tickets:detalle', args=[ticket.pk])}#chat-compose")


def _comentario(request, pk):
    return get_object_or_404(Comentario.objects.select_related('ticket'), pk=pk, ticket__empresa=_empresa(request))


@require_POST
@acceso_tareas()
def comentario_editar(request, pk):
    c = _comentario(request, pk)
    if not sv.puede_moderar_comentario(request.user, c):
        raise PermissionDenied
    texto = request.POST.get('texto', '').strip()
    if texto:
        c.texto = texto
        c.save(update_fields=['texto', 'actualizado'])
    return redirect('tar_tickets:detalle', pk=c.ticket_id)


@require_POST
@acceso_tareas()
def comentario_borrar(request, pk):
    c = _comentario(request, pk)
    if not sv.puede_moderar_comentario(request.user, c):
        raise PermissionDenied
    ticket_id = c.ticket_id
    try:
        c.delete()  # cascada: borra sus adjuntos (y sus archivos, por la señal post_delete)
    except Exception:
        logger.exception('No se pudo borrar el comentario %s', pk)
        messages.error(request, 'No se pudo borrar el mensaje (error de almacenamiento en sus adjuntos).')
    return redirect('tar_tickets:detalle', pk=ticket_id)


# ── Adjuntos ──────────────────────────────────────────────────────────────────

def _adjunto(request, pk):
    return get_object_or_404(Adjunto.objects.select_related('ticket', 'comentario'), pk=pk, empresa=_empresa(request))


@acceso_tareas()
def adjunto_servir(request, pk):
    a = _adjunto(request, pk)
    if not sv.puede_ver(request.user, a.ticket):
        raise PermissionDenied
    # El archivo es inmutable por versión (anotar crea una versión nueva), así que el sha256 es un ETag estable.
    etag = f'"{a.sha256}"' if a.sha256 else None
    if etag and request.headers.get('If-None-Match') == etag:
        return HttpResponseNotModified()
    try:
        archivo = a.archivo.open('rb')
    except Exception:
        raise Http404('No se pudo recuperar el archivo del almacenamiento.')
    mime = (a.mime_type or 'application/octet-stream').lower()
    # `inline` solo para tipos sin contenido activo; todo lo demás se descarga en vez de
    # renderizarse en el mismo origen con las cookies de sesión.
    respuesta = FileResponse(archivo, content_type=mime, as_attachment=mime not in adj.INLINE_SEGUROS, filename=a.nombre)
    respuesta['Content-Security-Policy'] = 'sandbox'  # defensa en profundidad ante contenido activo
    respuesta['Cache-Control'] = 'private, max-age=86400'  # pasó por un permiso por usuario: no cachear en proxies
    if etag:
        respuesta['ETag'] = etag
    return respuesta


@acceso_tareas()
def adjunto_miniatura(request, pk):
    a = _adjunto(request, pk)
    if not sv.puede_ver(request.user, a.ticket):
        raise PermissionDenied
    etag = f'"{a.sha256}"' if a.sha256 else None
    if etag and request.headers.get('If-None-Match') == etag:
        return HttpResponseNotModified()
    png = adj.miniatura(a)
    if not png:
        raise Http404('Sin miniatura.')
    respuesta = HttpResponse(png, content_type='image/png')
    respuesta['Cache-Control'] = 'private, max-age=86400'
    if etag:
        respuesta['ETag'] = etag
    return respuesta


@require_POST
@acceso_tareas()
def adjunto_borrar(request, pk):
    a = _adjunto(request, pk)
    if not sv.puede_escribir_chat(request.user, a.ticket):
        raise PermissionDenied
    if a.comentario_id:
        # Igual que el mensaje: solo su autor (o edit_any) y solo el último; los antiguos son inmutables.
        if not sv.puede_moderar_comentario(request.user, a.comentario):
            raise PermissionDenied
    elif a.subido_por_id != request.user.id and not tiene_capacidad(request.user, 'tar.tickets.edit_any', a.empresa_id):
        raise PermissionDenied
    try:
        a.delete()
    except Exception:
        logger.exception('No se pudo borrar el adjunto %s', pk)
        messages.error(request, 'No se pudo borrar el adjunto (error de almacenamiento).')
    return redirect('tar_tickets:detalle', pk=a.ticket_id)


@require_POST
@acceso_tareas()
def adjunto_anotar(request, pk):
    """Guarda una versión anotada de la imagen como un mensaje NUEVO del chat, a nombre de quien anota
    (no cuelga en silencio del mensaje original, que puede ser de otro usuario)."""
    a = _adjunto(request, pk)
    if not a.es_imagen:
        return HttpResponseBadRequest('Solo se pueden anotar imágenes.')
    if not sv.puede_escribir_chat(request.user, a.ticket):
        raise PermissionDenied
    png = request.FILES.get('image')
    if not png:
        return HttpResponseBadRequest('Falta la imagen anotada.')
    ticket = a.ticket
    try:
        with transaction.atomic():
            comentario = Comentario.objects.create(ticket=ticket, autor=request.user, texto='')
            nueva = adj.guardar_version(a, png=png.read(), autor=request.user, comentario=comentario)
    except adj.AdjuntoDuplicado:
        return JsonResponse({'ok': False, 'error': 'Esa versión ya existe.'}, status=409)
    except ValidationError as exc:
        return JsonResponse({'ok': False, 'error': exc.messages[0]}, status=400)
    except Exception:
        logger.exception('No se pudo guardar la anotación del adjunto %s', pk)
        return JsonResponse({'ok': False, 'error': 'No se pudo guardar la imagen: el almacenamiento no responde.'}, status=502)
    sv.avisar_comentario(ticket, request.user)
    return JsonResponse({'ok': True, 'id': nueva.pk})


# ── Editar / derivar / dividir / archivar ─────────────────────────────────────

@acceso_tareas()
def editar(request, pk):
    empresa = _empresa(request)
    ticket = _ticket(request, pk)
    if not sv.puede_editar(request.user, ticket):
        raise PermissionDenied
    puede_asignar = tiene_capacidad(request.user, 'tar.tickets.assign', empresa)
    form = TicketForm(request.POST or None, instance=ticket, puede_asignar=puede_asignar,
                      user=request.user, empresa=empresa)
    if request.method == 'POST' and form.is_valid():
        conservadas = sv.aplicar_edicion(ticket, form, request.user, puede_asignar=puede_asignar)
        if conservadas:
            nombres = ', '.join(sv.nombre_usuario(a.user) for a in conservadas)
            messages.warning(
                request,
                f'No se desasignó a {nombres}: su subticket tiene trabajo registrado (tiempos o conclusión). '
                'Si corresponde quitarlo igual, primero resuelve o reasigna ese trabajo.',
            )
        messages.success(request, f'{ticket.clave} actualizado.')
        return redirect('tar_tickets:detalle', pk=ticket.pk)
    return render(request, 'tar_tickets/formulario.html', {
        'form': form, 'creando': False, 't': ticket, **_contexto_formulario(request, empresa, form),
    })


@require_POST
@acceso_tareas('tar.tickets.create')
def derivar(request, pk):
    padre = _ticket_visible(request, pk)
    hijo = sv.derivar(padre, request.user)
    messages.success(request, f'{hijo.clave} creado (deriva de {padre.clave}). Completa los datos.')
    return redirect('tar_tickets:editar', pk=hijo.pk)


@require_POST
@acceso_tareas('tar.tickets.create')
def dividir(request, pk):
    padre = _ticket_visible(request, pk)
    hijo = sv.dividir(padre, request.user)
    messages.success(request, f'{hijo.clave} creado (parte idéntica de {padre.clave}).')
    return redirect('tar_tickets:tablero')


@require_POST
@acceso_tareas()
def archivar(request, pk):
    ticket = _ticket(request, pk)
    if not sv.puede_archivar(request.user, ticket):
        raise PermissionDenied
    if sv.archivar(ticket, request.user):
        messages.success(request, f'{ticket.clave} archivado.')
    else:
        messages.error(request, 'Solo se archivan tickets Concluidos o Suspendidos/Cancelados.')
    return redirect('tar_tickets:tablero')


@require_POST
@acceso_tareas('tar.tickets.unarchive')
def desarchivar(request, pk):
    ticket = _ticket_visible(request, pk)
    sv.desarchivar(ticket, request.user)
    messages.success(request, f'{ticket.clave} desarchivado.')
    return redirect('tar_tickets:archivados')


@require_POST
@acceso_tareas()
def eliminar(request, pk):
    """Borrado definitivo (BD + archivos adjuntos en cascada). Solo superusuario; los derivados
    sobreviven con padre=NULL (son trabajo real)."""
    if not request.user.is_superuser:
        raise PermissionDenied
    ticket = _ticket(request, pk)
    clave = ticket.clave
    try:
        ticket.delete()
    except Exception:
        # Almacenamiento caído: la señal de Adjunto propaga y Django revierte todo el borrado.
        logger.exception('No se pudo eliminar el ticket %s', clave)
        messages.error(request, f'No se pudo eliminar {clave} (error de almacenamiento al borrar sus adjuntos).')
        return redirect('tar_tickets:tablero')
    messages.success(request, f'{clave} eliminado definitivamente.')
    return redirect('tar_tickets:tablero')


# ── Listados ──────────────────────────────────────────────────────────────────

@acceso_tareas()
def archivados(request):
    empresa = _empresa(request)
    qs = (sv.tickets_visibles(request.user, empresa, incluir_archivados=True, incluir_divididos=True)
          .filter(archivado_en__isnull=False).order_by('-archivado_en'))
    return render(request, 'tar_tickets/archivados.html', {
        'pagina': Paginator(qs, 30).get_page(request.GET.get('page')),
        'puede_desarchivar': tiene_capacidad(request.user, 'tar.tickets.unarchive', empresa),
    })


_ORDEN_MIS_TICKETS = {
    # Sin vencimiento al final: no debe taparle el puesto a lo que sí tiene fecha o prioridad.
    'vence': [F('vence').asc(nulls_last=True), '-rango_prio', '-creado'],
    'prioridad': ['-rango_prio', F('vence').asc(nulls_last=True), '-creado'],
    'actividad': [F('ultimo_en').desc(nulls_last=True), '-actualizado'],
    'modificado': ['-actualizado'],
}


def _anotar_ultimo_mensaje(qs, desde=0):
    """Último (y opcionalmente el anterior) mensaje de cada ticket, por subconsulta."""
    ult = Comentario.objects.filter(ticket=OuterRef('pk')).order_by('-creado', '-pk')
    campos = {
        'ultimo_texto': Subquery(ult.values('texto')[:1]),
        'ultimo_en': Subquery(ult.values('creado')[:1]),
        'ultimo_autor': Subquery(ult.values('autor__first_name')[:1]),
        'ultimo_autor_ap': Subquery(ult.values('autor__last_name')[:1]),
        'ultimo_autor_mail': Subquery(ult.values('autor__email')[:1]),
    }
    if desde:
        campos.update({
            'previo_texto': Subquery(ult.values('texto')[1:2]),
            'previo_autor': Subquery(ult.values('autor__first_name')[1:2]),
            'previo_autor_ap': Subquery(ult.values('autor__last_name')[1:2]),
            'previo_autor_mail': Subquery(ult.values('autor__email')[1:2]),
        })
    return qs.annotate(**campos)


@acceso_tareas()
def mis_tickets(request):
    empresa, user = _empresa(request), request.user
    orden = request.GET.get('sort') if request.GET.get('sort') in _ORDEN_MIS_TICKETS else 'vence'
    qs = sv.aplicar_filtros(
        _anotar_ultimo_mensaje(
            Ticket.objects.filter(empresa=empresa).select_related('creador', 'proyecto')
            .filter(asignaciones__user=user, dividido_en__isnull=True)
            # Se excluye por la Asignación propia (no por Ticket.estado): un padre puede quedar
            # «Concluido» mientras el subticket propio sigue abierto (p. ej. tras derivar).
            .exclude(asignaciones__user=user, asignaciones__estado=E.CONCLUIDO, asignaciones__aprobado_en__isnull=False)
        ).annotate(rango_prio=Case(
            When(prioridad=Ticket.Prioridad.URGENTE, then=Value(4)),
            When(prioridad=Ticket.Prioridad.ALTA, then=Value(3)),
            When(prioridad=Ticket.Prioridad.MEDIA, then=Value(2)),
            default=Value(1), output_field=IntegerField(),
        )).prefetch_related('etiquetas', 'asignaciones__user').distinct(),
        request.GET,
    ).order_by(*_ORDEN_MIS_TICKETS[orden])
    pagina = Paginator(qs, 24).get_page(request.GET.get('page'))
    ahora = timezone.now()
    es_director = tiene_capacidad(user, 'tar.tickets.assign', empresa)
    for t in pagina:
        # La tarjeta refleja el avance PROPIO (su asignación), no el estado agregado del ticket.
        mia = next((a for a in t.asignaciones.all() if a.user_id == user.id), None)
        t.estado_visual = mia.estado if mia else t.estado
        t.estado_visual_label = Ticket.Estado(t.estado_visual).label
        t.pendiente_aprobacion = bool(mia) and mia.estado == E.CONCLUIDO and t.estado != E.CONCLUIDO
        t.mi_en_progreso = _fmt_delta(mia.tiempo_en(E.EN_PROGRESO, ahora)) if mia else None
        t.viewer_es_ejecutor = es_director and any(
            a.user_id == user.id and a.tipo == Asignacion.Tipo.EJECUTOR for a in t.asignaciones.all())
    return render(request, 'tar_tickets/mis_tickets.html', {'pagina': pagina, 'orden': orden})


@acceso_tareas('tar.chat.view_all')
def seguimiento(request):
    qs = _anotar_ultimo_mensaje(
        Ticket.objects.filter(empresa=_empresa(request)).select_related('creador', 'proyecto')
        # Archivados y contenedores divididos ya no son accionables.
        .filter(archivado_en__isnull=True, dividido_en__isnull=True).exclude(estado=E.ENTRADA),
        desde=1,
    ).prefetch_related('etiquetas').order_by('-actualizado')
    return render(request, 'tar_tickets/seguimiento.html', {
        'pagina': Paginator(qs, 25).get_page(request.GET.get('page')),
    })


@acceso_tareas('tar.dashboard.view')
def dashboard(request):
    from . import dashboard as datos
    empresa = _empresa(request)
    return render(request, 'tar_tickets/dashboard.html', {
        **datos.calcular(empresa), 'puede_crear': tiene_capacidad(request.user, 'tar.tickets.create', empresa),
    })


# ── Tipos de actividad (etiquetas) ────────────────────────────────────────────

@acceso_tareas('tar.etiquetas.manage')
def etiquetas(request):
    empresa = _empresa(request)
    colores = dict(Etiqueta.Color.choices)
    if request.method == 'POST':
        accion = request.POST.get('action')
        if accion == 'add':
            nombre = request.POST.get('name', '').strip()[:50]
            color = request.POST.get('color', Etiqueta.Color.NEUTRAL)
            if nombre and color in colores:
                _e, creada = Etiqueta.objects.get_or_create(empresa=empresa, nombre__iexact=nombre,
                                                            defaults={'nombre': nombre, 'color': color})
                messages.success(request, f'Tipo de actividad «{nombre}» creado.' if creada else 'Ya existía.')
        elif accion == 'delete':
            Etiqueta.objects.filter(pk=request.POST.get('id'), empresa=empresa).delete()
            messages.success(request, 'Tipo de actividad eliminado.')
        return redirect('tar_tickets:etiquetas')
    return render(request, 'tar_tickets/etiquetas.html', {
        'etiquetas': Etiqueta.objects.filter(empresa=empresa), 'colores': Etiqueta.Color.choices,
    })


@require_POST
@acceso_tareas('tar.etiquetas.manage')
def etiqueta_rapida(request):
    """Alta rápida desde el formulario de ticket (AJAX): crea o reutiliza y devuelve JSON."""
    nombre = request.POST.get('name', '').strip()[:50]
    color = request.POST.get('color', Etiqueta.Color.NEUTRAL)
    if not nombre or color not in dict(Etiqueta.Color.choices):
        return JsonResponse({'ok': False, 'error': 'Falta el nombre o el color no es válido.'}, status=400)
    etiqueta = Etiqueta.objects.filter(empresa=_empresa(request), nombre__iexact=nombre).first()
    creada = etiqueta is None
    if creada:
        etiqueta = Etiqueta.objects.create(empresa=_empresa(request), nombre=nombre, color=color)
    return JsonResponse({'ok': True, 'id': etiqueta.pk, 'name': etiqueta.nombre, 'color': etiqueta.color, 'created': creada})
