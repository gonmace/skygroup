// Registros → Imágenes: selección múltiple, visor y acciones en lote (descargar ZIP, comprimir, eliminar).
// Las acciones pesadas se envían en lotes pequeños para no pasar el tiempo máximo de la petición; el CSRF viene de
// <meta name="csrf-token">.
(function () {
  'use strict';
  var raiz = document.getElementById('imagenes');
  if (!raiz) return;

  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute('content') : '';
  var barra = document.getElementById('imagenes-acciones');
  var contador = document.getElementById('imagenes-contador');
  var todas = document.getElementById('imagenes-todas');

  function checks() { return Array.prototype.slice.call(raiz.querySelectorAll('.imagen-check')); }
  function seleccion() { return checks().filter(function (c) { return c.checked; }).map(function (c) { return c.value; }); }

  function actualizar() {
    var n = seleccion().length, total = checks().length;
    contador.textContent = n;
    barra.classList.toggle('hidden', n === 0);
    barra.classList.toggle('flex', n > 0);
    if (todas) { todas.checked = n > 0 && n === total; todas.indeterminate = n > 0 && n < total; }
    raiz.querySelectorAll('.imagen-ficha').forEach(function (f) {
      var c = f.querySelector('.imagen-check');
      f.classList.toggle('ring-2', c.checked);
      f.classList.toggle('ring-primary', c.checked);
    });
  }

  // Todos los mensajes salen como toast (window.avisar de shell.js); «ok» = éxito.
  function avisar(texto, tipo) { return window.avisar(texto, tipo === 'ok' ? 'success' : tipo); }
  // Tras recargar la lista el toast se perdería: se guarda y se muestra al volver a cargar.
  function avisarTrasRecargar(texto, tipo) {
    try { sessionStorage.setItem('imagenes-aviso', JSON.stringify({ texto: texto, tipo: tipo })); } catch (e) {}
    location.reload();
  }
  // window.avisar se define en shell.js al terminar de cargar la página: se espera a ese evento (su listener va primero).
  document.addEventListener('DOMContentLoaded', function () {
    try {
      var guardado = JSON.parse(sessionStorage.getItem('imagenes-aviso') || 'null');
      if (guardado) { sessionStorage.removeItem('imagenes-aviso'); avisar(guardado.texto, guardado.tipo); }
    } catch (e) {}
  });
  // Mensaje de progreso: un solo toast que se actualiza y se quita al terminar.
  function progreso(texto) {
    var el = window.avisar(texto, 'info', { fijo: true });
    return {
      poner: function (t) { var sp = el.querySelector('span'); if (sp) sp.textContent = t; },
      quitar: function () { el.remove(); }
    };
  }

  function enviar(url, cuerpo) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(cuerpo)
    });
  }

  function lotes(ids, tam) {
    var r = [];
    for (var i = 0; i < ids.length; i += tam) r.push(ids.slice(i, i + tam));
    return r;
  }

  // Envía los ids por lotes, uno tras otro, mostrando el avance. `acumular` suma las cifras de cada respuesta.
  async function porLotes(url, ids, tam, extra, etiqueta) {
    var total = { ok: 0, omitidas: 0, ahorro: 0, sinAhorro: 0, noJpeg: 0 };
    var hechos = 0, prog = progreso(etiqueta + '… 0 de ' + ids.length);
    try {
      for (var lote of lotes(ids, tam)) {
        prog.poner(etiqueta + '… ' + hechos + ' de ' + ids.length);
        var r = await enviar(url, Object.assign({ ids: lote }, extra || {}));
        var d = await r.json().catch(function () { return { success: false, message: 'Respuesta inválida.' }; });
        if (!r.ok || !d.success) throw new Error(d.message || 'Error ' + r.status);
        total.ok += (d.eliminadas || d.comprimidas || 0);
        total.omitidas += d.omitidas || 0;
        total.ahorro += d.ahorro || 0;
        total.sinAhorro += d.sin_ahorro || 0;
        total.noJpeg += d.no_jpeg || 0;
        hechos += lote.length;
      }
    } finally { prog.quitar(); }
    return total;
  }

  function ocupado(si) {
    barra.querySelectorAll('button').forEach(function (b) { b.disabled = si; });
  }

  async function descargar() {
    var ids = seleccion(), max = +raiz.dataset.maxZip;
    if (ids.length > max) return avisar('Para descargar elige como máximo ' + max + ' fotos a la vez.', 'error');
    ocupado(true);
    var prog = progreso('Preparando el ZIP de ' + ids.length + ' foto(s)…');
    try {
      var r = await enviar(raiz.dataset.urlDescargar, { ids: ids });
      if (!r.ok) { var d = await r.json().catch(function () { return {}; }); throw new Error(d.message || 'No se pudo generar el ZIP'); }
      var blob = await r.blob();
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = 'fotos.zip';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
      avisar('ZIP descargado (' + ids.length + ' foto(s)).', 'ok');
    } catch (e) { avisar(e.message, 'error'); } finally { prog.quitar(); ocupado(false); }
  }

  async function comprimir() {
    var ids = seleccion(), cal = parseInt(document.getElementById('imagenes-calidad').value, 10) || 70;
    cal = Math.max(10, Math.min(95, cal));
    if (!await window.confirmarUI('¿Comprimir ' + ids.length + ' foto(s) al ' + cal + ' % de calidad? Se conserva la resolución y el EXIF. ' +
                 'Solo se comprimen las JPEG y nunca queda más pesada que la original.', { titulo: 'Comprimir', aceptar: 'Comprimir' })) return;
    ocupado(true);
    try {
      var t = await porLotes(raiz.dataset.urlComprimir, ids, +raiz.dataset.maxComprimir, { quality: cal }, 'Comprimiendo');
      var texto = t.ok + ' foto(s) comprimida(s), ahorro ' + Math.round(t.ahorro / 1024) + ' KB.' +
        (t.sinAhorro ? ' ' + t.sinAhorro + ' ya estaban optimizadas: recomprimir al ' + cal + ' % no las hace más livianas (prueba una calidad menor).' : '') +
        (t.noJpeg ? ' ' + t.noJpeg + ' no son JPEG (PNG u otro formato): no se tocan.' : '') +
        (t.omitidas ? ' ' + t.omitidas + ' con error.' : '');
      if (t.ok) avisarTrasRecargar(texto, 'success');
      else { avisar(texto, 'warning'); ocupado(false); }   // sin cambios: no se recarga, el aviso queda visible
    } catch (e) { avisar(e.message, 'error'); ocupado(false); }
  }

  async function eliminar() {
    var ids = seleccion();
    if (!await window.confirmarUI('¿Eliminar ' + ids.length + ' foto(s)? Esta acción no se puede deshacer. ' +
                 'Las fotos de registros concluidos no se eliminan.', { titulo: 'Eliminar', aceptar: 'Eliminar', tipo: 'peligro' })) return;
    ocupado(true);
    try {
      var t = await porLotes(raiz.dataset.urlEliminar, ids, +raiz.dataset.maxEliminar, null, 'Eliminando');
      avisarTrasRecargar(t.ok + ' foto(s) eliminada(s)' + (t.omitidas ? '. ' + t.omitidas + ' omitida(s).' : '.'), 'success');
    } catch (e) { avisar(e.message, 'error'); ocupado(false); }
  }

  raiz.addEventListener('change', function (e) {
    if (e.target === todas) checks().forEach(function (c) { c.checked = todas.checked; });
    if (e.target === todas || e.target.classList.contains('imagen-check')) actualizar();
  });

  document.addEventListener('click', function (e) {
    var abrir = e.target.closest('.imagen-abrir');
    if (abrir) {
      document.getElementById('imagenes-visor-img').src = abrir.dataset.src;
      document.getElementById('imagenes-visor-info').textContent = abrir.dataset.info;
      document.getElementById('imagenes-visor').showModal();
      return;
    }
    var b = e.target.closest('[data-accion]');
    if (!b || !barra.contains(b)) return;
    var a = b.dataset.accion;
    if (a === 'todas') { checks().forEach(function (c) { c.checked = true; }); actualizar(); }
    else if (a === 'ninguna') { checks().forEach(function (c) { c.checked = false; }); actualizar(); }
    else if (a === 'descargar') descargar();
    else if (a === 'comprimir') comprimir();
    else if (a === 'eliminar') eliminar();
  });

  actualizar();
})();
