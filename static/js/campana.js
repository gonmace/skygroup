// Campana de notificaciones en tiempo real. Sin inline scripts (CSP): la URL del WebSocket
// viene en data-campana-ws. Reintenta con espera creciente; sin WebSocket, la campana
// sigue funcionando al recargar la página.
document.addEventListener('DOMContentLoaded', function () {
  var campana = document.querySelector('[data-campana][data-campana-ws]');
  if (!campana) return;
  var contador = campana.querySelector('[data-campana-contador]');
  var espera = 1000;

  function pintar(n) {
    if (!contador) return;
    contador.textContent = n > 0 ? n : '';
    contador.classList.toggle('hidden', !(n > 0));
  }

  function conectar() {
    var proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
    var ws = new WebSocket(proto + location.host + campana.getAttribute('data-campana-ws'));
    ws.onopen = function () { espera = 1000; };
    ws.onmessage = function (e) {
      try { pintar(JSON.parse(e.data).no_leidas); } catch (err) {}
    };
    ws.onclose = function (e) {
      if (e.code === 4401 || e.code === 4403) return;  // sin sesión / sin acceso: no reintentar
      setTimeout(conectar, espera);
      espera = Math.min(espera * 2, 30000);
    };
  }
  conectar();
});
