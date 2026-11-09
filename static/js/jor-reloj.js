// Tiempo transcurrido de la jornada en curso: [data-jor-reloj="<ISO>"] se actualiza cada 30 s. Sin inline (CSP).
(function () {
  'use strict';
  var nodos = document.querySelectorAll('[data-jor-reloj]');
  if (!nodos.length) return;
  function texto(ms) {
    var min = Math.max(0, Math.floor(ms / 60000)), h = Math.floor(min / 60), m = min % 60;
    return h ? h + ' h ' + m + ' min' : m + ' min';
  }
  function pintar() {
    nodos.forEach(function (n) {
      var t = Date.parse(n.dataset.jorReloj);
      if (!isNaN(t)) n.textContent = texto(Date.now() - t);
    });
  }
  pintar();
  setInterval(pintar, 30000);
})();
