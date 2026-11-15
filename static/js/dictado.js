// Dictado por voz en todos los <textarea> (Web Speech API del navegador: sin servidor ni claves).
// Cada textarea recibe un botón de micrófono; los nuevos que se inserten en la página también (MutationObserver).
// Excluir uno: atributo `data-sin-dictado`. Navegadores sin soporte (Firefox): no se muestra nada.
// Dentro de un iframe (p. ej. «External sites» de Nextcloud) el micrófono exige `allow="microphone"` en el iframe
// del padre; si falta, sale el toast de «sin permiso».
(function () {
  'use strict';
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return;

  var activo = null; // { rec, ta, btn, inicio, fin, previo, parar }

  function lenguaje() {
    var n = (navigator.language || '').toLowerCase();
    return n.indexOf('es') === 0 ? navigator.language : 'es-ES';
  }

  function avisar(texto, tipo) { if (window.avisar) window.avisar(texto, tipo); }

  function icono() {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('class', 'size-4'); svg.setAttribute('aria-hidden', 'true');
    [['rect', { x: 9, y: 2, width: 6, height: 12, rx: 3 }],
     ['path', { d: 'M19 11a7 7 0 0 1-14 0' }],
     ['path', { d: 'M12 18v4' }]].forEach(function (p) {
      var e = document.createElementNS(ns, p[0]);
      Object.keys(p[1]).forEach(function (k) { e.setAttribute(k, p[1][k]); });
      svg.appendChild(e);
    });
    return svg;
  }

  function escribir(a, texto) {
    // Reemplaza el tramo dictado (a.inicio..a.fin) por `texto` y deja el cursor al final.
    var ta = a.ta, v = ta.value;
    var nuevo = v.slice(0, a.inicio) + texto + v.slice(a.fin);
    var max = ta.maxLength;
    if (max > 0 && nuevo.length > max) {
      texto = texto.slice(0, Math.max(0, texto.length - (nuevo.length - max)));
      nuevo = v.slice(0, a.inicio) + texto + v.slice(a.fin);
    }
    ta.value = nuevo;
    a.fin = a.inicio + texto.length;
    ta.setSelectionRange(a.fin, a.fin);
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function detener() {
    if (!activo) return;
    var a = activo; activo = null;
    a.btn.classList.remove('dictado-activo');
    a.btn.setAttribute('aria-pressed', 'false');
    a.btn.title = 'Dictar por voz';
    try { a.rec.stop(); } catch (e) {}
  }

  function capitalizar(ta, pos, texto) {
    var antes = ta.value.slice(0, pos).replace(/\s+$/, '');
    if (antes === '' || /[.?!¿¡\n]$/.test(antes)) return texto.charAt(0).toUpperCase() + texto.slice(1);
    return texto;
  }

  function iniciar(ta, btn) {
    detener();
    var rec = new SR();
    rec.lang = lenguaje(); rec.continuous = true; rec.interimResults = true;
    var pos = ta.selectionEnd == null ? ta.value.length : ta.selectionEnd;
    var a = { rec: rec, ta: ta, btn: btn, inicio: pos, fin: pos };
    activo = a;
    btn.classList.add('dictado-activo'); btn.setAttribute('aria-pressed', 'true'); btn.title = 'Detener dictado';
    var finales = '';

    rec.onresult = function (ev) {
      if (activo !== a) return;
      var provisional = '';
      for (var i = ev.resultIndex; i < ev.results.length; i++) {
        var t = ev.results[i][0].transcript;
        if (ev.results[i].isFinal) finales += t; else provisional += t;
      }
      var texto = (finales + provisional).replace(/^\s+/, '');
      if (!texto) return;
      var sep = a.inicio > 0 && !/\s$/.test(ta.value.slice(0, a.inicio)) ? ' ' : '';
      escribir(a, sep + capitalizar(ta, a.inicio, texto));
    };
    rec.onerror = function (ev) {
      var e = ev.error;
      if (e === 'aborted') return;
      var msg = {
        'not-allowed': ['El navegador no tiene permiso para usar el micrófono. Habilítalo en el candado de la barra de direcciones.', 'error'],
        'service-not-allowed': ['El navegador no tiene permiso para usar el micrófono. Habilítalo en el candado de la barra de direcciones.', 'error'],
        'no-speech': ['No se detectó voz. Vuelve a intentarlo más cerca del micrófono.', 'warning'],
        'audio-capture': ['No se encontró un micrófono en este dispositivo.', 'error'],
        'network': ['El dictado necesita conexión a internet.', 'error']
      }[e] || ['No se pudo dictar (' + e + ').', 'error'];
      avisar(msg[0], msg[1]);
    };
    rec.onend = function () { if (activo === a) detener(); };
    try { rec.start(); } catch (e) { detener(); avisar('No se pudo iniciar el dictado.', 'error'); }
  }

  function mejorar(ta) {
    if (ta.dataset.dictadoListo || ta.hasAttribute('data-sin-dictado')) return;
    if (ta.disabled || ta.readOnly || !ta.parentNode) return;
    ta.dataset.dictadoListo = '1';
    var caja = document.createElement('span');
    caja.className = 'dictado-caja';
    ta.parentNode.insertBefore(caja, ta);
    caja.appendChild(ta);
    ta.classList.add('dictado-con-btn');
    var btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'dictado-btn btn btn-ghost btn-xs btn-circle';
    btn.title = 'Dictar por voz'; btn.setAttribute('aria-label', 'Dictar por voz'); btn.setAttribute('aria-pressed', 'false');
    btn.appendChild(icono());
    // mousedown: que el clic no le quite el foco (ni el cursor) al textarea
    btn.addEventListener('mousedown', function (e) { e.preventDefault(); });
    btn.addEventListener('click', function () {
      if (activo && activo.ta === ta) { detener(); return; }
      ta.focus(); iniciar(ta, btn);
    });
    caja.appendChild(btn);
    if (ta.form) ta.form.addEventListener('submit', function () { if (activo && activo.ta === ta) detener(); });
  }

  function recorrer(raiz) {
    if (raiz.nodeType !== 1) return;
    if (raiz.tagName === 'TEXTAREA') mejorar(raiz);
    else raiz.querySelectorAll('textarea').forEach(mejorar);
  }
  window.dictadoMejorar = function (raiz) { recorrer(raiz || document.body); };

  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') detener(); });

  function arrancar() {
    recorrer(document.body);
    new MutationObserver(function (muts) {
      muts.forEach(function (m) { m.addedNodes.forEach(recorrer); });
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arrancar); else arrancar();
})();
