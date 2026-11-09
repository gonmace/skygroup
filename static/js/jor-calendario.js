// Calendario: clic en un día [data-fecha] rellena la fecha del formulario "Agregar nota". Sin inline (CSP).
(function () {
  'use strict';
  var campo = document.getElementById('id_fecha');
  var texto = document.getElementById('id_texto');
  if (!campo) return;
  document.querySelectorAll('[data-fecha]').forEach(function (celda) {
    celda.addEventListener('click', function (e) {
      if (e.target.closest('a, button')) return;
      campo.value = celda.dataset.fecha;
      if (texto) texto.focus();
    });
  });
})();
