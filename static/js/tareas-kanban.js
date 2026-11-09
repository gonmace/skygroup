// Drag & drop del tablero de Tareas (portado de skydesk). Requiere vendor/sortable.min.js antes.
// CSP-safe: sin inline; token CSRF de <meta name="csrf-token">.
// Dos modos: 'ticket' (coordinador: mueve tickets y también los subtickets ajenos de
// los multiproducto) y 'subticket' (ejecutor mueve su subticket).
// Expone window.initKanban() para re-inicializar tras recargar el fragmento por AJAX.
(function () {
  'use strict';

  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrftoken = meta ? meta.getAttribute('content') : '';
  var ALLOWED = { TODO: 1, IN_PROGRESS: 1, WAITING: 1, DONE: 1 };

  function post(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrftoken,
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify(body)
    });
  }

  // Cards de subticket (multiproducto): llevan data-assignment-id (una sola) o
  // data-assignment-ids (fusionada del coordinador: el grupo entero).
  function isAssignmentCard(el) {
    return el.hasAttribute('data-assignment-id') || el.hasAttribute('data-assignment-ids');
  }

  function persistTicketOrder(board, column) {
    // Los subtickets de un ticket multiproducto (tablero del coordinador) no tienen
    // posición propia de ticket y su data-ticket-id es el del PADRE: si entraran al
    // order, ticket_move movería el ticket entero. Van por persistAssignment.
    var order = [];
    Array.prototype.forEach.call(column.querySelectorAll('.ticket-card:not(.is-readonly)'), function (el) {
      if (!isAssignmentCard(el)) order.push(parseInt(el.getAttribute('data-ticket-id'), 10));
    });
    post(board.getAttribute('data-move-url'), {
      status: column.getAttribute('data-status'), order: order
    }).catch(function () { window.location.reload(); });
  }

  function persistAssignment(board, item, toColumn) {
    var body = { status: toColumn.getAttribute('data-status') };
    var groupIds = item.getAttribute('data-assignment-ids');
    if (groupIds) {
      // Merged del coordinador: mueve todos los subtickets del grupo de una.
      body.assignments = groupIds.split(',').map(function (s) { return parseInt(s, 10); });
    } else {
      body.assignment = parseInt(item.getAttribute('data-assignment-id'), 10);
    }
    post(board.getAttribute('data-assignment-move-url'), body).then(function (r) {
      if (!r.ok) { window.location.reload(); return; }
      // El servidor puede fusionar/separar cards multiproducto (mismo ticket, mismo
      // estado) — SortableJS solo movió el nodo que arrastramos, así que hace falta
      // refrescar el fragmento para que la fusión/separación (y el fantasma) se vean.
      if (window.refreshBoard) window.refreshBoard();
    }).catch(function () { window.location.reload(); });
  }

  function init() {
    var board = document.querySelector('[data-kanban]');
    if (!board || typeof Sortable === 'undefined') return;
    if (board.getAttribute('data-can-move') !== '1') return;
    var mode = board.getAttribute('data-mode') || 'ticket';

    Array.prototype.forEach.call(board.querySelectorAll('.kanban-col'), function (col) {
      var existing = Sortable.get(col);
      if (existing) existing.destroy();
      new Sortable(col, {
        group: 'kanban',
        draggable: '.ticket-card',
        // fantasmas, suspendidos y subtickets de solo lectura (tablero del coordinador
        // sobre tickets con subproductos) no se arrastran.
        filter: '.is-ghost, .is-locked, .is-readonly',
        animation: 150,
        ghostClass: 'opacity-40',
        delay: 150,
        delayOnTouchOnly: true,
        touchStartThreshold: 5,
        onMove: function (evt) {
          // Un subticket nunca puede caer en «Entrada» (ni en columnas ocultas):
          // aplica al tablero del ejecutor y a las cards de subticket que el
          // coordinador arrastra dentro del suyo.
          if (mode === 'subticket' || isAssignmentCard(evt.dragged)) {
            return !!ALLOWED[evt.to.getAttribute('data-status')];
          }
          return true;
        },
        onEnd: function (evt) {
          if (mode === 'subticket' || isAssignmentCard(evt.item)) {
            persistAssignment(board, evt.item, evt.to);
          } else {
            persistTicketOrder(board, evt.to);
            if (evt.from !== evt.to) persistTicketOrder(board, evt.from);
          }
        }
      });
    });
  }

  window.initKanban = init;
  init();
})();
