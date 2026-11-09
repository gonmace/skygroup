// Galería de fotos de un registro (Registros). CSP-safe: sin inline. Sube al elegir (cámara o galería) y reordena
// arrastrando (SortableJS vendorizado) guardando el orden por fetch; el CSRF viene de <meta name="csrf-token">.

// «Capturar Imágenes» / «Elegir de la galería»: al elegir el archivo se envía el formulario. Solo viaja el input usado.
document.addEventListener('change', function (e) {
  var input = e.target;
  if (!input || !input.matches || !input.matches('input[data-fotos-auto]') || !input.files || !input.files.length) return;
  var form = input.form;
  if (!form) return;
  Array.prototype.forEach.call(form.querySelectorAll('input[data-fotos-auto]'), function (otro) {
    if (otro !== input) otro.value = '';
  });
  form.style.opacity = '.6';           // evita un segundo toque mientras sube
  form.style.pointerEvents = 'none';
  if (form.requestSubmit) form.requestSubmit(); else form.submit();
});

(function () {
  'use strict';
  var grid = document.querySelector('[data-fotos-grid]');
  if (!grid || typeof Sortable === 'undefined' || grid.getAttribute('data-puede-escribir') !== '1') return;
  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute('content') : '';
  new Sortable(grid, {
    draggable: '[data-foto-id]',
    handle: '[data-foto-asa]',
    animation: 150,
    onEnd: function () {
      var order = Array.prototype.map.call(grid.querySelectorAll('[data-foto-id]'), function (el) {
        return parseInt(el.getAttribute('data-foto-id'), 10);
      });
      fetch(grid.getAttribute('data-orden-url'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify({ order: order })
      }).then(function (r) { if (!r.ok) window.location.reload(); })
        .catch(function () { window.location.reload(); });
    }
  });
})();
