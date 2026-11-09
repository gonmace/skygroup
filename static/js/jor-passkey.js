// Marcación de jornada desde el celular: passkey (huella/PIN del teléfono) + lecturas de GPS. CSP-safe: sin inline.
(function () {
  'use strict';
  var raiz = document.querySelector('[data-marcar-raiz]');
  if (!raiz) return;
  var csrf = (document.querySelector('input[name=csrfmiddlewaretoken]') || {}).value || '';

  function b64uABuf(s) {
    s = s.replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    var bin = atob(s), buf = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return buf.buffer;
  }
  function bufAB64u(b) {
    var bytes = new Uint8Array(b), s = '';
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function post(url, datos) {
    // Sin campos, un FormData viaja como multipart vacío y el servidor lo rechaza con 400: se usa urlencoded.
    var fd = datos instanceof FormData ? datos : new URLSearchParams();
    if (!(datos instanceof FormData)) Object.keys(datos || {}).forEach(function (k) { fd.append(k, datos[k]); });
    return fetch(url, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf } })
      .then(function (r) { return r.json().catch(function () { return { ok: false, error: 'Respuesta no válida del servidor.' }; }); });
  }

  // 3 lecturas de GPS seguidas (maximumAge 0 = siempre frescas). Se necesitan al menos 2 para validar.
  function lecturas() {
    return new Promise(function (resolve, reject) {
      if (!navigator.geolocation) return reject(new Error('Este navegador no permite leer la ubicación.'));
      var out = [], intentos = 0;
      (function una() {
        navigator.geolocation.getCurrentPosition(function (p) {
          out.push({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy, timestamp: p.timestamp });
          if (out.length >= 3) return resolve(out);
          setTimeout(una, 1200);
        }, function (err) {
          if (out.length >= 2) return resolve(out);
          reject(new Error(err && err.code === 1
            ? 'Permite el acceso a tu ubicación en el navegador para poder marcar.'
            : 'No se pudo leer tu ubicación. Sal a un lugar abierto e inténtalo de nuevo.'));
        }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
        intentos++;
      })();
    });
  }

  function opcionesCreacion(o) {
    o.challenge = b64uABuf(o.challenge);
    o.user.id = b64uABuf(o.user.id);
    (o.excludeCredentials || []).forEach(function (c) { c.id = b64uABuf(c.id); });
    return o;
  }
  function opcionesAuth(o) {
    o.challenge = b64uABuf(o.challenge);
    (o.allowCredentials || []).forEach(function (c) { c.id = b64uABuf(c.id); });
    return o;
  }
  function credencialAJson(c, extra) {
    var r = c.response, out = { id: c.id, rawId: bufAB64u(c.rawId), type: c.type,
      authenticatorAttachment: c.authenticatorAttachment || null, clientExtensionResults: {}, response: {} };
    out.response.clientDataJSON = bufAB64u(r.clientDataJSON);
    if (r.attestationObject) {
      out.response.attestationObject = bufAB64u(r.attestationObject);
      if (r.getTransports) out.response.transports = r.getTransports();
    } else {
      out.response.authenticatorData = bufAB64u(r.authenticatorData);
      out.response.signature = bufAB64u(r.signature);
      if (r.userHandle) out.response.userHandle = bufAB64u(r.userHandle);
    }
    return JSON.stringify(out);
  }

  var aviso = raiz.querySelector('[data-marcar-error]');
  function mostrarError(msg) {
    if (!aviso) return alert(msg);
    aviso.textContent = msg;
    aviso.classList.remove('hidden');
  }
  function ocupado(form, si) {
    form.querySelectorAll('button[type=submit]').forEach(function (b) { b.disabled = si; b.classList.toggle('loading', si); });
  }

  // ── Vincular este celular ──────────────────────────────────────────────────────────────────────
  var vincular = raiz.querySelector('[data-vincular]');
  if (vincular) vincular.addEventListener('click', function () {
    if (!window.PublicKeyCredential) return mostrarError('Este navegador no admite passkeys. Usa Chrome o Safari actualizados.');
    vincular.disabled = true;
    post(raiz.dataset.urlOpciones, {}).then(function (r) {
      if (!r.ok) throw new Error(r.error);
      return navigator.credentials.create({ publicKey: opcionesCreacion(r.opciones) });
    }).then(function (cred) {
      return post(raiz.dataset.urlVincular, { credencial: credencialAJson(cred), nombre: navigator.platform || 'Celular' });
    }).then(function (r) {
      if (!r.ok) throw new Error(r.error);
      location.href = r.url;
    }).catch(function (e) {
      vincular.disabled = false;
      mostrarError(e && e.name === 'NotAllowedError' ? 'Se canceló la verificación del celular.' : (e.message || 'No se pudo vincular.'));
    });
  });

  // ── Iniciar / finalizar ────────────────────────────────────────────────────────────────────────
  raiz.querySelectorAll('form[data-marcar]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!window.PublicKeyCredential) return mostrarError('Este navegador no admite passkeys. Usa Chrome o Safari actualizados.');
      if (aviso) aviso.classList.add('hidden');
      var confirmar = form.getAttribute('data-confirmar-marcar');
      var previo = confirmar && window.confirmarUI ? window.confirmarUI(confirmar) : Promise.resolve(true);
      previo.then(function (ok) {
        if (!ok) return;
        ocupado(form, true);
        // Primero la ubicación (3 lecturas) y justo antes de firmar, el challenge: así no caduca mientras se lee el GPS.
        return lecturas().then(function (ls) {
          return post(raiz.dataset.urlDesafio, {}).then(function (r) {
            if (!r.ok) throw new Error(r.error);
            return navigator.credentials.get({ publicKey: opcionesAuth(r.opciones) });
          }).then(function (cred) {
            var fd = new FormData(form);
            fd.set('credencial', credencialAJson(cred));
            fd.set('lecturas', JSON.stringify(ls));
            return post(form.action, fd);
          });
        }).then(function (r) {
          if (r.ok) { location.href = r.url; return; }
          var m = raiz.querySelector('[data-motivo]');
          if (r.motivo_requerido && m) m.classList.remove('hidden');
          throw new Error(r.error);
        });
      }).catch(function (e) {
        mostrarError(e && e.name === 'NotAllowedError' ? 'Se canceló la verificación del celular.' : (e.message || 'No se pudo marcar.'));
      }).then(function () { ocupado(form, false); });
    });
  });
})();
