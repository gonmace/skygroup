// Visor de fotos de Registros: al tocar una miniatura (enlace a /registros/fotos/<id>/imagen/) se abre en un modal
// que ocupa casi toda la pantalla, en vez de otra pestaña. Cierra con ✕, clic fuera, Esc; ←/→ navegan entre las fotos.
// CSP-safe: sin inline; el <dialog> se crea aquí.
(function () {
  'use strict';
  var RUTA = /\/registros\/fotos\/\d+\/imagen\/$/;
  var dlg, img, enlaces = [], idx = 0;

  function crear() {
    dlg = document.createElement('dialog');
    dlg.className = 'm-auto max-h-none max-w-none overflow-visible bg-transparent p-0 backdrop:bg-black/80';
    dlg.setAttribute('aria-label', 'Imagen');
    dlg.innerHTML =
      '<div style="width:96vw;height:94vh" class="relative flex items-center justify-center">' +
      '<img alt="" style="max-width:100%;max-height:100%" class="rounded-lg object-contain shadow-2xl">' +
      '<button type="button" data-v="cerrar" aria-label="Cerrar" class="btn btn-circle btn-sm absolute right-2 top-2">✕</button>' +
      '<button type="button" data-v="ant" aria-label="Anterior" class="btn btn-circle absolute left-2 top-1/2 -translate-y-1/2">‹</button>' +
      '<button type="button" data-v="sig" aria-label="Siguiente" class="btn btn-circle absolute right-2 top-1/2 -translate-y-1/2">›</button>' +
      '</div>';
    img = dlg.querySelector('img');
    dlg.addEventListener('click', function (e) {
      var v = e.target.getAttribute && e.target.getAttribute('data-v');
      if (v === 'ant') mover(-1);
      else if (v === 'sig') mover(1);
      else if (v === 'cerrar' || e.target === dlg || e.target === dlg.firstChild) dlg.close();
    });
    dlg.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowLeft') mover(-1);
      else if (e.key === 'ArrowRight') mover(1);
    });
    dlg.addEventListener('close', function () { img.removeAttribute('src'); });
    document.body.appendChild(dlg);
  }

  function mostrar() {
    var a = enlaces[idx];
    var mini = a.querySelector('img');
    img.alt = mini ? mini.alt : '';
    img.src = a.href;
    var multiple = enlaces.length > 1;
    dlg.querySelector('[data-v=ant]').hidden = !multiple;
    dlg.querySelector('[data-v=sig]').hidden = !multiple;
  }

  function mover(d) {
    idx = (idx + d + enlaces.length) % enlaces.length;
    mostrar();
  }

  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || !RUTA.test(a.pathname) || typeof HTMLDialogElement === 'undefined') return;
    e.preventDefault();
    if (!dlg) crear();
    // Navegación: las fotos de la misma página (sin repetir la misma imagen).
    var vistos = {};
    enlaces = Array.prototype.filter.call(document.querySelectorAll('a[href]'), function (x) {
      if (!RUTA.test(x.pathname) || vistos[x.pathname]) return false;
      vistos[x.pathname] = 1; return true;
    });
    idx = Math.max(0, enlaces.findIndex(function (x) { return x.pathname === a.pathname; }));
    if (!enlaces.length) enlaces = [a];
    mostrar();
    dlg.showModal();
  });
})();
