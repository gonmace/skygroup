// Modal de opciones del PDF: al generar (el PDF abre en otra pestaña) se cierra, y la página queda como estaba.
(function () {
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.matches || !form.matches('[data-pdf-opciones]')) return;
    var modal = document.getElementById('pdf-opciones');
    if (modal) setTimeout(function () { modal.checked = false; }, 0);
  });
})();
