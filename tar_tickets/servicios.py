"""Reglas de visibilidad, columnas del tablero y asignaciones del módulo Tareas.

Todo está acotado a la EMPRESA del request: un ticket de otra empresa no existe para el
usuario, ni siquiera con `tar.tickets.view_all` (ese alcance es su empresa).
"""
from django.contrib.auth import get_user_model
from django.db.models import Count, Q

from cuentas import capacidades
from cuentas.capacidades import tiene_capacidad
from cuentas.roles import RolBase

from .models import Asignacion, Evento, Ticket

User = get_user_model()
E = Ticket.Estado


def registrar_evento(ticket, actor, tipo, detalle='', asignacion=None):
    """Agrega una entrada al historial del ticket (y, más adelante, emite el cambio en vivo)."""
    evento = Evento.objects.create(ticket=ticket, actor=actor, tipo=tipo, detalle=detalle, asignacion=asignacion)
    return evento


def nombre_usuario(u):
    return u.get_full_name().strip() or u.email


# ── Visibilidad ───────────────────────────────────────────────────────────────

def puede_ver(user, ticket):
    empresa = ticket.empresa_id
    if tiene_capacidad(user, 'tar.tickets.view_all', empresa) or tiene_capacidad(user, 'tar.chat.view_all', empresa):
        return True
    return ticket.creador_id == user.id or ticket.es_participante(user)


def puede_escribir_chat(user, ticket):
    return tiene_capacidad(user, 'tar.chat.write', ticket.empresa_id) and puede_ver(user, ticket)


def tickets_visibles(user, empresa, incluir_archivados=False, incluir_divididos=False):
    """Tickets de `empresa` que `user` puede ver: todos (view_all) o solo los que creó o donde
    participa. Siempre acotado a la empresa."""
    qs = (Ticket.objects.filter(empresa=empresa)
          .select_related('creador', 'proyecto', 'padre')
          .prefetch_related('asignaciones', 'asignaciones__user'))
    if not incluir_archivados:
        qs = qs.filter(archivado_en__isnull=True)
    if not incluir_divididos:
        # Un ticket dividido es un contenedor: ya no es accionable; solo se ven sus partes.
        qs = qs.filter(dividido_en__isnull=True)
    if tiene_capacidad(user, 'tar.tickets.view_all', empresa):
        return qs
    return qs.filter(Q(creador=user) | Q(asignaciones__user=user)).distinct()


def aplicar_filtros(qs, params):
    """Filtros de querystring: búsqueda (q), asignado y proyecto."""
    q = params.get('q', '').strip()
    if q:
        qs = qs.filter(Q(titulo__icontains=q) | Q(descripcion__icontains=q)
                       | Q(codigo__icontains=q) | Q(solicitante__icontains=q))
    if params.get('asignado', '').isdigit():
        qs = qs.filter(asignaciones__user_id=params['asignado']).distinct()
    if params.get('proyecto', '').isdigit():
        qs = qs.filter(proyecto_id=params['proyecto'])
    return qs


def personas_de_la_empresa(empresa):
    """Usuarios activos con membresía activa en la empresa."""
    return (User.objects.filter(is_active=True, membresias__empresa=empresa, membresias__activa=True)
            .distinct().order_by('email'))


# ── Columnas del tablero ──────────────────────────────────────────────────────

def estados_visibles(user, empresa):
    """Columnas del tablero para `user`: «Entrada» solo con `view_backlog` y «Suspendido/
    Cancelado» solo con `view_waiting`."""
    ocultos = set()
    if not tiene_capacidad(user, 'tar.tickets.view_backlog', empresa):
        ocultos.add(E.ENTRADA)
    if not tiene_capacidad(user, 'tar.tickets.view_waiting', empresa):
        ocultos.add(E.SUSPENDIDO)
    return [(v, l) for v, l in E.choices if v not in ocultos]


def leyenda_visibilidad(empresa):
    """Para el botón «?» del tablero: qué columnas ve cada rol de la empresa, agrupando los roles
    que ven el mismo rango. Se calcula por rol (capacidades efectivas de la matriz), no por usuario."""
    estados = list(E.choices)
    grupos = {}
    for rol in empresa.roles.filter(activo=True).order_by('orden'):
        if rol.rol_base == RolBase.OBSERVADOR:
            continue  # observador: no figura ante los demás roles (igual que el «Administrador» de skydesk)
        efectivas = capacidades._conjunto_rol(rol)
        ocultos = set()
        if 'tar.tickets.view_backlog' not in efectivas:
            ocultos.add(E.ENTRADA)
        if 'tar.tickets.view_waiting' not in efectivas:
            ocultos.add(E.SUSPENDIDO)
        idx = [i for i, (v, _l) in enumerate(estados) if v not in ocultos]
        if idx:
            grupos.setdefault((min(idx), max(idx)), []).append(rol.nombre)
    filas = [{'label': ' / '.join(n), 'start': a, 'end': b} for (a, b), n in grupos.items()]
    filas.sort(key=lambda f: (f['start'], -(f['end'] - f['start'])))
    return {'statuses': estados, 'rows': filas}


def numero_base(ticket):
    """Número del código (EMBOL-0014-1-1 → 14): agrupa un ticket con TODAS sus partes bajo el
    mismo número, en vez de por el pk de cada hijo."""
    partes = (ticket.codigo or '').split('-')
    if len(partes) >= 2 and partes[1].isdigit():
        return int(partes[1])
    return ticket.pk


def tarjetas_subticket(visibles, estados, *, viewer, movible=False):
    """Agrupa Asignaciones en columnas por estado, fusionando 2+ subtickets del mismo ticket que
    caen en la misma columna en una sola tarjeta (evita «mi card» + fantasma casi idénticas).

    `viewer` = el ejecutor logueado: marca `es_fantasma` en los subtickets ajenos. `viewer=None`
    = vista del director (ve TODOS sin fantasmas; `vista_ajena=True`). Con `movible=True` esas
    tarjetas se arrastran; si no, quedan `solo_lectura`.

    Devuelve {estado: [entradas]}; cada entrada es {'type': 'subticket', 'a': a} o
    {'type': 'merged', ...}."""
    for a in visibles:
        a.es_fantasma = viewer is not None and a.user_id != viewer.id
    # Mismo color para todas las tarjetas del mismo ticket, solo si quedan repartidas en
    # columnas distintas. Hash de Knuth sobre el id para que pks consecutivos no caigan
    # en tonos adyacentes (8 variantes).
    estados_por_ticket = {}
    for a in visibles:
        estados_por_ticket.setdefault(a.ticket_id, set()).add(a.estado)
    for a in visibles:
        a.color_vinculo = ((a.ticket_id * 2654435761) & 0xFFFFFFFF) % 8 \
            if len(estados_por_ticket[a.ticket_id]) > 1 else None
    por_estado = {}
    for valor, _label in estados:
        items = [a for a in visibles if a.estado == valor]
        items.sort(key=lambda a: (a.es_fantasma, a.posicion, numero_base(a.ticket)))
        por_ticket = {}
        for a in items:
            por_ticket.setdefault(a.ticket_id, []).append(a)
        entradas, fusionados = [], set()
        for a in items:
            grupo = por_ticket[a.ticket_id]
            if len(grupo) > 1:
                if a.ticket_id in fusionados:
                    continue
                fusionados.add(a.ticket_id)
                mia = next((x for x in grupo if viewer is not None and x.user_id == viewer.id), None)
                entradas.append({
                    'type': 'merged', 'ticket': a.ticket, 'group': grupo, 'link_color': a.color_vinculo,
                    'is_locked': a.bloqueado, 'my_assignment': mia, 'others_view': viewer is None,
                    'is_readonly': viewer is None and not movible,
                    'is_muted': getattr(a, 'atenuado', False),
                    'pending_approval': any(x.estado == E.CONCLUIDO and not x.aprobado_en for x in grupo),
                    'viewer_is_executor': any(getattr(x, 'viewer_es_ejecutor', False) for x in grupo),
                })
            else:
                a.vista_ajena = viewer is None
                a.solo_lectura = viewer is None and not movible
                entradas.append({'type': 'subticket', 'a': a})
        por_estado[valor] = entradas
    return por_estado


def columnas_por_ticket(request):
    """Vista del coordinador/especialista/observador: tarjetas = tickets (estado agregado), salvo los
    de subproductos, que se muestran por subticket (un estado agregado no puede reflejar «alguien
    concluyó pero no todos» sin ocultar ese progreso)."""
    user, empresa = request.user, request.empresa
    tickets = list(aplicar_filtros(tickets_visibles(user, empresa), request.GET).annotate(
        num_comments=Count('comentarios', distinct=True),
        num_children=Count('hijos', distinct=True),
    ).prefetch_related('etiquetas', 'asignaciones__user', 'hijos', 'padre__hijos'))
    # El director (assign) ve todo, pero primero lo propio; el resto con la tarjeta apagada.
    resaltar_propios = tiene_capacidad(user, 'tar.tickets.assign', empresa)
    puede_editar = tiene_capacidad(user, 'tar.tickets.edit_any', empresa)
    entradas, asignaciones_sub = [], []
    for t in tickets:
        ejec = [a for a in t.asignaciones.all() if a.tipo == Asignacion.Tipo.EJECUTOR]
        viewer_es_ejec = resaltar_propios and any(a.user_id == user.id for a in ejec)
        participante = any(a.user_id == user.id for a in t.asignaciones.all())
        if t.tiene_subproductos and ejec:
            atenuado = resaltar_propios and not (t.creador_id == user.id or participante)
            for a in ejec:
                a.ticket = t  # evita relanzar la query (asignaciones ya viene prefetched)
                a.bloqueado = bool(t.suspendido_en)
                a.atenuado = atenuado
                a.viewer_es_ejecutor = resaltar_propios and a.user_id == user.id
                asignaciones_sub.append(a)
            continue
        # Todos los ejecutores concluyeron pero falta la aprobación: el ticket sigue «En progreso»
        # (recalcular_estado) pero visualmente ya está «Concluido».
        t.pendiente_aprobacion = bool(ejec) and all(a.estado == E.CONCLUIDO for a in ejec) and t.estado != E.CONCLUIDO
        t.estado_visual = E.CONCLUIDO if t.pendiente_aprobacion else t.estado
        t.puede_archivar = (
            (puede_editar or t.creador_id == user.id or participante)
            and t.estado in (E.CONCLUIDO, E.SUSPENDIDO) and not t.esta_archivado
        )
        if resaltar_propios:
            t.atenuado = not (t.creador_id == user.id or participante)
        t.viewer_es_ejecutor = viewer_es_ejec
        entradas.append(t)
    estados = estados_visibles(user, empresa)
    sub_por_estado = tarjetas_subticket(
        asignaciones_sub, estados, viewer=None, movible=tiene_capacidad(user, 'tar.tickets.move', empresa),
    )
    columnas = []
    for valor, label in estados:
        col = [t for t in entradas if t.estado_visual == valor]
        if resaltar_propios:
            col.sort(key=lambda t: (t.atenuado, t.posicion, numero_base(t)))
        else:
            col.sort(key=lambda t: (t.posicion, numero_base(t)))
        items = [{'type': 'ticket', 't': t} for t in col] + sub_por_estado[valor]
        columnas.append({'value': valor, 'label': label, 'items': items, 'count': len(items)})
    return columnas


def columnas_por_subticket(request):
    """Vista del ejecutor: tarjetas = sus subtickets (sólidos) + los de co-ejecutores (fantasma)."""
    user, empresa = request.user, request.empresa
    mis_ids = list(Asignacion.objects.filter(
        user=user, tipo=Asignacion.Tipo.EJECUTOR, ticket__empresa=empresa,
        ticket__archivado_en__isnull=True, ticket__dividido_en__isnull=True,
    ).values_list('ticket_id', flat=True))
    tickets = aplicar_filtros(Ticket.objects.filter(id__in=mis_ids), request.GET).annotate(
        num_comments=Count('comentarios', distinct=True),
    )
    tids = set(tickets.values_list('id', flat=True))
    conteo = {t.id: t.num_comments for t in tickets}
    asignaciones = Asignacion.objects.filter(
        ticket_id__in=tids, tipo=Asignacion.Tipo.EJECUTOR,
    ).select_related('ticket', 'ticket__proyecto', 'ticket__padre', 'user').prefetch_related(
        'ticket__etiquetas', 'ticket__asignaciones__user', 'ticket__hijos', 'ticket__padre__hijos',
    )
    visibles = []
    for a in asignaciones:
        a.bloqueado = bool(a.ticket.suspendido_en)
        a.ticket.num_children = len(a.ticket.hijos.all())
        a.ticket.num_comments = conteo.get(a.ticket_id, 0)
        # Colaborativa (sin subproductos): solo el subticket propio. Con subproductos: el propio
        # (sólido) + los de co-ejecutores (fantasma).
        if a.ticket.tiene_subproductos or a.user_id == user.id:
            visibles.append(a)
    estados = estados_visibles(user, empresa)
    por_estado = tarjetas_subticket(visibles, estados, viewer=user)
    return [{'value': v, 'label': l, 'items': por_estado[v], 'count': len(por_estado[v])} for v, l in estados]


def contexto_tablero(request):
    user, empresa = request.user, request.empresa
    por_ticket = tiene_capacidad(user, 'tar.tickets.board_by_ticket', empresa)
    return {
        'columns': columnas_por_ticket(request) if por_ticket else columnas_por_subticket(request),
        'board_mode': 'ticket' if por_ticket else 'subticket',
        'can_move': tiene_capacidad(user, 'tar.tickets.move', empresa),
    }


# ── Asignaciones ──────────────────────────────────────────────────────────────

def sincronizar_asignaciones(ticket, ejecutores, expertos, estado=E.POR_HACER, recalcular=True):
    """Sincroniza las Asignaciones del ticket con lo elegido. Devuelve
    `(usuarios_nuevos, asignaciones_conservadas, usuarios_removidos)`: las conservadas son
    desmarcadas que NO se borraron por tener trabajo registrado. `estado` es el inicial de las
    nuevas. `recalcular=False` deja el estado del ticket tal cual (la creación lo usa para que un
    ticket recién creado quede siempre en «Entrada»)."""
    deseado = {}
    for u in expertos:
        deseado[u.pk] = Asignacion.Tipo.EXPERTO
    for u in ejecutores:
        deseado[u.pk] = Asignacion.Tipo.EJECUTOR  # si está en ambos, gana ejecutor
    existentes = {a.user_id: a for a in ticket.asignaciones.select_related('user')}
    conservadas, removidos = [], []
    for uid, a in existentes.items():
        if uid not in deseado:
            if a.es_ejecutor and (a.iniciado_en or a.estado == E.CONCLUIDO):
                # Con trabajo empezado o concluido, borrar destruiría tiempos, conclusión y
                # aprobación de forma irreversible: se conserva y el llamador avisa.
                conservadas.append(a)
                continue
            removidos.append(a.user)
            a.delete()
    agregados = []
    for uid, tipo in deseado.items():
        a = existentes.get(uid)
        if a is None:
            Asignacion.objects.create(ticket=ticket, user_id=uid, tipo=tipo, estado=estado)
            agregados.append(uid)
        elif a.tipo != tipo:
            a.tipo = tipo
            a.save(update_fields=['tipo'])
    if recalcular:
        ticket.recalcular_estado()
    return list(User.objects.filter(pk__in=agregados)), conservadas, removidos


# ── Movimiento, conclusión, aprobación y suspensión ───────────────────────────
from django.core.exceptions import PermissionDenied  # noqa: E402
from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from cuentas.capacidades import usuarios_con_capacidad  # noqa: E402
from notificaciones.services import notificar  # noqa: E402

from .models import Comentario  # noqa: E402

# Columnas a las que se puede arrastrar un subticket (nunca «Entrada»).
ESTADOS_ARRASTRABLES = (E.POR_HACER, E.EN_PROGRESO, E.SUSPENDIDO, E.CONCLUIDO)


class ErrorDeMovimiento(Exception):
    """Movimiento rechazado; el mensaje es apto para mostrar."""


def bloquear_ticket(ticket_id):
    """Lock de fila del ticket: serializa mutaciones concurrentes sobre él y su subgrafo de
    Asignaciones (dos directores moviendo, aprobar vs. concluir…). Requiere transaction.atomic();
    en SQLite es un no-op inocuo."""
    return Ticket.objects.select_for_update().get(pk=ticket_id)


def url_ticket(ticket):
    return f'/tareas/{ticket.pk}/'


def avisar(ticket, destinatarios, actor, verbo):
    """Notifica a cada destinatario (menos al actor, que `notificar` ya omite)."""
    vistos = set()
    for u in destinatarios:
        if u is None or u.pk in vistos:
            continue
        vistos.add(u.pk)
        notificar(u, ticket.empresa, f'{verbo}: {ticket.clave} · {ticket.titulo}', url=url_ticket(ticket), actor=actor)


def personas_del_ticket(ticket):
    """Creador + todos los asignados (ejecutores y expertos)."""
    return [u for u in [ticket.creador] + [a.user for a in ticket.asignaciones.all()] if u]


def concluir_asignaciones(a, actor, conclusion=''):
    """Concluye el/los subtickets de `a`: solo el propio con subproductos, todos los ejecutores si
    la tarea es colaborativa. La conclusión (texto o link) es opcional."""
    ahora = timezone.now()
    ticket = a.ticket
    objetivos = [a] if ticket.tiene_subproductos else list(ticket.ejecutores)
    for ea in objetivos:
        ea.avanzar_a(E.CONCLUIDO, ahora)
        ea.cerrado_en = ahora
        ea.conclusion = conclusion
        if not ea.iniciado_en:
            ea.iniciado_en = ea.creado
        ea.save()
    if not ticket.tiene_subproductos:
        detalle = 'concluyó la tarea'
    elif actor.pk == a.user_id:
        detalle = 'concluyó su subticket'
    else:
        detalle = f'concluyó el subticket de {nombre_usuario(a.user)}'  # el director arrastró el de un ejecutor
    registrar_evento(ticket, actor, 'conclude', detalle, asignacion=a)
    ticket.recalcular_estado()
    # Avisa al creador Y a quienes pueden aprobar: si el creador es el propio ejecutor (o está de
    # baja), ningún director se enteraría de que hay algo por aprobar.
    verbo = ('concluyó un subticket (pendiente de aprobación)' if ticket.tiene_subproductos
             else 'concluyó la tarea (pendiente de aprobación)')
    avisar(ticket, [*usuarios_con_capacidad(ticket.empresa, 'tar.tickets.close'), ticket.creador], actor, verbo)
    if conclusion.strip():
        prefijo = 'Concluyó su subticket' if ticket.tiene_subproductos else 'Concluyó la tarea'
        Comentario.objects.create(ticket=ticket, autor=actor, texto=f'{prefijo}: {conclusion.strip()}')
        avisar(ticket, personas_del_ticket(ticket), actor, 'comentó en')


def mover_tickets(user, empresa, estado, orden):
    """Mueve tarjetas de TICKET completo (tablero por ticket) a `estado`, en el `orden` dado.
    Solo tickets que `user` puede ver; los suspendidos por el director no se mueven, y «Entrada» es
    la bandeja de tickets sin ejecutor."""
    if estado not in Ticket.Estado.values:
        raise ErrorDeMovimiento('estado inválido')
    with transaction.atomic():
        # Lock de las filas afectadas ANTES de leerlas (queryset pelado, sin joins).
        list(Ticket.objects.select_for_update().filter(pk__in=orden, empresa=empresa).values_list('pk', flat=True))
        movibles = {t.pk: t for t in tickets_visibles(user, empresa).filter(pk__in=orden)}
        ahora = timezone.now()
        for indice, tid in enumerate(orden):
            t = movibles.get(tid)
            if t is None or t.suspendido_en:
                continue
            anterior = t.estado
            cambio = anterior != estado
            ejec = [a for a in t.asignaciones.all() if a.tipo == Asignacion.Tipo.EJECUTOR]
            if estado == E.ENTRADA and ejec:
                continue
            t.posicion = indice
            if not cambio:
                t.save(update_fields=['posicion', 'actualizado'])
                continue
            if estado in ESTADOS_ARRASTRABLES and ejec:
                # Sincroniza los subtickets con la tarjeta arrastrada (evita el desfase ticket vs.
                # asignación que dejaba un ticket con ejecutores cayendo en «Entrada»).
                for ea in ejec:
                    ea.avanzar_a(estado, ahora)
                    if estado == E.CONCLUIDO:
                        ea.cerrado_en = ahora
                        if not ea.iniciado_en:
                            ea.iniciado_en = ea.creado
                    ea.save()
                t.save(update_fields=['posicion', 'actualizado'])
                t.recalcular_estado()
            else:
                t.estado = estado
                if estado == E.CONCLUIDO and t.cerrado_en is None:
                    t.cerrado_en = ahora
                elif estado != E.CONCLUIDO and t.cerrado_en is not None:
                    t.cerrado_en = None
                t.save(update_fields=['estado', 'posicion', 'cerrado_en', 'actualizado'])
            registrar_evento(t, user, 'status', f'movió a «{t.get_estado_display()}»')
            if anterior == E.ENTRADA and t.estado == E.POR_HACER:
                avisar(t, personas_del_ticket(t), user, 'puso en Por hacer')


def mover_subtickets(user, empresa, estado, ids):
    """El ejecutor mueve SU subticket (quien puede asignar mueve también los ajenos; la tarjeta
    fusionada manda el grupo entero)."""
    if estado not in ESTADOS_ARRASTRABLES:
        raise ErrorDeMovimiento('estado no permitido')
    if estado == E.SUSPENDIDO and not tiene_capacidad(user, 'tar.tickets.view_waiting', empresa):
        # El ejecutor no ve esa columna: aceptarle SUSPENDIDO mandaría la tarea (en las colaborativas,
        # la de TODOS) a un lugar que no puede ver ni revertir.
        raise ErrorDeMovimiento('estado no permitido')
    with transaction.atomic():
        movimientos = list(Asignacion.objects.filter(
            pk__in=set(ids), tipo=Asignacion.Tipo.EJECUTOR, ticket__empresa=empresa,
        ).select_related('ticket', 'user'))
        if len(movimientos) != len(set(ids)):
            raise ErrorDeMovimiento('subticket inexistente')
        if len({a.ticket_id for a in movimientos}) != 1:
            raise ErrorDeMovimiento('los subtickets deben ser del mismo ticket')
        if any(a.user_id != user.pk for a in movimientos) and not tiene_capacidad(user, 'tar.tickets.assign', empresa):
            raise PermissionDenied
        ticket = bloquear_ticket(movimientos[0].ticket_id)
        for a in movimientos:
            a.ticket = ticket
            a.refresh_from_db()  # re-lee ya bajo el lock (pudo cambiar en la espera)
            if ticket.suspendido_en:
                raise ErrorDeMovimiento('el ticket está suspendido por el coordinador')
            if a.estado == estado:
                continue
            if estado == E.CONCLUIDO:
                concluir_asignaciones(a, user)
                continue
            ahora = timezone.now()
            if ticket.tiene_subproductos:
                a.avanzar_a(estado, ahora)
                a.save()
                if a.user_id == user.pk:
                    detalle = f'movió su subticket a «{a.get_estado_display()}»'
                else:
                    detalle = f'movió el subticket de {nombre_usuario(a.user)} a «{a.get_estado_display()}»'
                registrar_evento(ticket, user, 'status', detalle, asignacion=a)
            else:
                # Colaborativa: el estado es compartido → se sincroniza a todos los ejecutores.
                for ea in ticket.ejecutores:
                    ea.avanzar_a(estado, ahora)
                    ea.save()
                registrar_evento(ticket, user, 'status', f'movió la tarea a «{Ticket.Estado(estado).label}»')
        ticket.recalcular_estado()
    return ticket


def aprobar(ticket, actor):
    """El director aprueba las conclusiones pendientes. Devuelve las asignaciones aprobadas."""
    with transaction.atomic():
        ticket = bloquear_ticket(ticket.pk)
        pendientes = ticket.ejecutores.filter(estado=E.CONCLUIDO, aprobado_en__isnull=True)
        aprobadas = list(pendientes.select_related('user'))
        if aprobadas:
            pendientes.update(aprobado_en=timezone.now())
            registrar_evento(ticket, actor, 'approve', 'aprobó la conclusión')
            ticket.recalcular_estado()
            avisar(ticket, [a.user for a in aprobadas], actor, 'aprobó tu conclusión')
    return ticket, aprobadas


def rechazar(ticket, actor, motivo):
    """El director devuelve las conclusiones pendientes a «En progreso» con feedback obligatorio."""
    motivo = (motivo or '').strip()
    if not motivo:
        raise ErrorDeMovimiento('Indica el motivo del rechazo: es lo que verá el ejecutor.')
    with transaction.atomic():
        ticket = bloquear_ticket(ticket.pk)
        pendientes = list(ticket.ejecutores.filter(estado=E.CONCLUIDO, aprobado_en__isnull=True).select_related('user'))
        if not pendientes:
            return ticket, []
        ahora = timezone.now()
        for ea in pendientes:
            ea.avanzar_a(E.EN_PROGRESO, ahora)  # salir de CONCLUIDO limpia aprobado_en/cerrado_en
            ea.save()
        registrar_evento(ticket, actor, 'reject', 'rechazó la conclusión')
        ticket.recalcular_estado()
        Comentario.objects.create(ticket=ticket, autor=actor, texto=f'Rechazó la conclusión: {motivo}')
    avisar(ticket, [a.user for a in pendientes], actor, 'rechazó tu conclusión')
    return ticket, pendientes


def alternar_suspension(ticket, actor):
    """Suspende/cancela el ticket o lo reactiva. Solo quien dirige toca este candado: mientras
    `suspendido_en` está fijado, los ejecutores no pueden mover su subticket. Devuelve True si quedó
    suspendido."""
    with transaction.atomic():
        ticket = bloquear_ticket(ticket.pk)
        ahora = timezone.now()
        if ticket.estado == E.SUSPENDIDO:
            # Reactivar: cada subticket vuelve al estado que tenía al suspender (no a «Por hacer» a
            # ciegas, que «renacía» trabajo en progreso).
            for ea in ticket.ejecutores.filter(estado=E.SUSPENDIDO):
                ea.avanzar_a(ea.estado_antes_de_suspender or E.POR_HACER, ahora)
                ea.estado_antes_de_suspender = ''
                ea.save()
            ticket.suspendido_en = None
            ticket.save(update_fields=['suspendido_en', 'actualizado'])
            registrar_evento(ticket, actor, 'status', 'reactivó el ticket')
            avisar(ticket, personas_del_ticket(ticket), actor, 'reactivó el ticket')
            suspendido = False
        else:
            # Los ya concluidos no se tocan: pisarlos borraría la conclusión/aprobación.
            for ea in ticket.ejecutores.exclude(estado=E.CONCLUIDO):
                ea.estado_antes_de_suspender = ea.estado
                ea.avanzar_a(E.SUSPENDIDO, ahora)
                ea.save()
            ticket.suspendido_en = ahora
            ticket.save(update_fields=['suspendido_en', 'actualizado'])
            registrar_evento(ticket, actor, 'status', 'suspendió/canceló el ticket')
            avisar(ticket, personas_del_ticket(ticket), actor, 'suspendió/canceló el ticket')
            suspendido = True
        ticket.recalcular_estado()
    return suspendido


# ── Permisos de edición / archivado ───────────────────────────────────────────

def puede_editar(user, ticket):
    """Editar el ticket es exclusivo de quien tiene `tar.tickets.edit_any`."""
    return tiene_capacidad(user, 'tar.tickets.edit_any', ticket.empresa_id)


def puede_archivar(user, ticket):
    return puede_editar(user, ticket) or ticket.creador_id == user.id or ticket.es_participante(user)


# ── Derivar / dividir ─────────────────────────────────────────────────────────

def crear_hijo_desde(padre, actor, *, sufijo, clonar=False):
    """Crea un hijo con código jerárquico (EMBOL-0014-N) heredando etiquetas y asignados del padre.
    Común a «Derivar» (tarea nueva a completar a mano) y «Dividir» (`clonar=True`: la parte nace
    idéntica al padre, también en estado y progreso de cada asignación)."""
    hijo = padre.crear_hijo(
        titulo=padre.titulo if clonar else f'{padre.titulo} {sufijo}',
        solicitante=padre.solicitante,
        descripcion=padre.descripcion if clonar else '',
        prioridad=padre.prioridad if clonar else Ticket.Prioridad.MEDIA,
        vence=padre.vence if clonar else None,
        tiene_subproductos=padre.tiene_subproductos if clonar else False,
        es_parte_dividida=clonar,
        proyecto=padre.proyecto,
        # Al dividir se conserva el creador original (es el mismo pedido partido); al derivar es una
        # tarea nueva, la crea quien la deriva.
        creador=padre.creador if clonar else actor,
        estado=padre.estado,
        # Hereda el candado del director: si no, el hijo de un ticket suspendido nacía en la columna
        # «Suspendido» pero SIN candado, y cualquier ejecutor podía moverlo.
        suspendido_en=padre.suspendido_en,
    )
    hijo.etiquetas.set(padre.etiquetas.all())
    asig_padre = list(padre.asignaciones.select_related('user'))
    ejecutores = [a.user for a in asig_padre if a.es_ejecutor]
    expertos = [a.user for a in asig_padre if not a.es_ejecutor]
    # El hijo nace en la misma columna que el padre. «Entrada» no es un estado válido de Asignación.
    estado_asig = padre.estado if padre.estado in ESTADOS_ARRASTRABLES else E.POR_HACER
    nuevos, _c, _r = sincronizar_asignaciones(
        hijo, ejecutores, expertos, estado=estado_asig,
        # Al clonar, el estado final lo fija el bloque de abajo tal cual el padre: recalcularlo desde las
        # asignaciones rompería «mismo estado» (nunca deriva «Entrada» habiendo un ejecutor asignado).
        recalcular=not clonar,
    )
    if clonar:
        por_user = {a.user_id: a for a in asig_padre}
        for ca in hijo.asignaciones.all():
            pa = por_user.get(ca.user_id)
            if pa:
                ca.estado, ca.iniciado_en, ca.cerrado_en = pa.estado, pa.iniciado_en, pa.cerrado_en
                ca.conclusion, ca.aprobado_en = pa.conclusion, pa.aprobado_en
                ca.save(update_fields=['estado', 'iniciado_en', 'cerrado_en', 'conclusion', 'aprobado_en'])
        hijo.estado, hijo.cerrado_en = padre.estado, padre.cerrado_en
        hijo.save(update_fields=['estado', 'cerrado_en', 'actualizado'])
    avisar(hijo, nuevos, actor, 'te asignó')
    return hijo


def derivar(padre, actor):
    with transaction.atomic():
        padre = bloquear_ticket(padre.pk)
        hijo = crear_hijo_desde(padre, actor, sufijo='(derivado)')
        registrar_evento(hijo, actor, 'created', f'derivado de {padre.clave}')
    return hijo


def dividir(padre, actor):
    with transaction.atomic():
        padre = bloquear_ticket(padre.pk)
        hijo = crear_hijo_desde(padre, actor, sufijo='(parte)', clonar=True)
        registrar_evento(padre, actor, 'split', 'dividido en partes')
        registrar_evento(hijo, actor, 'created', f'parte de {padre.clave}')
    return hijo


# ── Archivar / desarchivar / eliminar ─────────────────────────────────────────

def archivar(ticket, actor):
    """Archiva un ticket Concluido o Suspendido. Devuelve False si el estado no lo permite."""
    if ticket.estado not in (E.CONCLUIDO, E.SUSPENDIDO):
        return False
    ticket.archivado_en = timezone.now()
    ticket.save(update_fields=['archivado_en', 'actualizado'])
    registrar_evento(ticket, actor, 'archived', 'archivó el ticket')
    return True


def desarchivar(ticket, actor):
    ticket.archivado_en = None
    ticket.save(update_fields=['archivado_en', 'actualizado'])
    registrar_evento(ticket, actor, 'archived', 'desarchivó el ticket')


# ── Edición ───────────────────────────────────────────────────────────────────

def aplicar_edicion(ticket, form, actor, *, puede_asignar):
    """Guarda el formulario de un ticket existente, registra los cambios relevantes y sincroniza las
    asignaciones. Devuelve la lista de asignaciones CONSERVADAS (no se pudieron quitar por tener
    trabajo registrado)."""
    conservadas = []
    with transaction.atomic():
        bloquear_ticket(ticket.pk)
        # Los valores «anteriores» se leen de la BD: el ModelForm ya mutó la instancia al validar.
        antes = Ticket.objects.filter(pk=ticket.pk).values('prioridad', 'vence', 'estado').get()
        obj = form.save()
        if obj.prioridad != antes['prioridad']:
            registrar_evento(obj, actor, 'priority', f'cambió la prioridad a «{obj.get_prioridad_display()}»')
        if obj.vence != antes['vence']:
            fecha = obj.vence.strftime('%d/%m/%Y') if obj.vence else 'sin fecha'
            registrar_evento(obj, actor, 'due', f'cambió el vencimiento a {fecha}')
        if puede_asignar:
            nuevos, conservadas, removidos = sincronizar_asignaciones(
                obj, form.cleaned_data.get('ejecutores', []), form.cleaned_data.get('expertos', []))
            if nuevos or removidos:
                registrar_evento(obj, actor, 'assignee', 'actualizó las asignaciones')
                avisar(obj, nuevos, actor, 'te asignó')
            avisar(obj, removidos, actor, 'te desasignó de')
            if antes['estado'] == E.ENTRADA and obj.estado == E.POR_HACER:
                avisar(obj, personas_del_ticket(obj), actor, 'puso en Por hacer')
    return conservadas


# ── Chat ──────────────────────────────────────────────────────────────────────

def comentarios_del_hilo(ticket):
    return Comentario.objects.filter(ticket_id__in=ticket.ids_hilo()).select_related('autor', 'ticket').prefetch_related('adjuntos')


def es_ultimo_comentario(comentario):
    return not Comentario.objects.filter(ticket_id=comentario.ticket_id, pk__gt=comentario.pk).exists()


def puede_moderar_comentario(user, comentario):
    """Solo el autor (o quien tiene edit_any) y solo el ÚLTIMO mensaje: los anteriores quedan
    inmutables como registro de la conversación."""
    if comentario.autor_id != user.id and not tiene_capacidad(user, 'tar.tickets.edit_any', comentario.ticket.empresa_id):
        return False
    return es_ultimo_comentario(comentario)


def avisar_comentario(ticket, autor):
    avisar(ticket, personas_del_ticket(ticket), autor, 'comentó en')
