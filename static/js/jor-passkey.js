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

  var esMovilGlobal = navigator.userAgentData ? navigator.userAgentData.mobile : /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
  // Lecturas de GPS seguidas (maximumAge 0 = siempre frescas). El servidor necesita al menos 2 para validar.
  // Celular: 3 lecturas con GPS de alta precisión. Computador: no tiene GPS (ubicación por Wi-Fi/IP), así que
  // 2 lecturas rápidas y sin alta precisión; pedir más solo la haría esperar más sin mejorar el dato.
  function lecturas() {
    var total = esMovilGlobal ? 3 : 2, espera = esMovilGlobal ? 1200 : 200;
    return new Promise(function (resolve, reject) {
      if (!navigator.geolocation) return reject(new Error('Este navegador no permite leer la ubicación.'));
      var out = [], fallos = 0;
      (function una() {
        navigator.geolocation.getCurrentPosition(function (p) {
          out.push({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy, timestamp: p.timestamp });
          if (out.length >= total) return resolve(out);
          setTimeout(una, espera);
        }, function (err) {
          if (out.length >= 2) return resolve(out);
          // Edge/Windows a veces responde «denegado» o «no disponible» a la primera petición y a la siguiente sí
          // entrega la ubicación: se reintenta un par de veces antes de dar el error (una denegación real falla rápido).
          if (++fallos <= 2) return setTimeout(una, 700);
          reject(new Error(err && err.code === 1
            ? 'Permite el acceso a tu ubicación en el navegador para poder marcar.'
            : 'No se pudo leer tu ubicación. Sal a un lugar abierto e inténtalo de nuevo.'));
        }, { enableHighAccuracy: esMovilGlobal, timeout: 15000, maximumAge: 0 });
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
      b.disabled = si || reporteIncompleto(form);
    });
  }
  raiz.querySelectorAll('form[data-exige-reporte]').forEach(function (form) {
    form.addEventListener('input', function () { ocupado(form, false); });
    ocupado(form, false);
  });

  // ── PC: QR de un solo uso para vincular el celular (el celular lo abre sin sesión y crea su passkey) ──────────
  var bloque = document.querySelector('[data-enlace-vinculo]');
  if (bloque) {
    var btnGen = bloque.querySelector('[data-enlace-generar]'), res = bloque.querySelector('[data-enlace-resultado]'),
        nota = bloque.querySelector('[data-enlace-nota]'), err = bloque.querySelector('[data-enlace-error]'), vigilar = null;
    btnGen.addEventListener('click', function () {
      err.classList.add('hidden');
      if (window.btnOcupado) window.btnOcupado(btnGen, true);
      post(bloque.dataset.url, {}).then(function (r) {
        if (!r.ok) throw new Error(r.error);
        bloque.querySelector('[data-enlace-qr]').src = r.qr;
        bloque.querySelector('#jor-url-vinculo').textContent = r.url;
        res.classList.remove('hidden'); res.classList.add('flex');
        nota.textContent = 'Vale ' + r.minutos + ' minutos y una sola vez.';
        nota.classList.remove('hidden');
        btnGen.textContent = 'Generar otro código';
        clearInterval(vigilar);
        vigilar = setInterval(function () {   // cuando el celular termina, la página se actualiza sola
          fetch(r.estado_url, { credentials: 'same-origin' }).then(function (x) { return x.json(); }).then(function (e) {
            if (e.vinculado) { clearInterval(vigilar); location.href = e.url; }
          }).catch(function () { /* se reintenta */ });
        }, 2500);
      }).catch(function (e) {
        err.textContent = e.message || 'No se pudo generar el código.';
        err.classList.remove('hidden');
      }).then(function () { if (window.btnOcupado) window.btnOcupado(btnGen, false); });
    });
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

  // ── Iniciar desde el PC: QR que abre el celular (firma con su passkey y aporta SU ubicación) ──────────
  var qrTimer = null;
  function detenerQr(form) {
    clearInterval(qrTimer); qrTimer = null;
    var panel = form.querySelector('[data-qr-panel]');
    if (panel) panel.classList.add('hidden');
    form.querySelectorAll('button[type=submit]').forEach(function (b) { if (window.btnOcupado) window.btnOcupado(b, false); else b.disabled = false; });
  }
  function iniciarPorQr(form) {
    var panel = form.querySelector('[data-qr-panel]');
    if (!panel) return;
    if (window.btnOcupado) form.querySelectorAll('button[type=submit]').forEach(function (b) { window.btnOcupado(b, true); });
    var datos = new FormData();
    if (form.elements.proyecto) datos.set('proyecto', form.elements.proyecto.value);
    post(form.dataset.urlQr, datos).then(function (r) {
      if (!r.ok) throw new Error(r.error);
      panel.querySelector('[data-qr-img]').src = r.qr;
      panel.querySelector('#jor-url-qr').textContent = r.url;
      panel.querySelector('[data-qr-nota]').textContent = 'Vale ' + r.minutos + ' minutos y una sola vez.';
      panel.classList.remove('hidden');
      var hasta = Date.now() + r.minutos * 60000;
      clearInterval(qrTimer);
      qrTimer = setInterval(function () {
        fetch(r.estado_url, { credentials: 'same-origin' }).then(function (x) { return x.json(); }).then(function (e) {
          if (e.estado === 'hecha') { clearInterval(qrTimer); location.href = e.url; }
          else if (e.estado !== 'pendiente' || Date.now() > hasta) { detenerQr(form); mostrarError('El código caducó. Vuelve a pulsar «Iniciar jornada».'); }
        }).catch(function () { /* red intermitente: se reintenta en el siguiente ciclo */ });
      }, 2500);
    }).catch(function (e) {
      detenerQr(form);
      mostrarError(e.message || 'No se pudo generar el código.');
    });
  }
  raiz.querySelectorAll('[data-qr-cancelar]').forEach(function (b) {
    b.addEventListener('click', function () { detenerQr(b.closest('form')); });
  });

  // ── Iniciar / finalizar ────────────────────────────────────────────────────────────────────────
  raiz.querySelectorAll('form[data-marcar]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var esMovil = navigator.userAgentData ? navigator.userAgentData.mobile : /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
      // Cerrar desde un computador no pide passkey ni ubicación (no hay GPS ni celular a mano).
      var sinDisp = form.hasAttribute('data-sin-dispositivo') || (form.hasAttribute('data-cierre-sin-passkey-en-pc') && !esMovil);
      if (!sinDisp && !window.PublicKeyCredential) return mostrarError('Este navegador no admite passkeys. Usa Chrome o Safari actualizados.');
      if (aviso) aviso.classList.add('hidden');
      if (form.hasAttribute('data-exige-reporte')) {  // mínimos de palabras: solo se avisa al pulsar el botón
        var minimos = [['realizado', 10, 'realizadas'], ['planificado', 3, 'planificadas']];
        for (var i = 0; i < minimos.length; i++) {
          var campo = form.elements[minimos[i][0]];
          if (campo && campo.value.trim().split(/\s+/).filter(Boolean).length < minimos[i][1])
            return mostrarError('Las actividades ' + minimos[i][2] + ' deben tener al menos ' + minimos[i][1] + ' palabras.');
        }
      }
      if (form.hasAttribute('data-iniciar-qr-en-pc') && !esMovil) return iniciarPorQr(form);
      var confirmar = form.getAttribute('data-confirmar-marcar');
      var previo = confirmar && window.confirmarUI ? window.confirmarUI(confirmar) : Promise.resolve(true);
      previo.then(function (ok) {
        if (!ok) return;
        ocupado(form, true);
        if (sinDisp) {  // PC o sin celular vinculado: solo se puede cerrar; sin passkey, pero la ubicación es obligatoria
          return lecturas().then(function (ls) {
            var fd = new FormData(form);
            fd.set('lecturas', JSON.stringify(ls));
            return post(form.action, fd);
          }).then(function (r) {
            if (r.ok) { location.href = r.url; return; }
            throw new Error(r.error);
          });
        }
        // Primero la firma (challenge) y DESPUÉS las 3 lecturas de GPS: firmar con el QR del celular puede tardar y las
        // lecturas deben ser recientes (≤15 s) al llegar al servidor.
        return post(raiz.dataset.urlDesafio, esMovil ? {} : { pc: '1' }).then(function (r) {
          if (!r.ok) throw new Error(r.error);
          return navigator.credentials.get({ publicKey: opcionesAuth(r.opciones) });
        }).then(function (cred) {
          return lecturas().then(function (ls) {
            var fd = new FormData(form);
            fd.set('credencial', credencialAJson(cred));
            fd.set('lecturas', JSON.stringify(ls));
            fd.set('origen', esMovil ? 'celular' : 'pc');
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
