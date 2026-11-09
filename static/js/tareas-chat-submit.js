// Chat de seguimiento sin recargas. CSP-safe: sin inline.
//  - Envía el form por fetch (AJAX) y appendea el mensaje devuelto — Enter envía,
//    Shift+Enter hace salto de línea.
//  - Expone window.chatFetchNew: trae los mensajes nuevos (?after=<último pk del DOM>)
//    cuando live.js recibe un push 'comment.new' de otro usuario — append sin reload,
//    así nunca se pisa lo que se esté escribiendo.
//  - Borrador en sessionStorage: sobrevive a los reloads que sí quedan (cambios de
//    estado del ticket vía 'ticket.changed', anotar imagen).
//  - Cancela la edición inline al presionar el botón o Escape.
(function () {
  'use strict';

  var TAG_TYPE = { error: 'error', success: 'success', warning: 'warning', info: 'info', debug: 'info' };

  // El área de mensajes tiene altura máxima: arrancar con el scroll abajo
  // para que se vean los mensajes más recientes. Se repite en window.load
  // porque las imágenes adjuntas cargan después y empujan el contenido.
  var messages = document.querySelector('[data-chat-messages]');
  function scrollToBottom() {
    if (messages) messages.scrollTop = messages.scrollHeight;
  }
  scrollToBottom();
  window.addEventListener('load', scrollToBottom);

  // ── Borrador en sessionStorage ─────────────────────────────────────────────
  var marker = document.getElementById('live-ticket-marker');
  var draftKey = 'tareas-chat-draft-' + (marker ? marker.getAttribute('data-ticket-id') : window.location.pathname);
  var compose = document.getElementById('chat-compose');

  function clearDraft() {
    try { sessionStorage.removeItem(draftKey); } catch (e) { /* storage bloqueado */ }
  }
  if (compose) {
    try {
      var savedDraft = sessionStorage.getItem(draftKey);
      if (savedDraft && !compose.value) compose.value = savedDraft;
    } catch (e) { /* storage bloqueado */ }
    compose.addEventListener('input', function () {
      try {
        if (compose.value) sessionStorage.setItem(draftKey, compose.value);
        else sessionStorage.removeItem(draftKey);
      } catch (e) { /* storage bloqueado */ }
    });
  }

  // Tras un envío no-AJAX (fallback POST + recarga completa), volver a enfocar el
  // textarea de compose. Ver #chat-compose en tickets/views.py::comment_add.
  if (window.location.hash === '#chat-compose' && compose) {
    compose.focus();
    var len = compose.value.length;
    compose.setSelectionRange(len, len);
    // Limpiar el hash para que un refresh no vuelva a robar el foco.
    history.replaceState(null, '', window.location.pathname + window.location.search);
  }

  // ── Append de mensajes (usado por el envío propio y por chatFetchNew) ───────
  function appendMessages(html) {
    if (!messages || !html) return;
    var tpl = document.createElement('template');
    tpl.innerHTML = html;
    // Dedupe por data-comment-id: el emisor recibe su propio 'comment.new' por WS
    // además de la respuesta del fetch, en cualquier orden.
    var fresh = Array.prototype.filter.call(tpl.content.querySelectorAll('[data-comment-id]'), function (node) {
      return !messages.querySelector('[data-comment-id="' + node.getAttribute('data-comment-id') + '"]');
    });
    if (!fresh.length) return;
    var empty = messages.querySelector('[data-chat-empty]');
    if (empty) empty.remove();
    // El mensaje anterior deja de ser el último: pierde su "editar" (cosmético —
    // el server re-valida igual con _can_moderate_comment).
    Array.prototype.forEach.call(messages.querySelectorAll('details[data-chat-edit]'), function (d) {
      d.remove();
    });
    fresh.forEach(function (node) { messages.appendChild(node); });
    scrollToBottom();
  }

  // ── Mensajes nuevos de otros (push 'comment.new' → live.js → acá) ───────────
  var fetchingNew = false;
  var refetchQueued = false;
  function chatFetchNew() {
    if (!messages) return;
    var url = messages.getAttribute('data-since-url');
    if (!url) return;
    if (fetchingNew) { refetchQueued = true; return; }  // coalescer ráfagas
    fetchingNew = true;
    var present = messages.querySelectorAll('[data-comment-id]');
    var after = present.length ? present[present.length - 1].getAttribute('data-comment-id') : '0';
    var done = function () {
      fetchingNew = false;
      if (refetchQueued) { refetchQueued = false; chatFetchNew(); }
    };
    fetch(url + '?after=' + encodeURIComponent(after), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); })
      .then(function (data) { if (data && data.ok) appendMessages(data.html); done(); })
      .catch(done);
  }
  window.chatFetchNew = chatFetchNew;

  // ── Envío del form por fetch ─────────────────────────────────────────────────
  // preventDefault también evita que live.js marque `navigating` (su listener de
  // document chequea ev.defaultPrevented) — ya no hay navegación al comentar.
  Array.prototype.forEach.call(document.querySelectorAll('form[data-chat-submit]'), function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var btn = form.querySelector('button[type=submit]');
      if (btn && btn.disabled) return;  // guard de doble envío
      var ta = form.querySelector('textarea');
      var hasFiles = false;
      Array.prototype.forEach.call(form.querySelectorAll('[data-dropzone-input]:not(:disabled)'), function (input) {
        if (input.files && input.files.length > 0) hasFiles = true;
      });
      // Spinner "Subiendo adjuntos…" (subir a Nextcloud puede tardar).
      var indicator = form.querySelector('[data-chat-uploading]');
      if (hasFiles && indicator) { indicator.classList.remove('hidden'); indicator.classList.add('flex'); }
      if (btn) btn.disabled = true;

      var finish = function () {
        if (btn) btn.disabled = false;
        if (indicator) { indicator.classList.add('hidden'); indicator.classList.remove('flex'); }
        if (ta) ta.focus();
      };

      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      })
        .then(function (r) {
          // Sesión expirada → HTML del login: tratar como fallo SIN limpiar el texto.
          var ct = r.headers.get('content-type') || '';
          if (ct.indexOf('application/json') === -1) throw new Error('respuesta no-JSON');
          return r.json();
        })
        .then(function (data) {
          if (data.ok) {
            appendMessages(data.html);
            if (ta) ta.value = '';
            clearDraft();
            // Vaciar el dropzone: dropzone.js re-renderiza los previews en 'change'.
            Array.prototype.forEach.call(form.querySelectorAll('[data-dropzone-input]'), function (input) {
              input.value = '';
              input.dispatchEvent(new Event('change'));
            });
            (data.warnings || []).forEach(function (w) {
              if (window.Alert) Alert.show(w.message, TAG_TYPE[w.tag] || 'info', { autoHide: 6000 });
            });
          } else if (window.Alert) {
            Alert.error(data.error || 'No se pudo enviar el mensaje.');
          }
          finish();
        })
        .catch(function () {
          // Texto y adjuntos quedan intactos para reintentar.
          if (window.Alert) Alert.error('No se pudo enviar el mensaje. Revisá tu conexión e intentá de nuevo.');
          finish();
        });
    });
  });

  // Enter envía el form contenedor (textarea del chat nuevo).
  Array.prototype.forEach.call(document.querySelectorAll('form[data-chat-submit] textarea'), function (ta) {
    ta.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
      e.preventDefault();
      ta.form.requestSubmit();
    });
  });

  // Enter envía el form de edición inline; Escape cancela.
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      var input = e.target.closest('[data-chat-edit-input]');
      if (input) {
        e.preventDefault();
        input.form.requestSubmit();
      }
    }
    if (e.key === 'Escape') {
      var details = e.target.closest('details[data-chat-edit]');
      if (details) details.open = false;
    }
  });

  // Botón cancelar cierra el <details>.
  document.addEventListener('click', function (e) {
    var cancel = e.target.closest('[data-chat-edit-cancel]');
    if (!cancel) return;
    var details = cancel.closest('details[data-chat-edit]');
    if (details) details.open = false;
  });
})();
