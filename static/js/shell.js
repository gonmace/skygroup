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
      var el = document.createElement('div');
      el.className = 'w-80 max-w-[90vw] rounded-box border border-base-300 border-l-4 ' + (peligro ? 'border-l-error' : 'border-l-warning') + ' bg-base-100 p-4 text-base-content shadow-xl';
      el.setAttribute('role', 'alertdialog');
      var cuerpo = document.createElement('div');
      cuerpo.className = 'block';
      var h = document.createElement('h4'); h.className = 'mb-1 text-sm font-semibold'; h.textContent = op.titulo || (peligro ? 'Eliminar' : 'Confirmar');
      var p = document.createElement('p'); p.className = 'mb-3 text-sm'; p.textContent = msg;
      var fila = document.createElement('div'); fila.className = 'flex gap-2';
      var si = document.createElement('button'); si.type = 'button'; si.className = 'btn btn-sm ' + (peligro ? 'btn-error' : 'btn-warning'); si.textContent = op.aceptar || (peligro ? 'Eliminar' : 'Confirmar');
      var no = document.createElement('button'); no.type = 'button'; no.className = 'btn btn-sm btn-ghost'; no.textContent = op.cancelar || 'Cancelar';
      fila.append(si, no); cuerpo.append(h, p, fila); el.append(cuerpo);
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

  // Mensajes (toasts): se cierran solos a los 6 s (los de error, a los 12 s); el puntero o el
  // foco encima los mantiene, y siempre se pueden cerrar a mano.
  function armarAviso(el) {
    var ms = el.getAttribute('role') === 'alert' ? 12000 : 6000, t;
    function armar() { clearTimeout(t); t = setTimeout(function () { el.remove(); }, ms); }
    function parar() { clearTimeout(t); }
    el.addEventListener('mouseenter', parar); el.addEventListener('mouseleave', armar);
    el.addEventListener('focusin', parar); el.addEventListener('focusout', armar);
    armar();
  }
  document.querySelectorAll('[data-autocerrar]').forEach(armarAviso);

  // Aviso creado por código (acciones AJAX): mismo aspecto que los mensajes que pinta el servidor.
  // tipo: «success», «error», «warning» o «info» (la etiqueta del mensaje de Django).
  window.avisar = function (texto, tipo, opciones) {
    var region = document.querySelector('.toast[aria-label="Avisos"]');
    if (!region) {
      region = document.createElement('div');
      region.className = 'toast toast-top toast-end z-50';
      region.setAttribute('role', 'region'); region.setAttribute('aria-label', 'Avisos');
      document.body.appendChild(region);
    }
    var el = document.createElement('div');
    var clase = tipo === 'error' ? 'alert-error' : tipo === 'success' ? 'alert-success' : tipo === 'warning' ? 'alert-warning' : 'alert-info';
    el.className = 'alert ' + clase;
    el.setAttribute('role', tipo === 'error' ? 'alert' : 'status');
    var span = document.createElement('span'); span.textContent = texto;
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'btn btn-ghost btn-xs btn-square'; b.setAttribute('data-accion', 'cerrar-aviso');
    b.setAttribute('aria-label', 'Cerrar aviso'); b.textContent = '✕';
    el.appendChild(span); el.appendChild(b); region.appendChild(el);
    if (!(opciones && opciones.fijo)) armarAviso(el);   // «fijo»: progreso, lo cierra quien lo creó
    return el;
  };
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-accion="cerrar-aviso"]');
    if (b) b.closest('.alert').remove();
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
      if (op && op.dataset.confirmar && !window.confirm(op.dataset.confirmar)) {
        for (var i = 0; i < sel.options.length; i++) sel.options[i].selected = sel.options[i].defaultSelected;
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
