// Filtra una lista de casillas por texto mientras se escribe. CSP-safe: sin inline.
(function () {
  'use strict';
  document.querySelectorAll('[data-filtro-lista]').forEach(function (raiz) {
    var campo = raiz.querySelector('[data-filtro-input]');
    var items = raiz.querySelectorAll('[data-filtro-item]');
    var vacio = raiz.querySelector('[data-filtro-vacio]');
    if (!campo) return;
    campo.addEventListener('input', function () {
      var q = campo.value.trim().toLowerCase(), visibles = 0;
      items.forEach(function (it) {
        var ok = !q || it.textContent.toLowerCase().indexOf(q) !== -1;
        it.classList.toggle('hidden', !ok);
        if (ok) visibles++;
      });
      if (vacio) vacio.classList.toggle('hidden', visibles !== 0);
    });
    campo.addEventListener('keydown', function (e) { if (e.key === 'Enter') e.preventDefault(); });
  });
})();
