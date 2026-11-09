// Botón «Usar mi ubicación» del widget de ubicación GPS. CSP-safe: sin inline.
(function () {
  'use strict';
  document.querySelectorAll('[data-ubicacion]').forEach(function (caja) {
    var boton = caja.querySelector('[data-usar-gps]');
    if (!boton) return;
    var estado = caja.querySelector('[data-gps-estado]');
    function mensaje(texto) { if (estado) estado.textContent = texto; }
    boton.addEventListener('click', function () {
      if (!navigator.geolocation) { mensaje('Tu navegador no permite obtener la ubicación.'); return; }
      mensaje('Obteniendo ubicación…');
      navigator.geolocation.getCurrentPosition(function (pos) {
        caja.querySelector('[data-lat]').value = pos.coords.latitude.toFixed(6);
        caja.querySelector('[data-lon]').value = pos.coords.longitude.toFixed(6);
        caja.querySelector('[data-acc]').value = Math.round(pos.coords.accuracy);
        mensaje('Ubicación capturada (±' + Math.round(pos.coords.accuracy) + ' m). Guarda el paso.');
      }, function () { mensaje('No se pudo obtener la ubicación (revisa el permiso del navegador).'); },
      { enableHighAccuracy: true, timeout: 20000 });
    });
  });
})();
