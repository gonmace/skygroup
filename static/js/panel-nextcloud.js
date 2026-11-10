// Panel → Nextcloud → «Probar conexión»: envía la URL del formulario (sin guardar) y pinta las comprobaciones.
(function () {
  'use strict';
  var boton = document.getElementById('nc-probar-conexion');
  var lista = document.getElementById('nc-resultados');
  if (!boton || !lista) return;
  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute('content') : '';
  var ICONOS = { ok: '✔', error: '✘', info: 'ℹ' };
  var CLASES = { ok: 'text-success', error: 'text-error', info: 'text-base-content/70' };

  function pintar(resultados) {
    lista.textContent = '';
    resultados.forEach(function (r) {
      var li = document.createElement('li');
      li.className = 'flex gap-2 ' + (CLASES[r.estado] || '');
      var i = document.createElement('span'); i.setAttribute('aria-hidden', 'true'); i.textContent = ICONOS[r.estado] || '•';
      var t = document.createElement('span');
      var b = document.createElement('strong'); b.textContent = r.titulo; t.appendChild(b);
      if (r.detalle) { var d = document.createElement('span'); d.className = 'ml-1 text-base-content/70'; d.textContent = '— ' + r.detalle; t.appendChild(d); }
      li.appendChild(i); li.appendChild(t); lista.appendChild(li);
    });
  }

  boton.addEventListener('click', function () {
    var campo = document.getElementById('id_servidor_url');
    var datos = new FormData();
    datos.append('servidor_url', campo ? campo.value : '');
    boton.disabled = true; boton.classList.add('loading');
    lista.textContent = 'Comprobando…';
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
