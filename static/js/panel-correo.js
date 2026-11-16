// Plataforma → Correo: «Probar conexión» y «Enviar correo de prueba» con lo que hay en el formulario (sin guardar).
(function () {
  'use strict';
  var form = document.getElementById('correo-form');
  var resultado = document.getElementById('correo-resultado');
  var botones = [document.getElementById('correo-probar-conexion'), document.getElementById('correo-probar-envio')];
  if (!form || !resultado || !botones[0]) return;
  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute('content') : '';

  var progreso = null;
  function quitarProgreso() { if (progreso) { progreso.remove(); progreso = null; } }
  function mostrar(ok, texto) {
    quitarProgreso();
    resultado.textContent = '';
    if (window.avisar) window.avisar(texto, ok ? 'success' : 'error', { titulo: ok ? 'Prueba correcta' : 'La prueba falló' });
  }

  function probar(accion, url) {
    var datos = new FormData();
    ['host', 'puerto', 'seguridad', 'usuario', 'password', 'remitente', 'remitente_nombre'].forEach(function (n) {
      var c = form.elements[n];
      datos.append(n, c ? c.value : '');
    });
    datos.append('accion', accion);
    datos.append('destino', document.getElementById('correo-destino').value);
    botones.forEach(function (b) { b.disabled = true; });
    quitarProgreso();
    if (window.avisar) progreso = window.avisar(accion === 'envio' ? 'Enviando…' : 'Conectando…', 'info', { fijo: true });
    fetch(url, { method: 'POST', body: datos, credentials: 'same-origin',
                 headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { if (!r.ok) throw new Error('Error ' + r.status); return r.json(); })
      .then(function (d) { mostrar(d.ok, d.mensaje); })
      .catch(function () { mostrar(false, 'No se pudo hacer la prueba. Revisa tu conexión e inténtalo de nuevo.'); })
      .then(function () { botones.forEach(function (b) { b.disabled = false; }); });
  }

  botones[0].addEventListener('click', function () { probar('conexion', botones[0].getAttribute('data-url')); });
  botones[1].addEventListener('click', function () { probar('envio', botones[1].getAttribute('data-url')); });
})();
