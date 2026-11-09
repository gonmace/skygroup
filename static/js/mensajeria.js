// Mensajería: ventana flotante (#msj) con la lista de conversaciones y el chat en vivo, disponible en todas las
// pantallas sin cambiar de página.
// Sin inline scripts (CSP). El HTML de lista, conversación y mensajes lo genera el servidor; aquí solo se
// pintan, se envían los mensajes por HTTP y se escuchan avisos por WebSocket (ws/empresa/<slug>/mensajes/).
document.addEventListener('DOMContentLoaded', function () {
  var raiz = document.getElementById('msj');
  if (!raiz) return;
  var cont = document.getElementById('msj-contenido');
  var base = raiz.dataset.base;                       // «/<slug>/mensajes/»
  var yo = parseInt(raiz.dataset.yo, 10);
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  var abierto = false, convActual = null, disparador = null;
  var porConv = {}, total = 0;
  var archivos = [];                                  // File[] pendientes del mensaje en redacción
  var cargandoMas = false, enviando = false, timerLista = null, timerBuscar = null, timerMencion = null;
  var menciones = { activa: false, items: [], indice: 0 };

  // ── Utilidades ──────────────────────────────────────────────────────────────────────────────────
  function url(ruta) { return base + ruta; }
  function pedir(ruta, op) {
    op = op || {};
    var cabeceras = { 'X-Requested-With': 'fetch' };
    if (op.method === 'POST') cabeceras['X-CSRFToken'] = csrf;
    return fetch(url(ruta), { method: op.method || 'GET', body: op.body, headers: cabeceras, credentials: 'same-origin' });
  }
  function html(ruta) {
    return pedir(ruta).then(function (r) { if (!r.ok) throw new Error(r.status); return r; });
  }
  function el(sel, desde) { return (desde || cont).querySelector(sel); }
  function guardar() {
    try { sessionStorage.setItem('msj', JSON.stringify({ abierto: abierto, conv: convActual })); } catch (e) {}
  }

  // ── Contadores ──────────────────────────────────────────────────────────────────────────────────
  function pintarContadores() {
    document.querySelectorAll('[data-msj-contador]').forEach(function (b) {
      b.textContent = total > 0 ? (total > 99 ? '99+' : total) : '';
      b.classList.toggle('hidden', !(total > 0));
    });
    document.querySelectorAll('[data-msj-conv-badge]').forEach(function (b) {
      var n = porConv[b.dataset.msjConvBadge] || 0;
      b.textContent = n > 99 ? '99+' : n;
      b.classList.toggle('hidden', !(n > 0));
    });
  }
  function fijarResumen(t, pc) {
    porConv = {};
    Object.keys(pc || {}).forEach(function (k) { porConv[k] = pc[k]; });
    total = t || 0;
    pintarContadores();
  }
  function sumar(conv, n) {
    porConv[conv] = Math.max(0, (porConv[conv] || 0) + n);
    total = Object.keys(porConv).reduce(function (a, k) { return a + porConv[k]; }, 0);
    pintarContadores();
  }
  function ponerCero(conv) { porConv[conv] = 0; sumar(conv, 0); }

  // ── Abrir y cerrar ──────────────────────────────────────────────────────────────────────────────
  function mostrar(si) {
    abierto = si;
    ['translate-y-4', 'opacity-0', 'pointer-events-none'].forEach(function (c) { raiz.classList.toggle(c, !si); });
    if (si) raiz.removeAttribute('inert'); else raiz.setAttribute('inert', '');
    raiz.setAttribute('aria-hidden', si ? 'false' : 'true');
    document.querySelectorAll('[data-accion="mensajeria"]').forEach(function (b) { b.setAttribute('aria-expanded', si ? 'true' : 'false'); });
    guardar();
  }
  function abrir(conv) {
    disparador = document.activeElement;
    mostrar(true);
    if (conv) verConv(conv); else if (convActual) verConv(convActual); else verLista();
  }
  function cerrar() {
    mostrar(false);
    if (disparador && disparador.focus) disparador.focus();
  }

  // ── Lista de conversaciones ─────────────────────────────────────────────────────────────────────
  function listaVisible() { return abierto && !convActual; }
  function verLista() {
    convActual = null; guardar();
    return html('panel/').then(function (r) { return r.text(); }).then(function (t) {
      if (convActual) return;                      // mientras tanto abrieron una conversación
      cont.innerHTML = t;
      pintarContadores();
      var b = el('[data-msj-buscar]'); if (b) b.focus({ preventScroll: true });
    }).catch(function () { cont.textContent = 'No se pudo cargar la mensajería.'; });
  }
  function refrescarLista() {
    if (!listaVisible()) return;
    clearTimeout(timerLista);
    timerLista = setTimeout(function () {
      var buscando = el('[data-msj-buscar]');
      if (buscando && buscando.value) return;      // no pisar una búsqueda en curso
      html('panel/').then(function (r) { return r.text(); }).then(function (t) {
        if (!listaVisible()) return;
        cont.innerHTML = t; pintarContadores();
      }).catch(function () {});
    }, 250);
  }

  // ── Conversación ────────────────────────────────────────────────────────────────────────────────
  function hilo() { return el('#msj-hilo'); }
  function abajo(forzar) {
    var h = hilo(); if (!h) return;
    if (forzar || h.scrollHeight - h.scrollTop - h.clientHeight < 90) h.scrollTop = h.scrollHeight;
  }
  function limpiarDias() {
    var h = hilo(); if (!h) return;
    var previo = null;
    h.querySelectorAll('[data-dia]').forEach(function (d) {
      if (previo === d.dataset.dia) d.remove(); else previo = d.dataset.dia;
    });
  }
  function actualizarVacio() {
    var h = hilo(); if (!h) return;
    var v = el('[data-msj-vacio]');
    if (v) v.classList.toggle('hidden', !!h.querySelector('[data-msj-id]'));
  }
  function verConv(id) {
    convActual = String(id); guardar();
    archivos = []; menciones.activa = false;
    return html('c/' + id + '/').then(function (r) { return r.text(); }).then(function (t) {
      if (convActual !== String(id)) return;
      cont.innerHTML = t;
      limpiarDias(); abajo(true);
      marcarLeido();
      var ta = el('[data-msj-texto]'); if (ta) ta.focus({ preventScroll: true });
    }).catch(function () {
      convActual = null; guardar();
      cont.textContent = 'No se pudo abrir la conversación.';
    });
  }
  function marcarLeido() {
    if (!convActual) return;
    var c = convActual;
    pedir('c/' + c + '/leido/', { method: 'POST' }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.ok) { porConv[c] = 0; total = d.total; pintarContadores(); }
    }).catch(function () {});
  }
  // Agrega al hilo los mensajes del HTML que aún no están (evita duplicados por carrera con el WebSocket).
  function agregar(htmlTxt, alPrincipio) {
    var h = hilo(); if (!h) return 0;
    var lista = el('[data-msj-lista]');
    var tpl = document.createElement('template'); tpl.innerHTML = htmlTxt;
    var nuevos = 0;
    var nodos = Array.prototype.slice.call(tpl.content.children);
    if (alPrincipio) nodos.reverse();
    nodos.forEach(function (n) {
      var id = n.dataset && n.dataset.msjId;
      if (id && lista.querySelector('[data-msj-id="' + id + '"]')) return;
      if (id) nuevos++;
      if (alPrincipio) lista.insertBefore(n, lista.firstChild); else lista.appendChild(n);
    });
    limpiarDias(); actualizarVacio();
    return nuevos;
  }
  function traerNuevos(forzarAbajo) {
    var h = hilo(); if (!h) return Promise.resolve();
    var c = h.dataset.conv;
    return html('c/' + c + '/nuevos/?despues=' + (h.dataset.ultimo || 0)).then(function (r) {
      var ultimo = r.headers.get('X-Ultimo-Id');
      return r.text().then(function (t) {
        if (!hilo() || hilo().dataset.conv !== c) return;
        var cerca = h.scrollHeight - h.scrollTop - h.clientHeight < 90;
        agregar(t, false);
        if (ultimo) h.dataset.ultimo = ultimo;
        if (forzarAbajo || cerca) abajo(true);
      });
    }).catch(function () {});
  }
  function masAntiguos() {
    var h = hilo(); if (!h || cargandoMas || h.dataset.hayMas !== '1') return;
    cargandoMas = true;
    var altura = h.scrollHeight;
    html('c/' + h.dataset.conv + '/antiguos/?antes=' + h.dataset.primero).then(function (r) {
      var hayMas = r.headers.get('X-Hay-Mas') === '1', primero = r.headers.get('X-Primero-Id');
      return r.text().then(function (t) {
        if (!hilo() || hilo() !== h) return;
        agregar(t, true);
        h.dataset.hayMas = hayMas ? '1' : '0';
        if (primero) h.dataset.primero = primero;
        var b = el('[data-msj="mas"]'); if (b) b.classList.toggle('hidden', !hayMas);
        h.scrollTop = h.scrollHeight - altura;        // mantiene lo que se estaba leyendo
      });
    }).catch(function () {}).then(function () { cargandoMas = false; });
  }

  // ── Redacción: adjuntos y envío ─────────────────────────────────────────────────────────────────
  function mostrarError(txt) {
    var e = el('[data-msj-error]'); if (!e) return;
    e.textContent = txt || ''; e.classList.toggle('hidden', !txt);
  }
  function pintarPrevias() {
    var ul = el('[data-msj-previas]'); if (!ul) return;
    ul.innerHTML = '';
    archivos.forEach(function (f, i) {
      var li = document.createElement('li');
      li.className = 'relative flex items-center gap-2 rounded-lg border border-base-content/15 bg-base-200 p-1 pr-7 text-xs';
      if (f.type.indexOf('image/') === 0) {
        var im = document.createElement('img'); im.className = 'size-10 rounded object-cover'; im.alt = '';
        im.src = URL.createObjectURL(f); im.onload = function () { URL.revokeObjectURL(im.src); };
        li.appendChild(im);
      }
      var n = document.createElement('span'); n.className = 'max-w-28 truncate'; n.textContent = f.name; li.appendChild(n);
      var q = document.createElement('button'); q.type = 'button';
      q.className = 'btn btn-ghost btn-circle btn-xs absolute right-0 top-1/2 -translate-y-1/2';
      q.setAttribute('aria-label', 'Quitar ' + f.name); q.textContent = '✕'; q.dataset.msjQuitar = i;
      li.appendChild(q); ul.appendChild(li);
    });
  }
  function sumarArchivos(lista) {
    var form = el('[data-msj-form]'); if (!form) return;
    var max = parseInt(form.dataset.maxAdjuntos, 10) || 5;
    Array.prototype.forEach.call(lista, function (f) {
      if (archivos.length >= max) { mostrarError('Máximo ' + max + ' archivos por mensaje.'); return; }
      archivos.push(f); mostrarError('');
    });
    pintarPrevias();
  }
  function autoaltura(ta) { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 160) + 'px'; }
  function enviar(form) {
    if (enviando) return;
    var ta = el('[data-msj-texto]', form), texto = ta.value.trim();
    if (!texto && !archivos.length) return;
    enviando = true;
    var btn = el('[data-msj-enviar]', form); btn.disabled = true; mostrarError('');
    var fd = new FormData(); fd.append('texto', texto);
    archivos.forEach(function (f) { fd.append('files', f); });
    pedir('c/' + hilo().dataset.conv + '/enviar/', { method: 'POST', body: fd })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (!x.ok || !x.d.ok) { mostrarError(x.d.error || 'No se pudo enviar el mensaje.'); return; }
        ta.value = ''; autoaltura(ta); archivos = []; pintarPrevias(); ocultarMenciones();
        agregar(x.d.html, false); abajo(true);
        traerNuevos(true);                              // por si llegó algo ajeno entre medio
      })
      .catch(function () { mostrarError('Sin conexión: el mensaje no se envió.'); })
      .then(function () { enviando = false; btn.disabled = false; ta.focus(); });
  }

  // ── Edición y borrado de mensajes propios ───────────────────────────────────────────────────────
  function editar(id) {
    var nodo = el('[data-msj-id="' + id + '"]'); if (!nodo) return;
    var burbuja = nodo.querySelector('[data-msj-burbuja]');
    var previo = burbuja.innerHTML;
    var original = (nodo.querySelector('[data-msj-texto-msg]') || {}).textContent || '';
    burbuja.innerHTML = '';
    var ta = document.createElement('textarea');
    ta.className = 'textarea textarea-bordered w-64 max-w-full text-base-content'; ta.rows = 3; ta.value = original;
    var fila = document.createElement('div'); fila.className = 'mt-1 flex justify-end gap-1';
    var ok = document.createElement('button'); ok.type = 'button'; ok.className = 'btn btn-xs btn-success'; ok.textContent = 'Guardar';
    var no = document.createElement('button'); no.type = 'button'; no.className = 'btn btn-xs btn-ghost'; no.textContent = 'Cancelar';
    fila.append(no, ok); burbuja.append(ta, fila); ta.focus();
    no.addEventListener('click', function () { burbuja.innerHTML = previo; });
    ok.addEventListener('click', function () {
      var fd = new FormData(); fd.append('texto', ta.value);
      pedir('m/' + id + '/editar/', { method: 'POST', body: fd }).then(function (r) { return r.json(); }).then(function (d) {
        if (!d.ok) { burbuja.innerHTML = previo; mostrarError(d.error || 'No se pudo editar.'); return; }
        reemplazar(id, d.html);
      }).catch(function () { burbuja.innerHTML = previo; });
    });
  }
  function reemplazar(id, htmlTxt) {
    var nodo = el('[data-msj-id="' + id + '"]'); if (!nodo) return;
    var tpl = document.createElement('template'); tpl.innerHTML = htmlTxt;
    var nuevo = tpl.content.querySelector('[data-msj-id]'); if (nuevo) nodo.replaceWith(nuevo);
  }
  function borrar(id) {
    window.confirmarUI('¿Borrar este mensaje? No se puede deshacer.', { titulo: 'Borrar mensaje', aceptar: 'Borrar' }).then(function (ok) {
      if (!ok) return;
      pedir('m/' + id + '/borrar/', { method: 'POST' }).then(function (r) { return r.json(); }).then(function (d) {
        if (d.ok) { var n = el('[data-msj-id="' + id + '"]'); if (n) n.remove(); limpiarDias(); actualizarVacio(); }
      }).catch(function () { mostrarError('No se pudo borrar el mensaje.'); });
    });
  }

  // ── @menciones ──────────────────────────────────────────────────────────────────────────────────
  function ocultarMenciones() {
    menciones.activa = false;
    var ul = el('[data-msj-menciones]'); if (ul) { ul.classList.add('hidden'); ul.innerHTML = ''; }
  }
  function pintarMenciones() {
    var ul = el('[data-msj-menciones]'); if (!ul) return;
    ul.innerHTML = '';
    if (!menciones.items.length) { ocultarMenciones(); return; }
    menciones.items.forEach(function (p, i) {
      var li = document.createElement('li'); li.setAttribute('role', 'option');
      var a = document.createElement('button'); a.type = 'button'; a.dataset.msjMencion = i;
      a.className = i === menciones.indice ? 'menu-active' : '';
      var n = document.createElement('span'); n.className = 'truncate'; n.textContent = p.nombre;
      var h = document.createElement('span'); h.className = 'ml-auto text-xs opacity-60'; h.textContent = '@' + p.handle;
      a.append(n, h); li.appendChild(a); ul.appendChild(li);
    });
    ul.classList.remove('hidden'); menciones.activa = true;
  }
  function elegirMencion(i) {
    var ta = el('[data-msj-texto]'), p = menciones.items[i]; if (!ta || !p) return;
    var pos = ta.selectionStart, antes = ta.value.slice(0, pos), despues = ta.value.slice(pos);
    var m = /(^|\s)@([\w.\-]*)$/.exec(antes); if (!m) return;
    var inicio = antes.length - m[2].length - 1;
    ta.value = antes.slice(0, inicio) + '@' + p.handle + ' ' + despues;
    var nuevaPos = inicio + p.handle.length + 2;
    ta.setSelectionRange(nuevaPos, nuevaPos); ta.focus(); ocultarMenciones(); autoaltura(ta);
  }
  function buscarMenciones(ta) {
    var antes = ta.value.slice(0, ta.selectionStart);
    var m = /(^|\s)@([\w.\-]*)$/.exec(antes);
    if (!m) { ocultarMenciones(); return; }
    clearTimeout(timerMencion);
    timerMencion = setTimeout(function () {
      html('personas/?c=' + hilo().dataset.conv + '&q=' + encodeURIComponent(m[2])).then(function (r) { return r.json(); })
        .then(function (d) { menciones.items = d.personas; menciones.indice = 0; pintarMenciones(); })
        .catch(ocultarMenciones);
    }, 120);
  }

  // ── Buscar a alguien para un mensaje directo ────────────────────────────────────────────────────
  function buscarPersonas(input) {
    var ul = el('[data-msj-resultados]'); if (!ul) return;
    var q = input.value.trim();
    clearTimeout(timerBuscar);
    if (!q) { ul.classList.add('hidden'); ul.innerHTML = ''; refrescarLista(); return; }
    timerBuscar = setTimeout(function () {
      html('personas/?q=' + encodeURIComponent(q)).then(function (r) { return r.json(); }).then(function (d) {
        ul.innerHTML = '';
        d.personas.forEach(function (p) {
          var li = document.createElement('li'); li.setAttribute('role', 'option');
          var b = document.createElement('button'); b.type = 'button'; b.dataset.msjDm = p.id;
          b.className = 'flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-base-200';
          var av = document.createElement('span'); av.className = 'msj-avatar'; av.textContent = p.iniciales;
          var n = document.createElement('span'); n.className = 'truncate'; n.textContent = p.nombre;
          b.append(av, n); li.appendChild(b); ul.appendChild(li);
        });
        if (!d.personas.length) { var v = document.createElement('li'); v.className = 'px-2 py-1.5 text-sm text-base-content/50'; v.textContent = 'Sin resultados'; ul.appendChild(v); }
        ul.classList.remove('hidden');
      }).catch(function () {});
    }, 200);
  }
  function abrirDirecto(userId) {
    return pedir('directo/' + userId + '/', { method: 'POST' }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.ok) { if (!abierto) { disparador = document.activeElement; mostrar(true); } verConv(d.id); }
    });
  }
  function abrirProyecto(proyectoId) {
    return pedir('proyecto/' + proyectoId + '/', { method: 'POST' }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.ok) { if (!abierto) { disparador = document.activeElement; mostrar(true); } verConv(d.id); }
    });
  }

  // ── Eventos de la interfaz (delegados) ──────────────────────────────────────────────────────────
  document.addEventListener('click', function (e) {
    var t = e.target.closest && e.target.closest('[data-accion="mensajeria"]');
    if (t) { e.preventDefault(); if (abierto) cerrar(); else abrir(); return; }
    var d = e.target.closest && e.target.closest('[data-msj-directo]');
    if (d) { e.preventDefault(); abrirDirecto(d.dataset.msjDirecto); return; }
    var p = e.target.closest && e.target.closest('[data-msj-proyecto]');
    if (p) { e.preventDefault(); abrirProyecto(p.dataset.msjProyecto); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && abierto && !menciones.activa && !document.getElementById('confirmaciones')?.children.length) cerrar();
  });
  cont.addEventListener('click', function (e) {
    var a = e.target.closest('[data-msj], [data-msj-abrir], [data-msj-dm], [data-msj-editar], [data-msj-borrar], [data-msj-quitar], [data-msj-mencion]');
    if (!a) return;
    if (a.dataset.msj === 'cerrar') cerrar();
    else if (a.dataset.msj === 'volver') verLista();
    else if (a.dataset.msj === 'mas') masAntiguos();
    else if (a.dataset.msjAbrir) verConv(a.dataset.msjAbrir);
    else if (a.dataset.msjDm) abrirDirecto(a.dataset.msjDm);
    else if (a.dataset.msjEditar) editar(a.dataset.msjEditar);
    else if (a.dataset.msjBorrar) borrar(a.dataset.msjBorrar);
    else if (a.dataset.msjQuitar) { archivos.splice(parseInt(a.dataset.msjQuitar, 10), 1); pintarPrevias(); }
    else if (a.dataset.msjMencion) elegirMencion(parseInt(a.dataset.msjMencion, 10));
  });
  cont.addEventListener('submit', function (e) {
    if (e.target.matches('[data-msj-form]')) { e.preventDefault(); enviar(e.target); }
  });
  cont.addEventListener('input', function (e) {
    if (e.target.matches('[data-msj-texto]')) { autoaltura(e.target); buscarMenciones(e.target); }
    else if (e.target.matches('[data-msj-buscar]')) buscarPersonas(e.target);
  });
  cont.addEventListener('keydown', function (e) {
    if (!e.target.matches('[data-msj-texto]') || e.isComposing) return;
    if (menciones.activa) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        menciones.indice = (menciones.indice + (e.key === 'ArrowDown' ? 1 : -1) + menciones.items.length) % menciones.items.length;
        pintarMenciones(); return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); elegirMencion(menciones.indice); return; }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); ocultarMenciones(); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar(e.target.form); }
  });
  cont.addEventListener('change', function (e) {
    if (e.target.matches('[data-msj-archivos]')) { sumarArchivos(e.target.files); e.target.value = ''; }
  });
  cont.addEventListener('paste', function (e) {
    if (!e.target.matches('[data-msj-texto]')) return;
    var imgs = Array.prototype.filter.call((e.clipboardData || {}).files || [], function (f) { return f.type.indexOf('image/') === 0; });
    if (imgs.length) { e.preventDefault(); sumarArchivos(imgs); }
  });
  cont.addEventListener('dragover', function (e) { if (e.target.closest('[data-msj-form], #msj-hilo')) e.preventDefault(); });
  cont.addEventListener('drop', function (e) {
    if (!e.target.closest('[data-msj-form], #msj-hilo') || !(e.dataTransfer && e.dataTransfer.files.length)) return;
    e.preventDefault(); sumarArchivos(e.dataTransfer.files);
  });
  cont.addEventListener('scroll', function (e) {
    if (e.target.id === 'msj-hilo' && e.target.scrollTop < 40) masAntiguos();
  }, true);

  // ── WebSocket ───────────────────────────────────────────────────────────────────────────────────
  var espera = 1000;
  function conectar() {
    var proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
    var ws = new WebSocket(proto + location.host + raiz.dataset.ws);
    ws.onopen = function () { espera = 1000; };
    ws.onmessage = function (e) {
      var m; try { m = JSON.parse(e.data); } catch (err) { return; }
      if (m.tipo === 'resumen') {
        fijarResumen(m.total, m.por_conv);
        if (abierto && convActual) traerNuevos(false);   // se pone al día tras reconectar
        refrescarLista();
      } else if (m.tipo === 'mensaje') {
        var propio = m.autor === yo;
        var viendo = abierto && convActual === String(m.conv) && !document.hidden;
        if (viendo) { traerNuevos(false).then(function () { if (!propio) marcarLeido(); }); }
        else if (!propio) sumar(m.conv, 1);
        refrescarLista();
      } else if (m.tipo === 'cambio') {
        if (abierto && convActual === String(m.conv)) {
          html('m/' + m.id + '/').then(function (r) { return r.text(); }).then(function (t) { reemplazar(m.id, t); })
            .catch(function () { var n = el('[data-msj-id="' + m.id + '"]'); if (n) { n.remove(); limpiarDias(); actualizarVacio(); } });
        }
      } else if (m.tipo === 'leida') {
        ponerCero(m.conv);
      }
    };
    ws.onclose = function (e) {
      if (e.code === 4401 || e.code === 4403) return;   // sin sesión / sin acceso: no reintentar
      setTimeout(conectar, espera);
      espera = Math.min(espera * 2, 30000);
    };
  }
  conectar();
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && abierto && convActual) { traerNuevos(false); marcarLeido(); }
  });

  // ── Estado inicial: ?c=<id> / ?msj=1 (enlace de una notificación) o ventana que seguía abierta al navegar ──
  var params = new URLSearchParams(location.search);
  var pedida = params.get('c');
  var valida = pedida && /^\d+$/.test(pedida);
  if (valida || params.has('msj')) {
    params.delete('c'); params.delete('msj');
    history.replaceState(null, '', location.pathname + (params.toString() ? '?' + params : ''));
    abrir(valida ? pedida : null);
  } else {
    try {
      var g = JSON.parse(sessionStorage.getItem('msj') || 'null');
      if (g && g.abierto) { convActual = g.conv; abrir(g.conv); }
    } catch (err) {}
  }
});
