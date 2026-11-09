// Tiempo real del módulo Tareas (Django Channels). CSP-safe: sin inline. Se conecta a la URL indicada en
// [data-live-url] (/ws/empresa/<slug>/tareas/) y reacciona a:
//  - 'board.changed'  -> refresca el tablero (window.refreshBoard), con debounce para coalescer ráfagas.
//  - 'ticket.changed' -> si es el ticket (o un padre de su hilo) que se está viendo, recarga la página.
//  - 'comment.new'    -> mensaje nuevo en el seguimiento visible: lo agrega por AJAX (window.chatFetchNew)
//                        SIN recargar, para no pisar lo que el usuario esté escribiendo.
// Degrada en silencio si el WebSocket no conecta: la app sigue funcionando, solo se pierde el aviso.
(function () {
  'use strict';

  var host = document.querySelector('[data-live-url]');
  if (!host) return;
  var liveUrl = host.getAttribute('data-live-url');

  var socket = null;
  var reconnectDelay = 1000;
  var MAX_RECONNECT_DELAY = 30000;
  var boardRefreshTimer = null;
  var closedForGood = false;

  var marker = document.getElementById('live-ticket-marker');
  var watchedTicketId = marker ? marker.getAttribute('data-ticket-id') : null;
  // El detalle hereda el seguimiento de su cadena de padres (derivar/dividir): también hay que refrescar
  // cuando cambia cualquiera de esos tickets.
  var watchedThreadIds = [];
  if (marker && marker.getAttribute('data-thread-ids')) {
    watchedThreadIds = marker.getAttribute('data-thread-ids').split(',').filter(Boolean);
  } else if (watchedTicketId) {
    watchedThreadIds = [watchedTicketId];
  }

  // Una acción propia (p. ej. «Dividir») puede mutar el ticket que se está viendo y disparar su aviso
  // ANTES de que el navegador reciba la respuesta del formulario: el recargar competiría con la
  // navegación y a veces devolvía al usuario a la misma página. Marcar `navigating` en el submit real
  // cierra esa carrera en el origen; `beforeunload` cubre la navegación por enlaces.
  var navigating = false;
  window.addEventListener('beforeunload', function () { navigating = true; });
  document.addEventListener('submit', function (ev) {
    if (!ev.defaultPrevented) navigating = true;
  });

  function refreshBoardDebounced() {
    if (!window.refreshBoard) return;
    clearTimeout(boardRefreshTimer);
    boardRefreshTimer = setTimeout(window.refreshBoard, 400);
  }

  function handleMessage(event) {
    var data;
    try { data = JSON.parse(event.data); } catch (e) { return; }
    if (data.type === 'board.changed') {
      refreshBoardDebounced();
    } else if (data.type === 'ticket.changed') {
      if (!navigating && watchedThreadIds.indexOf(String(data.ticket_id)) !== -1) {
        window.location.reload();
      }
    } else if (data.type === 'comment.new') {
      // Agregar es inofensivo aunque haya una navegación en curso (chatFetchNew dedupea por data-comment-id).
      if (watchedThreadIds.indexOf(String(data.ticket_id)) !== -1 && window.chatFetchNew) {
        window.chatFetchNew();
      }
    }
  }

  function connect() {
    var proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    socket = new WebSocket(proto + '://' + window.location.host + liveUrl);
    socket.onopen = function () {
      reconnectDelay = 1000;
      watchedThreadIds.forEach(function (id) {
        socket.send(JSON.stringify({ action: 'subscribe_ticket', id: parseInt(id, 10) }));
      });
    };
    socket.onmessage = handleMessage;
    socket.onclose = function (e) {
      if (closedForGood || e.code === 4401 || e.code === 4403) return;  // sin sesión / sin acceso: no reintentar
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
    };
    socket.onerror = function () { /* silencioso: onclose maneja el reintento */ };
  }

  connect();
})();
