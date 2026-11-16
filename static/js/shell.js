// Confirmación como alerta tipo toast arriba a la derecha (igual que el sitio original).
// window.confirmarUI(msg, {titulo, aceptar, cancelar}) → Promise<boolean>.
// Spinner estándar: window.spinnerHTML(tam) → '<span class="loading loading-spinner loading-{tam}">' (tam: xs|sm|md|lg).
// window.btnOcupado(btn, si) pone/quita el spinner al inicio del botón y lo deshabilita; no toca su texto.
(function () {
  window.spinnerHTML = function (tam) {
    return '<span class="loading loading-spinner loading-' + (tam || 'sm') + '" aria-hidden="true"></span>';
  };
  window.btnOcupado = function (btn, si) {
    var s = btn.querySelector(':scope > [data-spinner]');
    if (si && !s) {
      s = document.createElement('span');
      s.setAttribute('data-spinner', '');
      s.className = 'loading loading-spinner loading-sm';
      s.setAttribute('aria-hidden', 'true');
      btn.insertBefore(s, btn.firstChild);
    } else if (!si && s) s.remove();
    btn.setAttribute('aria-busy', si ? 'true' : 'false');
    btn.disabled = !!si;
  };
})();

// Copiar al portapapeles: <button data-copiar="id-del-elemento"> copia su texto y se tiñe de verde un instante (CSP-safe).
document.addEventListener('click', function (e) {
  var b = e.target.closest && e.target.closest('[data-copiar]');
  var fuente = b && document.getElementById(b.getAttribute('data-copiar'));
  if (!fuente || !navigator.clipboard) return;
  navigator.clipboard.writeText(fuente.textContent.trim()).then(function () {
    b.classList.add('text-success');
    setTimeout(function () { b.classList.remove('text-success'); }, 1500);
  });
});

(function () {
  // Aviso estándar (toast): ficha con icono + título + detalle + acción opcional + cierre con icono. Ver docs/estandar-interfaz.html.
  var TRAZOS = {
    ok: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    alerta: '<path d="M12 4 2.5 20h19z"/><path d="M12 10v4M12 17.5v.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.01"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    papelera: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>'
  };
  window.iconoSVG = function (nombre, cls) {
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="' +
      (cls || 'size-5') + '" aria-hidden="true">' + (TRAZOS[nombre] || TRAZOS.info) + '</svg>';
  };
  var TIPOS = {
    success: { icono: 'ok', ficha: 'ficha-ok', titulo: 'Listo' },
    error: { icono: 'alerta', ficha: 'ficha-error', titulo: 'No se pudo completar' },
    warning: { icono: 'alerta', ficha: 'ficha-aviso', titulo: 'Atención' },
    info: { icono: 'info', ficha: 'ficha-info', titulo: 'Información' }
  };
  function crear(tag, cls, texto) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (texto !== undefined) e.textContent = texto;
    return e;
  }
  // Construye (sin temporizador) un aviso. opciones: {titulo, accion: {texto, alClick}}.
  window.crearAviso = function (detalle, tipo, opciones) {
    opciones = opciones || {};
    var t = TIPOS[tipo] || TIPOS.info;
    tipo = TIPOS[tipo] ? tipo : 'info';
    var el = crear('div', 'aviso aviso-' + tipo);
    el.setAttribute('role', tipo === 'error' ? 'alert' : 'status');
    var ficha = crear('span', 'ficha ' + t.ficha); ficha.innerHTML = window.iconoSVG(t.icono);
    var cuerpo = crear('div', 'aviso__cuerpo');
    cuerpo.append(crear('span', 'aviso__titulo', opciones.titulo || t.titulo), crear('span', 'aviso__detalle', detalle));
    el.append(ficha, cuerpo);
    if (opciones.accion) {
      var acc = crear('button', 'btn btn-sm aviso__accion', opciones.accion.texto); acc.type = 'button';
      acc.className += tipo === 'error' ? ' btn-error' : tipo === 'warning' ? ' btn-warning' : tipo === 'info' ? ' btn-info' : ' btn-success';
      acc.addEventListener('click', function () { try { opciones.accion.alClick(); } finally { el.remove(); } });
      el.append(acc);
    }
    var x = crear('button', 'btn-icono'); x.type = 'button'; x.setAttribute('data-accion', 'cerrar-aviso'); x.setAttribute('aria-label', 'Cerrar aviso');
    x.innerHTML = window.iconoSVG('x', 'size-4'); el.append(x);
    return el;
  };

  window.confirmarUI = function (msg, op) {
    op = op || {};
    // Destructivas (eliminar, borrar, quitar) en rojo; el resto en advertencia. Se puede forzar con op.tipo.
    var peligro = (op.tipo || (/elimin|borrar|quitar|descartar|desvincular/i.test(msg) ? 'peligro' : '')) === 'peligro';
    var caja = document.getElementById('confirmaciones');
    if (!caja) {
      caja = document.createElement('div');
      caja.id = 'confirmaciones';
      caja.className = 'toast toast-top toast-end z-[9999]';
      document.body.appendChild(caja);
    }
    return new Promise(function (resolver) {
      var el = crear('div', 'aviso aviso-confirmar ' + (peligro ? 'aviso-error' : 'aviso-warning'));
      el.setAttribute('role', 'alertdialog');
      var fila = crear('div', 'aviso__fila');
      var ficha = crear('span', 'ficha ' + (peligro ? 'ficha-error' : 'ficha-aviso')); ficha.innerHTML = window.iconoSVG(peligro ? 'papelera' : 'alerta');
      var cuerpo = crear('div', 'aviso__cuerpo');
      cuerpo.append(crear('span', 'aviso__titulo', op.titulo || (peligro ? 'Eliminar' : 'Confirmar')), crear('span', 'aviso__detalle', msg));
      fila.append(ficha, cuerpo);
      var botones = crear('div', 'aviso__botones');
      var no = crear('button', 'btn btn-sm btn-ghost', op.cancelar || 'Cancelar'); no.type = 'button';
      var si = crear('button', 'btn btn-sm ' + (peligro ? 'btn-error' : 'btn-warning'), op.aceptar || (peligro ? 'Eliminar' : 'Confirmar')); si.type = 'button';
      botones.append(no, si); el.append(fila, botones);
      function fin(ok) { document.removeEventListener('keydown', tecla); el.remove(); resolver(ok); }
      function tecla(e) { if (e.key === 'Escape') fin(false); }
      si.addEventListener('click', function () { fin(true); });
      no.addEventListener('click', function () { fin(false); });
      document.addEventListener('keydown', tecla);
      caja.appendChild(el);
      si.focus();
    });
  };
})();

// Comportamiento del shell (sin inline scripts: el CSP solo permite 'self').
document.addEventListener('DOMContentLoaded', function () {
  var html = document.documentElement;
  var sidebar = document.getElementById('sidebar');
  var velo = document.getElementById('sidebar-velo');

  function abrir(abierto) {
    if (!sidebar) return;
    sidebar.classList.toggle('-translate-x-full', !abierto);
    if (velo) velo.classList.toggle('hidden', !abierto);
  }

  document.querySelectorAll('[data-accion="menu"]').forEach(function (b) {
    b.addEventListener('click', function () { abrir(sidebar.classList.contains('-translate-x-full')); });
  });
  if (velo) velo.addEventListener('click', function () { abrir(false); });

  function marcarTema() {
    var oscuro = html.getAttribute('data-theme') === 'dark';
    document.querySelectorAll('[data-accion="tema"]').forEach(function (b) {
      b.setAttribute('aria-pressed', oscuro ? 'true' : 'false');
    });
  }
  document.querySelectorAll('[data-accion="tema"]').forEach(function (b) {
    b.addEventListener('click', function () {
      var nuevo = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      html.setAttribute('data-theme', nuevo);
      try { localStorage.setItem('tema', nuevo); } catch (e) {}
      marcarTema();
    });
  });
  marcarTema();

  // Menús <details class="dropdown">: se cierran con Esc (devolviendo el foco al botón) y al
  // hacer clic fuera; abrir uno cierra los demás.
  var menus = function () { return document.querySelectorAll('details.dropdown[open]'); };
  document.addEventListener('click', function (e) {
    menus().forEach(function (d) { if (!d.contains(e.target)) d.removeAttribute('open'); });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    menus().forEach(function (d) {
      d.removeAttribute('open');
      var s = d.querySelector('summary'); if (s) s.focus();
    });
    if (sidebar && !sidebar.classList.contains('-translate-x-full') && window.matchMedia('(max-width: 767px)').matches) abrir(false);
  });

  // Mensajes (toasts): se cierran solos a los 6 s (los de error, a los 12 s). El puntero o el foco encima los detienen
  // (y la barra de tiempo con ellos) y al salir siguen donde iban; siempre se pueden cerrar a mano.
  function armarAviso(el) {
    var ms = el.getAttribute('role') === 'alert' ? 12000 : 6000, resto = ms, t0 = 0, t = null;
    el.style.setProperty('--ms', ms + 'ms'); el.setAttribute('data-ms', ms);
    function seguir() { t0 = Date.now(); clearTimeout(t); t = setTimeout(function () { el.remove(); }, resto); el.classList.remove('en-pausa'); }
    function parar() { if (t === null) return; clearTimeout(t); t = null; resto = Math.max(500, resto - (Date.now() - t0)); el.classList.add('en-pausa'); }
    el.addEventListener('mouseenter', parar); el.addEventListener('mouseleave', seguir);
    el.addEventListener('focusin', parar); el.addEventListener('focusout', seguir);
    seguir();
  }
  document.querySelectorAll('[data-autocerrar]').forEach(armarAviso);

  // Aviso creado por código (acciones AJAX): mismo aspecto que los mensajes que pinta el servidor.
  // tipo: «success», «error», «warning» o «info» (la etiqueta del mensaje de Django).
  // opciones: {fijo: true} (progreso: lo cierra quien lo creó), {titulo}, {accion: {texto, alClick}}.
  window.avisar = function (texto, tipo, opciones) {
    var region = document.querySelector('.toast[aria-label="Avisos"]');
    if (!region) {
      region = document.createElement('div');
      region.className = 'toast toast-top toast-end z-50';
      region.setAttribute('role', 'region'); region.setAttribute('aria-label', 'Avisos');
      document.body.appendChild(region);
    }
    var el = window.crearAviso(texto, tipo, opciones);
    region.appendChild(el);
    if (opciones && opciones.fijo) el.classList.add('aviso-fijo'); else armarAviso(el);   // «fijo»: progreso, lo cierra quien lo creó
    return el;
  };
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-accion="cerrar-aviso"]');
    if (b) b.closest('.aviso, .alert').remove();
  });

  // Filas enlazadas: <tr data-href="…"> abre su destino al hacer click en cualquier parte de la fila
  // (los enlaces, botones y campos de dentro conservan su propio comportamiento).
  document.addEventListener('click', function (e) {
    var fila = e.target.closest && e.target.closest('tr[data-href]');
    if (!fila || e.target.closest('a, button, input, select, textarea, label, summary')) return;
    if (window.getSelection && String(window.getSelection())) return;   // no robar la selección de texto
    var destino = fila.getAttribute('data-href');
    if (e.ctrlKey || e.metaKey) window.open(destino, '_blank', 'noopener');
    else window.location.href = destino;
  });


  // Formularios AJAX: <form data-ajax> se envía con fetch y la página NO se recarga (se conserva el desplazamiento).
  // El servidor responde JSON {ok, mensajes:[{texto,tipo}]}; después se vuelven a pedir las zonas marcadas con
  // [data-refrescar="<id>"] y se sustituye su contenido, restaurando su scroll. Si algo falla, se avisa y se
  // refresca igual, para que los campos vuelvan al valor real.
  function enviarForm(form) {
    if (form.hasAttribute('data-ajax') && form.requestSubmit) form.requestSubmit(); else form.submit();
  }

  function refrescarZonas() {
    var zonas = document.querySelectorAll('[data-refrescar]');
    if (!zonas.length) return Promise.resolve();
    return fetch(window.location.href, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { if (!r.ok) throw new Error('refresco'); return r.text(); })
      .then(function (html) {
        var nuevo = new DOMParser().parseFromString(html, 'text/html');
        zonas.forEach(function (z) {
          var otra = nuevo.querySelector('[data-refrescar="' + z.getAttribute('data-refrescar') + '"]');
          if (!otra) return;
          var arriba = z.scrollTop, izquierda = z.scrollLeft;
          z.innerHTML = otra.innerHTML;
          z.scrollTop = arriba; z.scrollLeft = izquierda;
        });
      });
  }

  // Selectores que envían su formulario al cambiar: <select data-autoenviar-select>.
  document.addEventListener('change', function (e) {
    var sel = e.target;
    if (sel && sel.matches && sel.matches('select[data-autoenviar-select], input[data-autoenviar-select]') && sel.form) {
      // Una opción con data-confirmar pide confirmación; si se cancela, el select vuelve a su valor original.
      var op = sel.selectedOptions && sel.selectedOptions[0];
      if (op && op.dataset.confirmar) {
        window.confirmarUI(op.dataset.confirmar).then(function (ok) {
          if (ok) { enviarForm(sel.form); return; }
          for (var i = 0; i < sel.options.length; i++) sel.options[i].selected = sel.options[i].defaultSelected;
        });
        return;
      }
      enviarForm(sel.form);
    }
  });

  // Interruptores que envían su formulario: <input type="checkbox" data-autoenviar="¿Seguro?">. Se confirma y,
  // si la persona cancela, el interruptor vuelve a su posición.
  document.addEventListener('change', function (e) {
    var cb = e.target;
    if (!cb || !cb.matches || !cb.matches('input[data-autoenviar]')) return;
    var msg = cb.getAttribute('data-autoenviar');
    var form = cb.form;
    Promise.resolve(msg ? window.confirmarUI(msg) : true).then(function (ok) {
      if (!ok) { cb.checked = !cb.checked; return; }
      if (!form.hasAttribute('data-ajax')) cb.disabled = true;
      enviarForm(form);
    });
  });

  // Confirmaciones declarativas: <form data-confirmar="¿Seguro?">. Por delegación, así también
  // valen para formularios insertados por AJAX (mensajes del chat, fragmentos del tablero).
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (!f || !f.matches || !f.matches('form[data-confirmar]') || f.dataset.confirmado) return;
    e.preventDefault();
    var boton = e.submitter;
    window.confirmarUI(f.getAttribute('data-confirmar')).then(function (ok) {
      if (!ok) return;
      f.dataset.confirmado = '1';
      if (f.requestSubmit) f.requestSubmit(boton || undefined); else f.submit();
      delete f.dataset.confirmado;
    });
  });

  // (El envío AJAX va DESPUÉS de las confirmaciones: así una confirmación cancelada no envía nada.)
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (e.defaultPrevented || !form || !form.matches || !form.matches('form[data-ajax]')) return;
    e.preventDefault();
    if (form.dataset.enviando) return;
    form.dataset.enviando = '1';
    var datos = new FormData(form);   // ANTES de deshabilitar: un campo deshabilitado no se envía (ni el token CSRF)
    var controles = form.querySelectorAll('select, input, button');
    controles.forEach(function (c) { c.disabled = true; });
    fetch(form.action, {
      method: 'POST', body: datos, credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
    })
      .then(function (r) {
        if (!r.ok) throw new Error('Error ' + r.status);
        return r.json();
      })
      .then(function (d) {
        (d.mensajes || []).forEach(function (m) { window.avisar(m.texto, m.tipo); });
        if (!d.ok && !(d.mensajes || []).length) window.avisar('No se pudo guardar el cambio.', 'error');
      })
      .catch(function () { window.avisar('No se pudo guardar el cambio. Revisa tu conexión.', 'error'); })
      .then(function () { return refrescarZonas(); })
      .catch(function () { /* sin refresco: la persona puede recargar a mano */ })
      .then(function () {
        delete form.dataset.enviando;
        controles.forEach(function (c) { if (c.isConnected) c.disabled = false; });
      });
  });

  // Edición en modal: <button data-editar-registro data-action="…" data-user="…" data-alternativa="…"> rellena y abre
  // el <dialog id="editar-registro"> compartido de la lista. [data-cerrar-dialogo] lo cierra.
  document.addEventListener('click', function (e) {
    var cerrar = e.target.closest && e.target.closest('[data-cerrar-dialogo]');
    if (cerrar) { var d = cerrar.closest('dialog'); if (d) d.close(); return; }
    var b = e.target.closest && e.target.closest('[data-editar-registro]');
    if (!b) return;
    var dlg = document.getElementById('editar-registro');
    if (!dlg) return;
    var form = dlg.querySelector('form[method="post"]');
    form.action = b.getAttribute('data-action');
    var u = form.querySelector('[name="user"]'), a = form.querySelector('[name="alternativa"]');
    if (u) u.value = b.getAttribute('data-user') || '';
    if (a) a.value = b.getAttribute('data-alternativa') || '';
    dlg.showModal();
  });

  // Botones con confirmación propia: <button data-confirmar-click="¿Seguro?">.
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-confirmar-click]');
    if (!b || b.dataset.confirmado) return;
    e.preventDefault();
    window.confirmarUI(b.getAttribute('data-confirmar-click')).then(function (ok) {
      if (!ok) return;
      b.dataset.confirmado = '1';
      b.click();
      delete b.dataset.confirmado;
    });
  });
});

// Búsqueda en vivo: <input data-autobuscar="3"> envía su formulario al escribir (con pausa) cuando hay al menos N
// letras, o al vaciarlo. Tras recargar la página devuelve el foco al campo, con el cursor al final.
(function () {
  var CLAVE = 'autobuscar-foco', temporizador;
  function campo(e) { return e.target && e.target.matches && e.target.matches('input[data-autobuscar]') ? e.target : null; }
  document.addEventListener('input', function (e) {
    var c = campo(e);
    if (!c || !c.form) return;
    var minimo = parseInt(c.getAttribute('data-autobuscar'), 10) || 3;
    var largo = c.value.trim().length;
    clearTimeout(temporizador);
    if (largo !== 0 && largo < minimo) return;
    if (largo === 0 && !c.defaultValue) return;   // ya estaba vacío: nada que actualizar
    temporizador = setTimeout(function () {
      try { sessionStorage.setItem(CLAVE, c.name); } catch (_) { /* sin almacenamiento: solo se pierde el foco */ }
      c.form.submit();
    }, 400);
  });
  document.addEventListener('DOMContentLoaded', function () {
    var nombre;
    try { nombre = sessionStorage.getItem(CLAVE); sessionStorage.removeItem(CLAVE); } catch (_) { return; }
    var c = nombre && document.querySelector('input[data-autobuscar][name="' + nombre + '"]');
    if (!c) return;
    c.focus();
    c.setSelectionRange(c.value.length, c.value.length);
  });

  // Botón «Imprimir / PDF»: <button data-imprimir>. (Sin onclick inline: lo bloquea la CSP.)
  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('[data-imprimir]')) window.print();
  });
})();
