// Widget «Lista» de los pasos: filas numeradas con subir / bajar / quitar y «Agregar».
(function () {
  'use strict';

  function iniciar(caja) {
    var ol = caja.querySelector('[data-reg-lista-filas]');
    var agregar = caja.querySelector('[data-reg-lista-agregar]');
    if (!ol || !agregar) return;
    var max = parseInt(caja.dataset.max, 10) || 200;

    function filas() { return ol.querySelectorAll('[data-reg-lista-fila]'); }
    function actualizar() {
      var todas = filas();
      todas.forEach(function (f, i) {
        f.querySelector('[data-reg-lista-num]').textContent = (i + 1) + '.';
        f.querySelector('[data-reg-lista-subir]').disabled = i === 0;
        f.querySelector('[data-reg-lista-bajar]').disabled = i === todas.length - 1;
      });
      agregar.disabled = todas.length >= max;
    }

    agregar.addEventListener('click', function () {
      var todas = filas();
      if (!todas.length || todas.length >= max) return;
      var nueva = todas[0].cloneNode(true);
      nueva.querySelector('input').value = '';
      ol.appendChild(nueva);
      nueva.querySelector('input').focus();
      actualizar();
    });

    ol.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      var fila = b.closest('[data-reg-lista-fila]');
      if (b.hasAttribute('data-reg-lista-quitar')) {
        if (filas().length > 1) fila.remove(); else fila.querySelector('input').value = '';
      } else if (b.hasAttribute('data-reg-lista-subir') && fila.previousElementSibling) {
        ol.insertBefore(fila, fila.previousElementSibling);
      } else if (b.hasAttribute('data-reg-lista-bajar') && fila.nextElementSibling) {
        ol.insertBefore(fila.nextElementSibling, fila);
      }
      actualizar();
    });

    // Enter en un campo agrega una fila en lugar de enviar el formulario.
    ol.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && e.target.matches('input')) { e.preventDefault(); agregar.click(); }
    });
    actualizar();
  }

  function arrancar() { document.querySelectorAll('[data-reg-lista]').forEach(iniciar); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arrancar);
  else arrancar();
})();
