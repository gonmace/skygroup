// Tabla de avance de obra (Registros). CSP-safe: sin inline. Agrega/quita filas y recalcula en vivo
// acumulado = min(100, anterior + actual), total = incidencia × acumulado / 100. El servidor recalcula al guardar.
(function () {
  'use strict';
  function num(v) { var n = parseFloat(String(v || '').replace(',', '.')); return isNaN(n) ? 0 : n; }
  function f2(n) { return n.toFixed(2); }

  document.querySelectorAll('[data-tabla-avance]').forEach(function (caja) {
    var cuerpo = caja.querySelector('[data-filas]');

    function recalcular() {
      var general = 0, suma = 0;
      cuerpo.querySelectorAll('[data-fila]').forEach(function (fila) {
        var inc = num(fila.querySelector('[data-incidencia]').value);
        var acumulada = Math.min(100, num(fila.getAttribute('data-anterior')) + num(fila.querySelector('[data-actual]').value));
        var total = inc * acumulada / 100;
        fila.querySelector('[data-acumulada]').textContent = f2(acumulada);
        fila.querySelector('[data-total]').textContent = f2(total);
        general += total; suma += inc;
      });
      var tg = caja.querySelector('[data-total-general]'), si = caja.querySelector('[data-suma-incidencia]');
      if (tg) tg.textContent = f2(general);
      if (si) { si.textContent = f2(suma); si.classList.toggle('text-error', Math.abs(suma - 100) >= 0.005 && suma > 0); }
    }

    caja.addEventListener('input', function (e) {
      if (e.target.matches('[data-incidencia], [data-actual]')) recalcular();
    });
    caja.addEventListener('click', function (e) {
      var agregar = e.target.closest('[data-agregar-fila]');
      var quitar = e.target.closest('[data-quitar-fila]');
      if (agregar) {
        var plantilla = caja.querySelector('[data-fila-nueva]');
        var vacio = cuerpo.querySelector('[data-vacio]');
        if (vacio) vacio.remove();
        cuerpo.appendChild(plantilla.content.firstElementChild.cloneNode(true));
        recalcular();
      } else if (quitar) {
        quitar.closest('[data-fila]').remove();
        recalcular();
      }
    });
  });
})();
