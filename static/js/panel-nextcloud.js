// Panel → Nextcloud → «Probar conexión»: envía la URL del formulario (sin guardar) y muestra cada comprobación como aviso.
(function () {
  'use strict';
  var boton = document.getElementById('nc-probar-conexion');
  var lista = document.getElementById('nc-resultados');
  if (!boton || !lista) return;
  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute('content') : '';
  var TIPOS = { ok: 'success', error: 'error', info: 'info' };
  var progreso = null;
  function quitarProgreso() { if (progreso) { progreso.remove(); progreso = null; } }

  function pintar(resultados) {
    quitarProgreso();
    lista.textContent = '';
    if (!window.avisar) return;
    resultados.forEach(function (r) {
      window.avisar(r.detalle || '', TIPOS[r.estado] || 'info', { titulo: r.titulo });
    });
  }

  boton.addEventListener('click', function () {
    var campo = document.getElementById('id_servidor_url');
    var datos = new FormData();
    datos.append('servidor_url', campo ? campo.value : '');
    boton.disabled = true; boton.classList.add('loading');
    lista.textContent = '';
    quitarProgreso();
    if (window.avisar) progreso = window.avisar('Comprobando…', 'info', { fijo: true });
    fetch(boton.getAttribute('data-url'), {
      method: 'POST', body: datos, credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(function (r) { if (!r.ok) throw new Error('Error ' + r.status); return r.json(); })
      .then(function (d) { pintar(d.resultados || []); })
      .catch(function () { pintar([{ estado: 'error', titulo: 'No se pudo hacer la comprobación', detalle: 'Revisa tu conexión e inténtalo de nuevo.' }]); })
      .then(function () { boton.disabled = false; boton.classList.remove('loading'); });
  });
})();
