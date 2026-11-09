// Editor de anotaciones sobre imágenes del chat de seguimiento.
// Al hacer click en el botón "lápiz" dentro del modal de imagen, monta un <canvas>
// sobre la imagen y permite dibujar a mano alzada. Al guardar, POSTea el PNG a la
// vista attachment_annotate, que publica la imagen anotada como un mensaje nuevo
// del chat a nombre de quien anota.
// CSP-safe: sin inline.
(function () {
  'use strict';

  var csrf = document.querySelector('meta[name="csrf-token"]');
  // Django pone el token en un input dentro de cada form; acá usamos el del form de
  // chat si existe, sino tiramos de cookie (fallback). Más simple: leer de un meta.
  // Como la app no lo tenga, lo obtenemos de cualquier form presente al final.
  function getCSRF() {
    if (csrf) return csrf.getAttribute('content');
    var input = document.querySelector('[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  function showReloadOverlay(modal) {
    var box = modal.querySelector('.modal-box');
    if (!box) return;
    var overlay = document.createElement('div');
    overlay.className =
      'absolute inset-0 flex items-center justify-center bg-base-100/80 rounded-lg z-20';
    overlay.innerHTML = '<span class="loading loading-spinner loading-lg text-primary"></span>';
    box.appendChild(overlay);
  }

  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest('[data-annotate-btn]');
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();

    var modal = btn.closest('.modal');
    if (!modal) return;
    var img = modal.querySelector('img');
    if (!img) return;

    // Bsca la URL de guardado desde data-annotate-url.
    var saveUrl = btn.getAttribute('data-annotate-url');
    if (!saveUrl) return;

    startEditing(modal, img, saveUrl);
  });

  function startEditing(modal, img, saveUrl) {
    // Evita inicializar dos veces.
    if (modal.querySelector('[data-annotate-canvas]')) return;

    // Reemplaza el <img> por un contenedor relativo con el <canvas> encima.
    var wrap = document.createElement('div');
    wrap.className = 'relative inline-block max-w-full';
    img.parentNode.insertBefore(wrap, img);
    wrap.appendChild(img);
    img.className = img.className + ' max-w-full max-h-[85vh] rounded-lg mx-auto block select-none';
    img.draggable = false;

    var canvas = document.createElement('canvas');
    canvas.setAttribute('data-annotate-canvas', '');
    canvas.className =
      'absolute inset-0 w-full h-full rounded-lg cursor-crosshair touch-none';

    // Tamaño del canvas = tamaño renderizado del img.
    function syncSize() {
      var r = img.getBoundingClientRect();
      // Intrinsic pixel size of the canvas matches the displayed image size.
      canvas.width = Math.round(r.width);
      canvas.height = Math.round(r.height);
      canvas.style.width = r.width + 'px';
      canvas.style.height = r.height + 'px';
      // El canvas se posiciona sobre el img usando estilo absolute inset-0 (Tailwind).
    }
    syncSize();
    wrap.appendChild(canvas);

    // Asegurar refresco al cambiar el tamaño de la ventana o la carga del img.
    if (!img.complete) img.addEventListener('load', syncSize, { once: true });
    window.addEventListener('resize', syncSize);

    var ctx = canvas.getContext('2d');
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = '#E4002B'; // primary (rojo Coca-Cola)
    ctx.lineWidth = 3;

    var drawing = false;
    var lastX = 0;
    var lastY = 0;

    function getPos(e) {
      var r = canvas.getBoundingClientRect();
      var t = e.touches ? e.touches[0] : e;
      return {
        x: (t.clientX - r.left) * (canvas.width / r.width),
        y: (t.clientY - r.top) * (canvas.height / r.height),
      };
    }

    function down(e) {
      e.preventDefault();
      drawing = true;
      var p = getPos(e);
      lastX = p.x;
      lastY = p.y;
      // Dibuja un punto inicial.
      ctx.beginPath();
      ctx.moveTo(lastX, lastY);
      ctx.lineTo(lastX + 0.01, lastY + 0.01);
      ctx.stroke();
    }

    function move(e) {
      if (!drawing) return;
      e.preventDefault();
      var p = getPos(e);
      ctx.beginPath();
      ctx.moveTo(lastX, lastY);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      lastX = p.x;
      lastY = p.y;
    }

    function up(e) {
      if (!drawing) return;
      drawing = false;
    }

    canvas.addEventListener('mousedown', down);
    canvas.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
    canvas.addEventListener('touchstart', down, { passive: false });
    canvas.addEventListener('touchmove', move, { passive: false });
    canvas.addEventListener('touchend', up);

    // Barra de herramientas (limpiar, color, tamaño, guardar, cancelar).
    var toolbar = document.createElement('div');
    toolbar.className =
      'absolute top-2 right-2 flex items-center gap-1 bg-base-100/90 border border-base-300 rounded-lg p-1 shadow-lg text-xs';
    toolbar.innerHTML = '';
    toolbar.appendChild(colorBtn('#E4002B'));
    toolbar.appendChild(colorBtn('#3B82F6'));
    toolbar.appendChild(colorBtn('#10B981'));
    toolbar.appendChild(colorBtn('#FACC15'));
    toolbar.appendChild(divider());
    toolbar.appendChild(strokeBtn(2));
    toolbar.appendChild(strokeBtn(4));
    toolbar.appendChild(strokeBtn(8));
    toolbar.appendChild(divider());
    toolbar.appendChild(actionBtn('Limpiar', function () {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }));
    var save = actionBtn('Guardar', function () { saveAnnotated(modal, canvas, saveUrl, btnSave); });
    var btnSave = save;
    btnSave.className =
      'btn btn-success btn-xs';
    toolbar.appendChild(btnSave);
    var cancel = actionBtn('Cancelar', function () {
      cleanup();
    });
    cancel.className = 'btn btn-ghost btn-xs';
    toolbar.appendChild(cancel);
    wrap.appendChild(toolbar);

    function colorBtn(c) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'w-5 h-5 rounded-full border border-base-300';
      b.style.backgroundColor = c;
      b.title = 'Color';
      b.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        ctx.strokeStyle = c;
      });
      return b;
    }

    function strokeBtn(w) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn btn-ghost btn-xs px-1';
      b.textContent = w;
      b.title = 'Trazo ' + w + 'px';
      b.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        ctx.lineWidth = w;
      });
      return b;
    }

    function actionBtn(label, fn) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn btn-ghost btn-xs';
      b.textContent = label;
      b.addEventListener('click', fn);
      return b;
    }

    function divider() {
      var d = document.createElement('span');
      d.className = 'w-px h-5 bg-base-300 mx-0.5';
      return d;
    }

    function saveAnnotated(modal, canvas, url, btn) {
      btn.disabled = true;
      // Spinner: reemplaza el contenido del botón mientras dura el guardado.
      var btnLabel = btn.textContent;
      btn.innerHTML = '<span class="loading loading-spinner loading-xs"></span> Guardando…';
      // Componer la imagen final: primero dibuja la imagen original, luego las
      // anotaciones del canvas encima. Usamos un segundo canvas fuera del DOM.
      var outCanvas = document.createElement('canvas');
      outCanvas.width = img.naturalWidth || canvas.width;
      outCanvas.height = img.naturalHeight || canvas.height;
      var out = outCanvas.getContext('2d');
      // Escala el trazo del canvas-overlay al tamaño natural del img.
      var sx = outCanvas.width / canvas.width;
      var sy = outCanvas.height / canvas.height;
      out.drawImage(img, 0, 0, outCanvas.width, outCanvas.height);
      out.drawImage(canvas, 0, 0, canvas.width, canvas.height, 0, 0, outCanvas.width, outCanvas.height);
      outCanvas.toBlob(function (blob) {
        if (!blob) {
          btn.disabled = false;
          btn.textContent = btnLabel;
          if (window.Alert) Alert.show('No se pudo generar la imagen.', 'error');
          return;
        }
        var fd = new FormData();
        fd.append('image', blob, 'anotacion.png');
        fd.append('csrfmiddlewaretoken', getCSRF());
        fetch(url, {
          method: 'POST',
          body: fd,
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.ok) {
              if (window.Alert) Alert.show('Anotación enviada al chat.', 'success');
              // No hacer cleanup(): dejaría ver la imagen sin anotar mientras se espera
              // la recarga, dando la sensación de que la edición se perdió/quedó colgado.
              // En cambio se tapa todo con un spinner hasta que la página nueva llegue.
              showReloadOverlay(modal);
              window.location.reload();
            } else {
              btn.disabled = false;
              btn.textContent = btnLabel;
              if (window.Alert) Alert.show(data.error || 'No se pudo guardar.', 'error');
            }
          })
          .catch(function () {
            btn.disabled = false;
            btn.textContent = btnLabel;
            if (window.Alert) Alert.show('No se pudo guardar.', 'error');
          });
      }, 'image/png');
    }

    function cleanup() {
      // Restaura el DOM: remueve canvas, toolbar y el wrap.
      canvas.remove();
      toolbar.remove();
      img.className = img.className.replace('max-w-full max-h-[85vh] rounded-lg mx-auto block select-none', '').trim();
      img.className = (img.className + ' max-w-full max-h-[85vh] rounded-lg mx-auto').trim();
      img.draggable = true;
      // Mueve el img fuera del wrap y elimina el wrap.
      wrap.parentNode.insertBefore(img, wrap);
      wrap.remove();
    }
  }
})();