// Widget «Firma»: dibuja en un canvas (mouse, dedo o lápiz) y deja el PNG en un campo oculto al enviar el formulario.
// Si no se dibuja nada, el campo queda vacío y el servidor conserva la firma guardada.
(function () {
  'use strict';

  function iniciar(caja) {
    var pizarra = caja.querySelector('[data-reg-firma-pizarra]');
    var lienzo = caja.querySelector('[data-reg-firma-lienzo]');
    var dato = caja.querySelector('[data-reg-firma-dato]');
    if (!pizarra || !lienzo || !dato || !lienzo.getContext) return;
    pizarra.hidden = false;
    var ctx = lienzo.getContext('2d');
    ctx.lineWidth = 3; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#111';
    var dibujando = false, hayTrazo = false;

    function punto(e) {
      var r = lienzo.getBoundingClientRect();
      return { x: (e.clientX - r.left) * lienzo.width / r.width, y: (e.clientY - r.top) * lienzo.height / r.height };
    }
    lienzo.addEventListener('pointerdown', function (e) {
      dibujando = true; lienzo.setPointerCapture(e.pointerId);
      var p = punto(e); ctx.beginPath(); ctx.moveTo(p.x, p.y);
    });
    lienzo.addEventListener('pointermove', function (e) {
      if (!dibujando) return;
      var p = punto(e); ctx.lineTo(p.x, p.y); ctx.stroke(); hayTrazo = true;
    });
    function fin() { dibujando = false; }
    lienzo.addEventListener('pointerup', fin);
    lienzo.addEventListener('pointercancel', fin);

    var limpiar = caja.querySelector('[data-reg-firma-limpiar]');
    if (limpiar) limpiar.addEventListener('click', function () {
      ctx.clearRect(0, 0, lienzo.width, lienzo.height); hayTrazo = false; dato.value = '';
    });
    var form = caja.closest('form');
    if (form) form.addEventListener('submit', function () {
      dato.value = hayTrazo ? lienzo.toDataURL('image/png') : '';
    });
  }

  function arrancar() { document.querySelectorAll('[data-reg-firma]').forEach(iniciar); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arrancar);
  else arrancar();
})();
