// Sincroniza el selector de color nativo con el texto #RRGGBB de los campos de color (sin inline: CSP).
(function () {
  'use strict';
  var HEX = /^#[0-9a-fA-F]{6}$/;
  document.querySelectorAll('[data-campo-color]').forEach(function (caja) {
    var sel = caja.querySelector('[data-color-selector]'), txt = caja.querySelector('[data-color-texto]');
    if (!sel || !txt) return;
    sel.addEventListener('input', function () { txt.value = sel.value.toUpperCase(); sel.classList.remove('opacity-50'); });
    txt.addEventListener('input', function () {
      var v = txt.value.trim();
      if (v && v.charAt(0) !== '#') v = '#' + v;
      if (HEX.test(v)) { sel.value = v.toLowerCase(); sel.classList.remove('opacity-50'); }
      else if (!v) sel.classList.add('opacity-50');
    });
  });
})();
