// Widget «Tabla» de los pasos: botón «Agregar fila» (clona la última fila en blanco) y «Quitar fila».
// Sin el script el formulario sigue funcionando: se ofrecen filas en blanco y cada guardado trae más.
(function () {
  'use strict';

  function vaciar(fila) {
    fila.querySelectorAll('input, select').forEach(function (el) {
      if (el.tagName === 'SELECT') el.selectedIndex = 0; else el.value = '';
    });
  }

  function iniciar(tabla) {
    var cuerpo = tabla.querySelector('[data-reg-tabla-filas]');
    var agregar = tabla.querySelector('[data-reg-tabla-agregar]');
    if (!cuerpo || !agregar) return;
    var max = parseInt(tabla.dataset.max, 10) || 100;
    agregar.hidden = false;

    function filas() { return cuerpo.querySelectorAll('[data-reg-tabla-fila]'); }
    function actualizar() { agregar.disabled = filas().length >= max; }

    agregar.addEventListener('click', function () {
      var todas = filas();
      if (!todas.length || todas.length >= max) return;
      var nueva = todas[todas.length - 1].cloneNode(true);
      vaciar(nueva);
      cuerpo.appendChild(nueva);
      var primero = nueva.querySelector('input, select');
      if (primero) primero.focus();
      actualizar();
    });

    cuerpo.addEventListener('click', function (e) {
      var quitar = e.target.closest('[data-reg-tabla-quitar]');
      if (!quitar) return;
      var fila = quitar.closest('[data-reg-tabla-fila]');
      if (filas().length > 1) fila.remove(); else vaciar(fila);   // la última fila solo se vacía
      actualizar();
    });
    actualizar();
  }

  function arrancar() { document.querySelectorAll('[data-reg-tabla]').forEach(iniciar); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arrancar);
  else arrancar();
})();
