// Filtro de búsqueda para listas de checkboxes (ejecutores/expertos). CSP-safe: sin inline.
(function () {
  'use strict';
  Array.prototype.forEach.call(document.querySelectorAll('[data-multiselect]'), function (box) {
    var search = box.querySelector('[data-multiselect-search]');
    var items = box.querySelectorAll('[data-multiselect-item]');
    var counter = box.querySelector('[data-multiselect-count]');

    function updateCount() {
      if (!counter) return;
      var n = 0;
      Array.prototype.forEach.call(items, function (it) {
        var cb = it.querySelector('input[type=checkbox]');
        if (cb && cb.checked) n++;
      });
      counter.textContent = n ? (n + ' seleccionado' + (n > 1 ? 's' : '')) : 'ninguno';
    }

    if (search) {
      search.addEventListener('input', function () {
        var q = search.value.trim().toLowerCase();
        Array.prototype.forEach.call(items, function (it) {
          var txt = (it.getAttribute('data-label') || it.textContent).toLowerCase();
          it.classList.toggle('hidden', q !== '' && txt.indexOf(q) === -1);
        });
      });
    }
    box.addEventListener('change', updateCount);
    updateCount();
  });
})();
