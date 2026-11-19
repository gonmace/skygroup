// APU → Plantillas: banco de pruebas de un prompt. Corre el paso con lo que hay en el formulario (sin guardarlo) y deja
// cada resultado en una tarjeta, para comparar modelos y versiones. Sin inline scripts (CSP).
(function () {
  'use strict';

  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute('content') : '';
  var NIVELES = { '': 'sin razonamiento', low: 'razonamiento bajo', medium: 'razonamiento medio', high: 'razonamiento alto' };

  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function avisar(texto, tipo) { if (window.avisar) window.avisar(texto, tipo); }

  function tabla(filas) {
    var hayPersonas = filas.some(function (f) { return f.personas != null; });
    var html = '<div class="overflow-x-auto"><table class="table table-sm"><thead><tr><th>Descripción</th><th>Unidad</th><th class="text-right">' +
      (hayPersonas ? 'Personas' : 'Cantidad') + '</th><th>Justificación</th></tr></thead><tbody>';
    filas.forEach(function (f) {
      var cant = f.personas != null ? f.personas : f.cantidad;
      html += '<tr' + (f.check === false ? ' class="opacity-60"' : '') + '><td>' + esc(f.descripcion) + '</td><td>' + esc(f.unidad) +
        '</td><td class="text-right tabular-nums">' + esc(cant) + '</td><td class="text-xs text-base-content/60">' + esc(f.justificacion) + '</td></tr>';
    });
    return html + '</tbody></table></div>';
  }

  function resumen(r) {
    var html = '';
    if (Array.isArray(r.filas) && r.filas.length) html += tabla(r.filas);
    if (r.rendimiento != null) html += '<p class="text-sm"><strong>Rendimiento:</strong> ' + esc(r.rendimiento) + ' por jornada de ' + esc(r.horas_jornada || 8) + ' h</p>';
    (r.consultas || []).forEach(function (c) {
      html += '<div class="rounded-xl border border-base-300 p-3 text-sm"><p class="font-medium">' + esc(c.pregunta) + '</p>' +
        (c.recomendada ? '<p class="text-xs text-base-content/60">Recomendada: ' + esc(c.recomendada) + (c.por_que ? ' · ' + esc(c.por_que) : '') + '</p>' : '') + '</div>';
    });
    var simples = Object.keys(r).filter(function (k) { return typeof r[k] !== 'object' && k !== 'ejecucion_id'; });
    if (!html && simples.length) {
      html += '<dl class="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">' + simples.map(function (k) {
        return '<dt class="font-medium">' + esc(k) + '</dt><dd>' + esc(r[k]) + '</dd>';
      }).join('') + '</dl>';
    }
    return html || '<p class="text-sm text-base-content/60">La IA no devolvió contenido para mostrar.</p>';
  }

  // ── Resaltado de variables: lo que va entre « » y los nombres con guion bajo salen en otro color ─────────────────────
  var VARIABLES = /«[^»\n]+»|\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g;
  var ESTILOS = ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'wordSpacing', 'tabSize', 'textIndent',
                 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'borderTopWidth', 'borderRightWidth',
                 'borderBottomWidth', 'borderLeftWidth', 'textTransform'];

  function resaltar(ta) {
    var base = ta.parentNode.classList.contains('dictado-caja') ? ta.parentNode : ta;
    var caja = document.createElement('div');
    caja.className = 'resaltado-caja';
    base.parentNode.insertBefore(caja, base);
    caja.appendChild(base);
    var eco = document.createElement('div');
    eco.className = 'resaltado-eco';
    eco.setAttribute('aria-hidden', 'true');
    caja.appendChild(eco);
    ta.classList.add('resaltado-ta');

    function pintar() {
      var cs = getComputedStyle(ta);
      ESTILOS.forEach(function (k) { eco.style[k] = cs[k]; });
      // El ancho útil es el del textarea sin su barra de desplazamiento (si la tiene): así las líneas se parten igual.
      var barra = ta.offsetWidth - ta.clientWidth - parseFloat(cs.borderLeftWidth) - parseFloat(cs.borderRightWidth);
      eco.style.right = Math.max(0, barra) + 'px';
      eco.textContent = '';
      var texto = ta.value, ultimo = 0, m;
      VARIABLES.lastIndex = 0;
      while ((m = VARIABLES.exec(texto))) {
        if (m.index > ultimo) eco.appendChild(document.createTextNode(texto.slice(ultimo, m.index)));
        var span = document.createElement('span');
        span.className = 'var-ia';
        span.textContent = m[0];
        eco.appendChild(span);
        ultimo = m.index + m[0].length;
      }
      eco.appendChild(document.createTextNode(texto.slice(ultimo) + '\n'));   // el salto final mantiene la altura de la última línea
      eco.scrollTop = ta.scrollTop;
    }
    ta.addEventListener('input', pintar);
    ta.addEventListener('scroll', function () { eco.scrollTop = ta.scrollTop; });
    if (window.ResizeObserver) new ResizeObserver(pintar).observe(ta);
    // Lo escribe a veces otro script (restaurar un borrador, dictado): se vuelve a pintar al terminar de cargar y en un instante.
    window.addEventListener('load', pintar);
    setTimeout(pintar, 300);
    pintar();
    return pintar;
  }
  var repintar = [];
  document.querySelectorAll('textarea[data-resaltar]').forEach(function (ta) { repintar.push(resaltar(ta)); });

  // Borradores sin guardar: se conservan por pestaña (sessionStorage) para no perder lo editado al cambiar de paso, y la
  // prueba los usa (también los de los pasos que acompañan al que se prueba).
  var CAMPOS = ['rol', 'criterios', 'reglas', 'notas', 'modelo', 'razonamiento', 'comentario'];
  var formPrompt = document.querySelector('[data-plantilla-form]');
  function clave(id, paso) { return 'apu-plantilla-' + id + ':' + paso; }
  function leer(k) { try { return JSON.parse(sessionStorage.getItem(k) || 'null'); } catch (e) { return null; } }
  function guardar(k, v) { try { if (v) sessionStorage.setItem(k, JSON.stringify(v)); else sessionStorage.removeItem(k); } catch (e) { /* sin almacenamiento: no se conserva */ } }

  function iniciarBorrador(form) {
    var id = form.getAttribute('data-plantilla-id'), paso = form.getAttribute('data-paso'), k = clave(id, paso);
    var aviso = document.querySelector('[data-borrador-aviso]');
    function valores() { var v = {}; CAMPOS.forEach(function (c) { if (form.elements[c]) v[c] = form.elements[c].value; }); return v; }
    var original = valores();
    function distinto(v) { return CAMPOS.some(function (c) { return c in v && v[c] !== original[c]; }); }
    function marcar(hay) {
      if (aviso) { aviso.classList.toggle('hidden', !hay); aviso.classList.toggle('flex', hay); }
      var tab = document.querySelector('nav.segmentado a[href="?paso=' + paso + '"]');
      if (tab) tab.setAttribute('title', hay ? 'Cambios sin guardar' : '');
    }
    var previo = leer(k);
    if (previo && distinto(previo)) {
      CAMPOS.forEach(function (c) { if (form.elements[c] && c in previo) form.elements[c].value = previo[c]; });
      repintar.forEach(function (f) { f(); });
      marcar(true);
    } else { guardar(k, null); }
    function cambio() { var v = valores(); guardar(k, distinto(v) ? v : null); marcar(distinto(v)); }
    form.addEventListener('input', cambio);
    form.addEventListener('change', cambio);
    form.addEventListener('submit', function () { guardar(k, null); });
    var descartar = document.querySelector('[data-borrador-descartar]');
    if (descartar) descartar.addEventListener('click', function () { guardar(k, null); window.location.reload(); });
    // Marca en las otras pestañas las que tienen cambios sin guardar.
    document.querySelectorAll('nav.segmentado a[href^="?paso="]').forEach(function (a) {
      var p = a.getAttribute('href').split('=')[1];
      if (p !== paso && leer(clave(id, p))) a.setAttribute('title', 'Cambios sin guardar');
    });
  }
  if (formPrompt) iniciarBorrador(formPrompt);

  function otrosBorradores(id, paso) {
    var o = {};
    try {
      for (var i = 0; i < sessionStorage.length; i++) {
        var k = sessionStorage.key(i), pre = 'apu-plantilla-' + id + ':';
        if (k.indexOf(pre) === 0 && k.slice(pre.length) !== paso) o[k.slice(pre.length)] = leer(k);
      }
    } catch (e) { /* nada */ }
    return o;
  }

  document.querySelectorAll('[data-probar]').forEach(function (panel) {
    var boton = panel.querySelector('[data-probar-boton]'), salida = panel.querySelector('[data-resultados]');
    var form = document.querySelector('[data-plantilla-form]');
    if (!boton || !salida || !form) return;
    var n = 0;

    function valor(nombre) { var el = form.elements[nombre]; return el ? el.value : ''; }
    function campo(nombre) {
      var el = panel.querySelector('[data-prueba="' + nombre + '"]');
      return el ? (el.type === 'checkbox' ? el.checked : el.value) : '';
    }

    boton.addEventListener('click', function () {
      var datos = {
        rol: valor('rol'), criterios: valor('criterios'), reglas: valor('reglas'), notas: valor('notas'),
        modelo: valor('modelo'), razonamiento: valor('razonamiento'),
        proyecto: campo('proyecto'), actividad: campo('actividad'), unidad: campo('unidad'), descripcion: campo('descripcion'),
        sin_preguntas: campo('sin_preguntas') !== false,
        otros: otrosBorradores(form.getAttribute('data-plantilla-id'), form.getAttribute('data-paso'))
      };
      n += 1;
      var id = n;
      var tarjeta = document.createElement('div');
      tarjeta.className = 'card border border-base-300 bg-base-100';
      tarjeta.innerHTML = '<div class="card-body gap-2 p-4"><p class="text-sm font-medium">Prueba ' + id + ' · ' + esc(datos.modelo) + ' · ' +
        esc(NIVELES[datos.razonamiento] || datos.razonamiento) + '</p><p class="flex items-center gap-2 text-sm text-base-content/60"><span class="loading loading-spinner loading-xs"></span> Ejecutando… puede tardar hasta un par de minutos.</p></div>';
      salida.prepend(tarjeta);
      boton.disabled = true;
      var inicio = Date.now();
      fetch(panel.getAttribute('data-url'), {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify(datos)
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok && d.success !== false, d: d }; });
      }).catch(function () {
        return { ok: false, d: { message: 'No hay conexión con el servidor. Revisa tu red e inténtalo de nuevo.' } };
      }).then(function (res) {
        boton.disabled = false;
        var cuerpo = tarjeta.querySelector('.card-body');
        var titulo = '<p class="text-sm font-medium">Prueba ' + id + ' · ' + esc(datos.modelo) + ' · ' + esc(NIVELES[datos.razonamiento] || datos.razonamiento);
        if (!res.ok) {
          cuerpo.innerHTML = titulo + '</p><p class="text-sm text-error">' + esc(res.d.message || 'No se pudo completar la prueba.') + '</p>';
          avisar(res.d.message || 'No se pudo completar la prueba.', 'error');
          return;
        }
        var seg = res.d.segundos != null ? res.d.segundos : Math.round((Date.now() - inicio) / 100) / 10;
        cuerpo.innerHTML = titulo + ' · ' + esc(String(seg).replace('.', ',')) + ' s</p>' + resumen(res.d.respuesta || {}) +
          '<details class="text-xs"><summary class="cursor-pointer text-base-content/60">Respuesta completa (JSON)</summary><pre class="mt-1 max-h-72 overflow-auto rounded-xl bg-base-200 p-3">' +
          esc(JSON.stringify(res.d.respuesta, null, 2)) + '</pre></details>' +
          '<p class="text-xs text-base-content/50">Tokens y costo: aparecen en Consumo IA (ejecución n8n ' + esc(res.d.ejecucion_id || '—') + ').</p>';
      });
    });
  });
})();
