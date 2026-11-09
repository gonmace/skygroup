// Se carga bloqueante en <head>: fija el tema antes del primer pintado (evita parpadeo).
(function () {
  var guardado = null;
  try { guardado = localStorage.getItem('tema'); } catch (e) {}
  var oscuro = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme', guardado || (oscuro ? 'dark' : 'light'));
})();
