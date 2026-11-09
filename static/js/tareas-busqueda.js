// Búsqueda/filtros del tablero de Tareas en vivo (AJAX). CSP-safe: sin inline.
// Expone window.refreshBoard() para que kanban.js pueda re-pedir el fragmento tras un
// drag exitoso (SortableJS solo mueve el nodo DOM que ya tenía — no alcanza para
// reflejar fusiones/separaciones de cards multiproducto, hace falta HTML fresco).
(function () {
  'use strict';
  var form = document.querySelector('[data-board-filters]');
  var board = document.querySelector('[data-kanban]');
  if (!board) return;
  var fragmentUrl = board.getAttribute('data-fragment-url');
  var timer = null;

  function currentParams() {
    var params = new URLSearchParams();
    if (!form) return params.toString();
    Array.prototype.forEach.call(form.elements, function (el) {
      if (el.name && el.value) params.append(el.name, el.value);
    });
    return params.toString();
  }

  function refresh() {
    var qs = currentParams();
    return fetch(fragmentUrl + (qs ? '?' + qs : ''), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        board.innerHTML = html;
        if (window.initKanban) window.initKanban();
        // reflejar el filtro en la URL sin recargar
        try { history.replaceState(null, '', qs ? '?' + qs : location.pathname); } catch (e) {}
      })
      .catch(function () {});
  }

  window.refreshBoard = refresh;

  if (form) {
    // Evitar el submit normal (recarga) — filtramos por AJAX.
    form.addEventListener('submit', function (e) { e.preventDefault(); refresh(); });

    // Búsqueda con debounce; selects al cambiar.
    Array.prototype.forEach.call(form.querySelectorAll('input[type="search"]'), function (input) {
      input.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(refresh, 300);
      });
    });
    Array.prototype.forEach.call(form.querySelectorAll('select'), function (sel) {
      sel.addEventListener('change', refresh);
    });

    // "Limpiar" → reset + refresh sin recargar.
    var clear = form.querySelector('[data-board-clear]');
    if (clear) {
      clear.addEventListener('click', function (e) {
        e.preventDefault();
        form.reset();
        refresh();
      });
    }
  }
})();
