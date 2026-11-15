// Pantallas de administración de APU (Usuarios y Consumo IA): guardado en línea y verificación de tarifas.
// Sin inline scripts (CSP). Los resultados salen como toast.
(function () {
  'use strict';
  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute('content') : '';
  function avisar(t, tipo) { if (window.avisar) window.avisar(t, tipo); }
  function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

  function post(url, datos) {
    return fetch(url, { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(datos || {}) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) {
        var ok = r.ok && d.success !== false;
        if (!ok && !d.message) d.message = 'No se pudo completar la acción.';
        return { ok: ok, data: d };
      }); })
      .catch(function () { return { ok: false, data: { message: 'No hay conexión con el servidor.' } }; });
  }

  document.addEventListener('submit', function (e) {
    var form = e.target.closest('form[data-limite]');
    if (!form) return;
    e.preventDefault();
    var datos = {};
    var campos = Array.prototype.slice.call(form.elements).concat(Array.prototype.slice.call(document.querySelectorAll('[form="' + form.id + '"]')));
    campos.forEach(function (el) {
      if (!el.name) return;
      datos[el.name] = el.type === 'checkbox' ? el.checked : el.value;
    });
    post(form.getAttribute('data-url'), datos).then(function (res) { avisar(res.data.message, res.ok ? 'success' : 'error'); });
  });

  // «Verificar tarifas»: pide las tarifas publicadas y muestra las diferencias; se aplican solo al confirmar.
  var boton = document.querySelector('[data-verificar-tarifas]');
  if (boton) boton.addEventListener('click', function () {
    boton.disabled = true;
    var cargando = window.avisar ? window.avisar('Consultando las tarifas publicadas…', 'info', { fijo: true }) : null;
    post(boton.getAttribute('data-url'), {}).then(function (res) {
      boton.disabled = false;
      if (cargando) cargando.remove();
      avisar(res.data.message, res.ok ? (res.data.cambios && res.data.cambios.length ? 'warning' : 'success') : 'error');
      var zona = document.getElementById('apu-diferencias');
      if (!res.ok || !res.data.cambios || !res.data.cambios.length) { if (zona) zona.classList.add('hidden'); return; }
      zona.classList.remove('hidden');
      zona.innerHTML = '<section class="table-card"><div class="border-b border-base-300 px-5 py-4"><h2 class="text-base font-semibold">Diferencias de tarifa</h2></div>' +
        '<table class="table"><thead><tr><th>Modelo</th><th>Entrada (actual → publicada)</th><th>Salida (actual → publicada)</th></tr></thead><tbody>' +
        res.data.cambios.map(function (c) {
          return '<tr><td class="font-mono text-sm">' + esc(c.modelo) + '</td><td class="tabular-nums">' + (c.actual ? esc(c.actual.entrada) : '—') + ' → <strong>' + esc(c.entrada) + '</strong></td>' +
            '<td class="tabular-nums">' + (c.actual ? esc(c.actual.salida) : '—') + ' → <strong>' + esc(c.salida) + '</strong></td></tr>';
        }).join('') + '</tbody></table><div class="flex justify-end p-4"><button class="btn btn-primary btn-sm" data-aplicar-tarifas>Aplicar las tarifas publicadas</button></div></section>';
      zona.querySelector('[data-aplicar-tarifas]').addEventListener('click', function () {
        post(boton.getAttribute('data-url').replace('verificar', 'aplicar'), { cambios: res.data.cambios, fuente: res.data.fuente }).then(function (r2) {
          avisar(r2.data.message, r2.ok ? 'success' : 'error');
          if (r2.ok) setTimeout(function () { window.location.reload(); }, 900);
        });
      });
    });
  });
})();
