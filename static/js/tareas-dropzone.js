// Drag & drop de adjuntos. CSP-safe: sin inline.
(function () {
  'use strict';

  // Resalta el área al arrastrar encima y dispara onDrop con los archivos soltados.
  // El ícono/texto (data-dropzone-hint) se oculta mientras se arrastra, como en
  // cualquier recuadro de drop estándar. Usa un contador de profundidad porque
  // dragenter/dragleave burbujean por cada hijo (ícono, texto, miniaturas) — sin el
  // contador el recuadro parpadea al pasar el mouse sobre esos hijos. Mientras se
  // arrastra ocultamos el hint con `invisible` (visibility, no display): si se
  // sacara del flujo (display:none) el recuadro achica su alto, el mouse queda
  // fuera de sus nuevos límites, dispara dragleave → el hint reaparece → el
  // recuadro vuelve a crecer → el mouse vuelve a quedar adentro → dragenter de
  // nuevo — un loop de resize. `invisible` reserva el mismo espacio así el tamaño
  // nunca cambia MIENTRAS se arrastra. Una vez que el drag termina, el estado
  // permanente (ocupa espacio o no, según haya archivos) lo maneja renderPreview()
  // con `hidden` — ahí sí se puede colapsar el espacio porque ya no hay un drag
  // activo reaccionando a la posición del mouse.
  function bindDragHighlight(area, onDrop) {
    var hint = area.querySelector('[data-dropzone-hint]');
    var depth = 0;

    function setActive(active) {
      area.classList.toggle('bg-base-200', active);
      area.classList.toggle('border-primary', active);
      if (hint) hint.classList.toggle('invisible', active);
    }

    area.addEventListener('dragenter', function (e) {
      e.preventDefault();
      depth++;
      setActive(true);
    });
    area.addEventListener('dragover', function (e) {
      e.preventDefault(); // necesario en cada dragover para permitir el drop
    });
    area.addEventListener('dragleave', function (e) {
      e.preventDefault();
      depth = Math.max(0, depth - 1);
      if (depth === 0) setActive(false);
    });
    area.addEventListener('drop', function (e) {
      e.preventDefault();
      depth = 0;
      setActive(false);
      if (e.dataTransfer && e.dataTransfer.files) onDrop(e.dataTransfer.files);
    });
  }

  // [data-dropzone-stage]: solo junta los archivos en el input (ej. imágenes del
  // mensaje de seguimiento) — se suben recién al enviar el form completo.
  // Hay dos stages: móvil (file-input de DaisyUI, sin arrastre) y desktop
  // (dropzone con drag & drop). Solo el stage activo mantiene su input habilitado
  // para evitar submits duplicados/vacíos al cambiar de breakpoint.
  var desktopMQ = window.matchMedia('(min-width: 1024px)');

  function updateInputStates() {
    var isDesktop = desktopMQ.matches;
    var mobile = document.querySelector('[data-dropzone-mobile] [data-dropzone-input]');
    var desktop = document.querySelector('[data-dropzone-desktop] [data-dropzone-input]');
    if (mobile) mobile.disabled = isDesktop;
    if (desktop) desktop.disabled = !isDesktop;
  }
  updateInputStates();
  if (desktopMQ.addEventListener) {
    desktopMQ.addEventListener('change', updateInputStates);
  } else if (desktopMQ.addListener) {
    desktopMQ.addListener(updateInputStates);
  }

  // Colores por extensión, igual que tickets/partials/_attachment.html.
  var EXT_COLORS = {
    doc: 'bg-info/15 text-info', docx: 'bg-info/15 text-info',
    xls: 'bg-success/15 text-success', xlsx: 'bg-success/15 text-success', csv: 'bg-success/15 text-success',
    ppt: 'bg-warning/15 text-warning', pptx: 'bg-warning/15 text-warning',
  };
  var FILE_ICON_PATHS = ['M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z', 'M14 2v6h6'];

  function svg(paths, cls) {
    var ns = 'http://www.w3.org/2000/svg';
    var el = document.createElementNS(ns, 'svg');
    el.setAttribute('class', cls);
    el.setAttribute('viewBox', '0 0 24 24');
    el.setAttribute('fill', 'none');
    el.setAttribute('stroke', 'currentColor');
    el.setAttribute('stroke-width', '2');
    paths.forEach(function (d) {
      var p = document.createElementNS(ns, 'path');
      p.setAttribute('d', d);
      el.appendChild(p);
    });
    return el;
  }

  function removeButton(onRemove) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-error text-white text-[10px] leading-none flex items-center justify-center';
    btn.setAttribute('aria-label', 'Quitar archivo');
    btn.textContent = '✕';
    // preventDefault: el item vive dentro del <label> del dropzone desktop, que
    // abriría el selector de archivos si el click llega a su acción por defecto.
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      onRemove();
    });
    return btn;
  }

  // [data-dropzone-stage]: solo junta los archivos en el input (ej. imágenes/PDF/docs
  // del mensaje de seguimiento) — se suben recién al enviar el form completo. Muestra
  // miniatura para imágenes/PDF y una fila de lista para el resto de los archivos.
  Array.prototype.forEach.call(document.querySelectorAll('[data-dropzone-stage]'), function (area) {
    var input = area.querySelector('[data-dropzone-input]');
    var preview = area.querySelector('[data-dropzone-preview]');
    var hint = area.querySelector('[data-dropzone-hint]');
    if (!input) return;
    var objectUrls = [];

    function clearObjectUrls() {
      objectUrls.forEach(function (u) { URL.revokeObjectURL(u); });
      objectUrls = [];
    }

    function removeAt(index) {
      var dt = new DataTransfer();
      Array.prototype.forEach.call(input.files, function (f, i) {
        if (i !== index) dt.items.add(f);
      });
      input.files = dt.files;
      renderPreview();
    }

    function extOf(name) {
      var i = name.lastIndexOf('.');
      return i === -1 ? '' : name.slice(i + 1).toLowerCase();
    }

    function buildThumb(file, index, isPdf) {
      var wrap = document.createElement('div');
      wrap.className = 'relative';
      if (isPdf) {
        var box = document.createElement('div');
        box.className = 'w-16 h-16 rounded-lg border border-base-300 bg-error/10 text-error flex flex-col items-center justify-center gap-0.5';
        box.title = file.name;
        box.appendChild(svg(FILE_ICON_PATHS, 'w-5 h-5'));
        var tag = document.createElement('span');
        tag.className = 'text-[9px] font-bold';
        tag.textContent = 'PDF';
        box.appendChild(tag);
        wrap.appendChild(box);
      } else {
        var url = URL.createObjectURL(file);
        objectUrls.push(url);
        var img = document.createElement('img');
        img.src = url;
        img.alt = file.name;
        img.title = file.name;
        img.className = 'w-16 h-16 object-cover rounded-lg border border-base-300 bg-base-200';
        wrap.appendChild(img);
      }
      wrap.appendChild(removeButton(function () { removeAt(index); }));
      return wrap;
    }

    function buildListItem(file, index) {
      var wrap = document.createElement('div');
      wrap.className = 'relative inline-flex items-center gap-1.5 bg-base-200 rounded-lg pl-2 pr-4 py-1.5 text-xs max-w-full';

      var iconBox = document.createElement('span');
      var ext = extOf(file.name);
      iconBox.className = 'inline-flex items-center justify-center w-6 h-6 rounded shrink-0 ' + (EXT_COLORS[ext] || 'bg-base-300 text-base-content/60');
      iconBox.appendChild(svg(FILE_ICON_PATHS, 'w-3.5 h-3.5'));
      wrap.appendChild(iconBox);

      var name = document.createElement('span');
      name.className = 'truncate max-w-[10rem]';
      name.textContent = file.name;
      wrap.appendChild(name);

      wrap.appendChild(removeButton(function () { removeAt(index); }));
      return wrap;
    }

    function renderPreview() {
      // hidden (display:none), no invisible: acá no hay un drag activo que dependa
      // del tamaño del recuadro, así que se puede colapsar el espacio del hint.
      if (hint) hint.classList.toggle('hidden', input.files.length > 0);
      if (!preview) return;
      clearObjectUrls();
      preview.textContent = '';
      Array.prototype.forEach.call(input.files, function (file, index) {
        var isImage = file.type.indexOf('image/') === 0;
        var isPdf = file.type === 'application/pdf';
        var node = (isImage || isPdf) ? buildThumb(file, index, isPdf) : buildListItem(file, index);
        preview.appendChild(node);
      });
    }

    function addFiles(newFiles) {
      if (!newFiles || !newFiles.length) return;
      var dt = new DataTransfer();
      Array.prototype.forEach.call(input.files, function (f) { dt.items.add(f); });
      Array.prototype.forEach.call(newFiles, function (f) { dt.items.add(f); });
      input.files = dt.files;
      renderPreview();
    }

    input.addEventListener('change', renderPreview);
    // Drag & drop solo en el stage desktop (pantallas chicas usan file-input).
    if (area.hasAttribute('data-dropzone-desktop')) {
      bindDragHighlight(area, addFiles);
    }
  });
})();
