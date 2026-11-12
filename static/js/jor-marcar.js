// Marcación de jornada: sesión + ubicación (lo más precisa posible, sin geocerca) + equipo habitual. CSP-safe: sin inline.
(function () {
  'use strict';
  var raiz = document.querySelector('[data-marcar-raiz]');
  if (!raiz) return;
  var csrf = (document.querySelector('input[name=csrfmiddlewaretoken]') || {}).value || '';

  // Celular: puntero táctil principal o User-Agent móvil; el iPad se presenta como Mac pero tiene pantalla táctil.
  var ua = navigator.userAgent;
  var esMovil = (navigator.userAgentData && navigator.userAgentData.mobile) ||
    /Android|iPhone|iPad|iPod|Mobile/i.test(ua) ||
    (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) ||
    (window.matchMedia && matchMedia('(pointer: coarse)').matches && !matchMedia('(any-pointer: fine)').matches);

  // Identificador del equipo: el servidor lo guarda en una cookie; esta copia cubre el iframe de Nextcloud, que puede bloquearla.
  var equipo = '';
  try { equipo = localStorage.getItem('jor_equipo') || ''; } catch (e) { /* almacenamiento bloqueado */ }

  function post(url, fd) {
    return fetch(url, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf } })
      .then(function (r) { return r.json().catch(function () { return { ok: false, error: 'Respuesta no válida del servidor.' }; }); });
  }

  // Ubicación lo más precisa posible: se observa el GPS hasta ~10 s o hasta una lectura de ≤ 20 m; el servidor se queda
  // con la mejor. Sin ninguna lectura no se marca.
  var MAX_MS = 10000, OBJETIVO_M = 20;
  function lecturas() {
    return new Promise(function (resolve, reject) {
      if (!navigator.geolocation) return reject(new Error('Este navegador no permite leer la ubicación.'));
      var out = [], terminado = false, id = null, tope = null;
      function fin(err) {
        if (terminado) return;
        terminado = true;
        navigator.geolocation.clearWatch(id);
        clearTimeout(tope);
        if (out.length) return resolve(out);
        reject(new Error(err && err.code === 1
          ? 'Permite el acceso a tu ubicación en el navegador para poder marcar.'
          : 'No se pudo leer tu ubicación. Revisa que esté activada e inténtalo de nuevo.'));
      }
      id = navigator.geolocation.watchPosition(function (p) {
        out.push({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy, timestamp: p.timestamp });
        if (p.coords.accuracy <= OBJETIVO_M) fin();
      }, function (err) {
        if (err && err.code === 1) fin(err);   // denegado: no tiene sentido seguir esperando
      }, { enableHighAccuracy: true, timeout: MAX_MS, maximumAge: 0 });
      tope = setTimeout(fin, MAX_MS);
    });
  }

  var aviso = raiz.querySelector('[data-marcar-error]');
  function mostrarError(msg) {
    if (!aviso) return alert(msg);
    aviso.textContent = msg;
    aviso.classList.remove('hidden');
  }
  // Con reporte obligatorio, "Finalizar" queda deshabilitado hasta completar realizado y planificado.
  function reporteIncompleto(form) {
    if (!form.hasAttribute('data-exige-reporte')) return false;
    return ['realizado', 'planificado'].some(function (n) {
      var c = form.elements[n];
      return c && !c.value.trim();
    });
  }
  function ocupado(form, si) {
    form.querySelectorAll('button[type=submit]').forEach(function (b) {
      if (window.btnOcupado) window.btnOcupado(b, si);
      b.disabled = si || reporteIncompleto(form) || b.hasAttribute('data-bloqueado');
    });
  }
  raiz.querySelectorAll('form[data-marcar] button[type=submit][disabled]').forEach(function (b) { b.setAttribute('data-bloqueado', ''); });
  raiz.querySelectorAll('form[data-exige-reporte]').forEach(function (form) {
    form.addEventListener('input', function () { ocupado(form, false); });
    ocupado(form, false);
  });

  // ── Iniciar / finalizar ────────────────────────────────────────────────────────────────────────
  raiz.querySelectorAll('form[data-marcar]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (aviso) aviso.classList.add('hidden');
      if (form.hasAttribute('data-exige-reporte')) {  // mínimos de palabras: solo se avisa al pulsar el botón
        var minimos = [['realizado', 10, 'realizadas'], ['planificado', 3, 'planificadas']];
        for (var i = 0; i < minimos.length; i++) {
          var campo = form.elements[minimos[i][0]];
          if (campo && campo.value.trim().split(/\s+/).filter(Boolean).length < minimos[i][1])
            return mostrarError('Las actividades ' + minimos[i][2] + ' deben tener al menos ' + minimos[i][1] + ' palabras.');
        }
      }
      var confirmar = form.getAttribute('data-confirmar-marcar');
      var previo = confirmar && window.confirmarUI ? window.confirmarUI(confirmar) : Promise.resolve(true);
      previo.then(function (ok) {
        if (!ok) return;
        ocupado(form, true);
        return lecturas().then(function (ls) {
          var fd = new FormData(form);
          fd.set('lecturas', JSON.stringify(ls));
          fd.set('tipo', esMovil ? 'movil' : 'pc');
          fd.set('equipo', equipo);
          return post(form.action, fd);
        }).then(function (r) {
          if (r.equipo && r.equipo !== equipo) {
            equipo = r.equipo;
            try { localStorage.setItem('jor_equipo', equipo); } catch (e) { /* almacenamiento bloqueado */ }
          }
          if (r.ok) { location.href = r.url; return; }
          if (r.cambio_equipo) mostrarMotivo(form);
          throw new Error(r.error);
        });
      }).catch(function (e) {
        mostrarError(e && e.message || 'No se pudo marcar.');
      }).then(function () { ocupado(form, false); });
    });
  });

  // Cambio de equipo: el servidor pide un motivo; se muestra el campo (en el de finalizar se crea al vuelo).
  function mostrarMotivo(form) {
    var m = form.querySelector('[data-motivo]');
    if (!m) {
      m = document.createElement('div');
      m.setAttribute('data-motivo', '');
      m.innerHTML = '<label class="mb-1 block text-sm font-medium">Motivo (equipo distinto al habitual)</label>' +
        '<input name="motivo" maxlength="300" class="input input-bordered w-full" placeholder="Ej.: mi computador está en reparación">' +
        '<p class="mt-1 text-xs text-base-content/60">Un revisor deberá aprobarla para que las horas cuenten.</p>';
      form.insertBefore(m, form.querySelector('button[type=submit]'));
    }
    m.classList.remove('hidden');
    var inp = m.querySelector('input');
    if (inp) inp.focus();
  }
})();
