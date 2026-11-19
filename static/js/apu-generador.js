// Generador de APU con IA: progreso estimado de cada llamada, tablas de propuesta, consultas de la IA y guardado de
// cada paso. Sin inline scripts (CSP): los datos llegan en <script type="application/json"> y en atributos data-*.
(function () {
  'use strict';

  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute('content') : '';

  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function avisar(texto, tipo, op) { return window.avisar ? window.avisar(texto, tipo, op) : null; }
  function leerJson(id) {
    var el = document.getElementById(id);
    try { return el ? JSON.parse(el.textContent) : null; } catch (e) { return null; }
  }
  function num(v) { var n = parseFloat(String(v == null ? '' : v).replace(',', '.')); return isFinite(n) ? n : 0; }

  function post(url, datos) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(datos || {})
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        var ok = r.ok && d.success !== false;
        if (!ok && !d.message) d.message = r.status >= 500 ? 'Ocurrió un error en el servidor. Inténtalo de nuevo.' : 'No se pudo completar la acción.';
        return { ok: ok, status: r.status, data: d };
      });
    }).catch(function () {
      return { ok: false, status: 0, data: { message: 'No hay conexión con el servidor. Revisa tu red e inténtalo de nuevo.' } };
    });
  }

  // ── Progreso estimado: spinner, barra con porcentaje y mensajes de lo que se está haciendo ───────────────────────
  // El avance es una estimación (la llamada a la IA es síncrona): tiende al 92 % según la duración media real del
  // webhook y salta a 100 % al llegar la respuesta.
  function Progreso(raiz) {
    var caja = raiz.querySelector('[data-progreso]');
    var msg = caja && caja.querySelector('[data-progreso-mensaje]');
    var pct = caja && caja.querySelector('[data-progreso-pct]');
    var barra = caja && caja.querySelector('[data-progreso-barra]');
    if (barra) barra.style.transition = 'stroke-dashoffset .3s linear';   // por JS: un style en línea no pasa la CSP
    var timer = null;
    function pintar(valor, texto) {
      if (barra) barra.style.strokeDashoffset = (276.46 * (1 - valor / 100)).toFixed(2);
      if (caja) caja.style.setProperty('--giro', (valor * 3.6).toFixed(1) + 'deg');   // el giro de las órbitas sigue al porcentaje
      if (pct) pct.textContent = Math.round(valor) + ' %';
      if (msg && texto && msg.textContent !== texto) {
        msg.textContent = texto; msg.classList.remove('prog-msg'); void msg.offsetWidth; msg.classList.add('prog-msg');
      }
    }
    return {
      iniciar: function (mensajes, promedioMs) {
        if (!caja) return;
        mensajes = mensajes && mensajes.length ? mensajes : ['Trabajando en ello…'];
        var inicio = Date.now(), media = Math.max(5000, promedioMs || 40000);
        if (caja.showPopover) { if (!caja.matches(':popover-open')) caja.showPopover(); }   // capa superior: al centro de la pantalla y sobre cualquier modal
        else { document.body.appendChild(caja); caja.style.display = 'flex'; }
        pintar(2, mensajes[0]);
        clearInterval(timer);
        timer = setInterval(function () {
          var t = Date.now() - inicio, v = 92 * (1 - Math.exp(-2.2 * t / media));
          pintar(v, mensajes[Math.min(mensajes.length - 1, Math.floor(v / 92 * mensajes.length))]);
        }, 300);
      },
      terminar: function (ok) {
        function cerrar() { if (caja.hidePopover && caja.matches(':popover-open')) caja.hidePopover(); caja.style.display = ''; }
        clearInterval(timer);
        if (!caja) return;
        if (ok) { pintar(100, 'Listo.'); setTimeout(cerrar, 350); }
        else cerrar();
      }
    };
  }

  function bloquear(raiz, si) {
    raiz.querySelectorAll('button, input, select, textarea').forEach(function (el) {
      if (si) { if (!el.disabled) { el.disabled = true; el.setAttribute('data-bloqueado', '1'); } }
      else if (el.getAttribute('data-bloqueado')) { el.disabled = false; el.removeAttribute('data-bloqueado'); }
    });
  }

  // ── Formularios sencillos (paso 1, modales de reutilizar y modificar) ────────────────────────────────────────────
  function valoresForm(form) {
    var d = {};
    new FormData(form).forEach(function (v, k) { if (k !== 'csrfmiddlewaretoken') d[k] = v; });
    return d;
  }

  // Paso 1: preguntas con que la IA cierra el alcance. Cada una trae su respuesta recomendada ya puesta; la persona la acepta o la cambia.
  function pintarConsultasAlcance(zona, form, consultas) {
    zona.innerHTML = '';
    consultas.forEach(function (c) {
      var rec = (c.opciones || []).filter(function (o) { return o.clave === c.recomendada; })[0] || (c.opciones || [])[0];
      var el = document.createElement('div');
      el.className = 'rounded-box border border-primary/30 bg-primary/5 p-4';
      el.setAttribute('data-consulta-alcance', c.id);
      var html = '<p class="font-medium">' + esc(c.pregunta) + '</p>' +
        (c.motivo ? '<p class="mt-0.5 text-sm text-base-content/60">' + esc(c.motivo) + '</p>' : '') +
        (c.por_que ? '<p class="mt-1 text-sm"><span class="font-medium text-primary-text">Recomendación:</span> ' + esc(c.por_que) + '</p>' : '') +
        '<div class="mt-3 space-y-2">';
      if (c.tipo === 'opciones') {
        c.opciones.forEach(function (o) {
          html += '<label class="flex cursor-pointer items-start gap-3 rounded-box border border-base-300 bg-base-100 p-3">' +
            '<input type="radio" class="radio radio-primary radio-sm mt-0.5" name="ca-' + esc(c.id) + '" value="' + esc(o.etiqueta) + '"' + (rec && o.clave === rec.clave ? ' checked' : '') + '>' +
            '<span class="min-w-0 flex-1 text-sm"><span class="font-medium">' + esc(o.etiqueta) + '</span>' +
            (rec && o.clave === rec.clave ? ' <span class="badge badge-primary badge-soft badge-sm ml-1">Recomendado</span>' : '') + '</span></label>';
        });
      } else {
        html += '<input class="input input-bordered input-sm w-full" name="ca-' + esc(c.id) + '" maxlength="300" value="' + esc(rec ? rec.etiqueta : '') + '" aria-label="' + esc(c.pregunta) + '">';
      }
      el.innerHTML = html + '</div>';
      zona.appendChild(el);
    });
    var boton = form.querySelector('[type=submit]');
    if (boton && consultas.length) boton.textContent = 'Responder y continuar';
  }
  function respuestasAlcance(zona) {
    var resp = {};
    zona.querySelectorAll('[data-consulta-alcance]').forEach(function (el) {
      var id = el.getAttribute('data-consulta-alcance');
      var r = el.querySelector('input[type=radio]:checked') || el.querySelector('input.input');
      if (r && String(r.value).trim()) resp[id] = String(r.value).trim();
    });
    return resp;
  }

  function iniciarFormAjax(form) {
    var progreso = Progreso(form);
    var mensajes = (form.getAttribute('data-mensajes') || '').split('|').filter(Boolean);
    var promedio = parseInt(form.getAttribute('data-promedio') || '0', 10);
    var urlRepetir = form.getAttribute('data-url-repetir');   // paso 1: ya existe el borrador → se vuelve a comprobar ahí
    var alerta = form.querySelector('[data-aviso-ia]');
    var zonaAlcance = form.querySelector('[data-consultas-alcance]');

    var abiertas = leerJson('apu-consultas-alcance');
    if (!Array.isArray(abiertas)) abiertas = [];
    if (zonaAlcance && abiertas.length) pintarConsultasAlcance(zonaAlcance, form, abiertas);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (alerta) alerta.classList.add('hidden');
      var destino = form.getAttribute('data-url') || form.getAttribute('action') || window.location.href;
      var datos = valoresForm(form);   // ANTES de bloquear: un campo deshabilitado no se envía
      if (zonaAlcance) { var resp = respuestasAlcance(zonaAlcance); if (Object.keys(resp).length) datos.respuestas = resp; }
      bloquear(form, true);
      progreso.iniciar(mensajes, promedio);
      post(destino, datos).then(function (res) {
        bloquear(form, false);
        progreso.terminar(res.ok);
        var d = res.data;
        if (d.borrador_id && urlRepetir) {   // el borrador ya se creó: los siguientes envíos lo reutilizan
          form.setAttribute('data-url', urlRepetir.replace('/0/', '/' + d.borrador_id + '/'));
          var b = form.querySelector('[type=submit]');
          if (b && !res.ok) b.textContent = 'Reintentar';
        }
        if (!res.ok) { avisar(d.message, 'error'); return; }
        if (d.estado === 'no_coherente') {   // la actividad no cuadra: se explica y se vuelve a comprobar (el proyecto no se cuestiona)
          if (alerta) { alerta.querySelector('[data-aviso-texto]').textContent = d.razon || d.message; alerta.classList.remove('hidden'); }
          avisar(d.message, 'warning');
          var boton = form.querySelector('[type=submit]');
          if (boton) boton.textContent = 'Comprobar de nuevo';
          return;
        }
        if (d.estado === 'consultas' && zonaAlcance) {   // falta un dato del alcance: se pregunta y el paso 1 sigue abierto
          pintarConsultasAlcance(zonaAlcance, form, d.consultas || []);
          avisar(d.message, 'info');
          return;
        }
        avisar(d.message, 'success');
        if (d.continuar_url) window.location.href = d.continuar_url;
        else if (d.sin_cambios) { var dlg = form.closest('dialog'); if (dlg) dlg.close(); }
      });
    });
  }

  // Paso 1: tipo de trabajo (plantilla) en un control segmentado que escribe su valor en un campo oculto.
  document.querySelectorAll('[data-plantillas]').forEach(function (caja) {
    var campo = caja.querySelector('input[name=plantilla]'), texto = caja.querySelector('[data-plantilla-texto]');
    caja.querySelectorAll('button[data-plantilla]').forEach(function (b) {
      b.addEventListener('click', function () {
        campo.value = b.dataset.plantilla;
        caja.querySelectorAll('button[data-plantilla]').forEach(function (o) { o.setAttribute('aria-pressed', o === b ? 'true' : 'false'); });
        if (texto) texto.textContent = b.dataset.descripcion || '';
      });
    });
  });

  // Paso 1: según el proyecto elegido se propone su perfil de cálculo y se muestra la región de sus precios.
  function iniciarActividad(raiz) {
    var info = leerJson('apu-info-proyectos') || {};
    var sel = raiz.querySelector('[name=proyecto]');
    var perfil = raiz.querySelector('[data-perfil]');
    var filtro = raiz.querySelector('[data-filtro-proyecto]');
    function actualizar() {   // el perfil se propone con el del proyecto (editable)
      var p = info[sel.value];
      var reg = raiz.querySelector('[data-region-actual]');
      if (reg) reg.textContent = p ? 'Precios de: ' + (p.region || 'nacionales') + ' (se define al habilitar el proyecto)' : '';
      if (!p) return;
      if (perfil && p.perfil_id && !perfil.dataset.tocado) perfil.value = String(p.perfil_id);
    }
    if (perfil) perfil.addEventListener('change', function () { perfil.dataset.tocado = '1'; });
    if (filtro) filtro.addEventListener('input', function () {
      var q = filtro.value.trim().toLowerCase();
      Array.prototype.forEach.call(sel.options, function (o) { o.hidden = q && o.value && o.text.toLowerCase().indexOf(q) < 0; });
    });
    sel.addEventListener('change', actualizar);
    actualizar();
  }

  // ── Pasos 2 a 4: tabla de propuesta + consultas ──────────────────────────────────────────────────────────────────
  function iniciarPaso(raiz) {
    var cfg = leerJson('apu-cfg');
    var estado = leerJson('apu-estado') || {};
    var catalogo = leerJson('apu-catalogo') || [];
    var tipo = cfg.tipo, esMO = tipo === 'mano_obra', esMat = tipo === 'materiales';
    var progreso = Progreso(raiz);
    var cuerpo = raiz.querySelector('[data-tabla]');
    var zonaConsultas = raiz.querySelector('[data-consultas]');
    var btnGuardar = raiz.querySelector('[data-accion=guardar]');
    var btnRepetir = raiz.querySelector('[data-accion=repetir]');
    var btnAgregar = raiz.querySelector('[data-accion=agregar]');
    var contador = raiz.querySelector('[data-contador]');
    var inRend = raiz.querySelector('[data-rendimiento]');
    var inHoras = raiz.querySelector('[data-horas]');
    var porClave = {};
    catalogo.forEach(function (c) { porClave[c.descripcion.trim().toLowerCase()] = c; });

    var filas = [], consultas = [], decisiones = {}, otras = {}, usadas = estado.usadas || 0;   // otras: respuesta escrita a una consulta de opciones
    var errorInicial = false;
    var bloquesResultado = raiz.querySelectorAll('[data-resultados]');   // tabla, rendimiento y acciones: salen DESPUÉS de las preguntas
    function mostrarResultados(si) { Array.prototype.forEach.call(bloquesResultado, function (b) { b.classList.toggle('hidden', !si); }); }

    var MENSAJES = {
      materiales: ['Leyendo la descripción del proyecto…', 'Revisando el catálogo de materiales de la empresa…',
        'Proponiendo materiales y cantidades por unidad…', 'Buscando insumos que se puedan consolidar…', 'Verificando los materiales esenciales…'],
      mano_obra: ['Revisando los oficios del catálogo de la empresa…', 'Estimando la cuadrilla y el rendimiento…',
        'Calculando las horas por unidad…', 'Verificando los oficios esenciales…'],
      equipos: ['Revisando los equipos del catálogo de la empresa…', 'Estimando las horas-máquina por unidad…',
        'Verificando los equipos esenciales…']
    };

    function filaVacia() {
      var f = { descripcion: '', unidad: esMO || tipo === 'equipos' ? 'h' : '', codigo_catalogo: '', nuevo: true, justificacion: '',
        check: true, consulta: '' };
      if (esMO) f.personas = '1'; else f.cantidad = '';
      if (esMat) f.desperdicio_pct = '0';
      return f;
    }
    function clonar(f) { return JSON.parse(JSON.stringify(f)); }

    function cargarPropuesta(p) {
      consultas = p.consultas || [];
      filas = (p.filas || []).map(clonar);
      decisiones = {}; otras = {};
      consultas.forEach(function (c) {
        if (c.tipo === 'opciones') {
          var op = c.opciones.filter(function (o) { return o.clave === c.recomendada; })[0] || c.opciones[0];
          decisiones[c.id] = op.clave;
          aplicarOpcion(c, op);
        } else if (estado.respuestas && estado.respuestas[c.id]) decisiones[c.id] = estado.respuestas[c.id];
        else {   // pregunta abierta: ya viene la respuesta recomendada (la persona la acepta o escribe otra)
          var rec = (c.opciones || []).filter(function (o) { return o.clave === c.recomendada; })[0] || (c.opciones || [])[0];
          if (rec) decisiones[c.id] = rec.etiqueta;
        }
      });
      if (esMO) {
        if (p.rendimiento && inRend && !inRend.value) inRend.value = p.rendimiento;
        if (p.horas_jornada && inHoras && !inHoras.value) inHoras.value = p.horas_jornada;
      }
      mostrarResultados(!consultas.length);   // con preguntas pendientes solo se ven las preguntas
      pintarConsultas(); pintarTabla();
    }

    // Elegir una opción de consulta reemplaza, al momento y sin llamar a la IA, las filas de esa consulta.
    function aplicarOpcion(c, op) {
      filas = filas.filter(function (f) { return f.consulta !== c.id; });
      var nuevas = (op.filas || []).map(function (f) { var g = clonar(f); g.check = true; g.consulta = c.id; return g; });
      if (!nuevas.length && op.codigo_subitem) {
        nuevas.push({ descripcion: op.etiqueta, unidad: '', codigo_subitem: op.codigo_subitem, cantidad: '1', desperdicio_pct: '0',
          codigo_catalogo: '', nuevo: false, justificacion: '', check: true, consulta: c.id });
      }
      filas = filas.concat(nuevas);
    }

    function pintarConsultas() {
      if (!zonaConsultas) return;
      zonaConsultas.innerHTML = '';
      var hayDatos = false;
      consultas.forEach(function (c) {
        var el = document.createElement('div');
        el.className = 'rounded-box border border-primary/30 bg-primary/5 p-4';
        var html = '<div class="flex items-start gap-3"><span class="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-primary/15 text-primary-text">?</span>' +
          '<div class="min-w-0 flex-1"><p class="font-medium">' + esc(c.pregunta) + '</p>' +
          (c.motivo ? '<p class="mt-0.5 text-sm text-base-content/60">' + esc(c.motivo) + '</p>' : '') +
          (c.por_que ? '<p class="mt-1 text-sm"><span class="font-medium text-primary-text">Recomendación:</span> ' + esc(c.por_que) + '</p>' : '') +
          '<div class="mt-3 space-y-2">';
        if (c.tipo === 'opciones') {
          c.opciones.forEach(function (o) {
            var marcada = otras[c.id] === undefined && decisiones[c.id] === o.clave;
            html += '<label class="flex cursor-pointer items-start gap-3 rounded-box border bg-base-100 p-3 ' + (marcada ? 'border-primary' : 'border-base-300') + '">' +
              '<input type="radio" class="radio radio-primary radio-sm mt-0.5" name="c-' + esc(c.id) + '" value="' + esc(o.clave) + '"' + (marcada ? ' checked' : '') + '>' +
              '<span class="min-w-0 flex-1 text-sm"><span class="font-medium">' + esc(o.etiqueta) + '</span>' +
              (o.clave === c.recomendada ? ' <span class="badge badge-primary badge-soft badge-sm ml-1">Recomendado</span>' : '') +
              (o.codigo_subitem ? ' <span class="badge badge-ghost badge-sm ml-1">Sub-análisis del catálogo</span>' : '') +
              ((o.filas || []).length ? '<span class="mt-0.5 block text-xs text-base-content/60">' + o.filas.map(function (f) { return esc(f.descripcion); }).join(' · ') + '</span>' : '') +
              '</span></label>';
          });
          var esOtra = otras[c.id] !== undefined;
          html += '<label class="flex cursor-pointer items-start gap-3 rounded-box border bg-base-100 p-3 ' + (esOtra ? 'border-primary' : 'border-base-300') + '">' +
            '<input type="radio" class="radio radio-primary radio-sm mt-0.5" name="c-' + esc(c.id) + '" value="__otra__"' + (esOtra ? ' checked' : '') + '>' +
            '<span class="min-w-0 flex-1 text-sm"><span class="font-medium">Otra respuesta</span>' +
            '<span class="mt-0.5 block text-xs text-base-content/60">Ninguna de las anteriores: escribe lo que corresponde.</span>' +
            (esOtra ? '<textarea class="textarea textarea-bordered mt-2 w-full text-sm" rows="2" data-otra="' + esc(c.id) + '" placeholder="Tu respuesta">' + esc(otras[c.id]) + '</textarea>' +
              '<button type="button" class="btn btn-primary btn-sm mt-2" data-accion="enviar-otra">Enviar a la IA</button>' : '') +
            '</span></label>';
        } else {
          hayDatos = true;
          (c.opciones || []).length && (html += '<div class="flex flex-wrap gap-2">' + c.opciones.map(function (o) {
            var rec = o.clave === c.recomendada;
            return '<button type="button" class="btn btn-xs ' + (rec ? 'btn-primary' : 'btn-ghost') + '" data-sugerencia="' + esc(c.id) + '" data-valor="' + esc(o.etiqueta) + '">' +
              esc(o.etiqueta) + (rec ? ' <span class="opacity-70">· Recomendado</span>' : '') + '</button>';
          }).join('') + '</div>');
          html += '<textarea class="textarea textarea-bordered w-full text-sm" rows="2" data-respuesta="' + esc(c.id) + '" placeholder="Elige una sugerencia o escribe tu propia respuesta">' + esc(decisiones[c.id] || '') + '</textarea>';
        }
        html += '</div></div></div>';
        el.innerHTML = html;
        zonaConsultas.appendChild(el);
      });
      if (hayDatos) {
        var b = document.createElement('div');
        b.className = 'flex justify-end';
        b.innerHTML = '<button type="button" class="btn btn-primary btn-sm" data-accion="responder">Enviar respuestas a la IA</button>';
        zonaConsultas.appendChild(b);
      } else if (consultas.length && bloquesResultado.length && bloquesResultado[0].classList.contains('hidden')) {
        // solo preguntas de opciones (ya traen la recomendada marcada): al confirmarlas aparece la tabla
        var c2 = document.createElement('div');
        c2.className = 'flex justify-end';
        c2.innerHTML = '<button type="button" class="btn btn-primary btn-sm" data-accion="ver-propuesta">Continuar con estas respuestas</button>';
        zonaConsultas.appendChild(c2);
      }
    }

    function horasPorUnidad(f) {
      var rend = num(inRend && inRend.value), h = num(inHoras && inHoras.value);
      return rend > 0 ? (num(f.personas) * h / rend) : 0;
    }

    function pintarTabla() {
      cuerpo.innerHTML = '';
      if (!filas.length) {
        cuerpo.innerHTML = '<tr><td colspan="6" class="py-8 text-center text-base-content/60">' + (errorInicial ? 'La IA no pudo proponer este paso. Reintenta o agrega las filas a mano.' : 'Aún no hay filas.') + '</td></tr>';
      }
      filas.forEach(function (f, i) {
        var tr = document.createElement('tr');
        tr.setAttribute('data-i', i);
        var enCatalogo = !!f.codigo_catalogo || !!f.subitem_id || !!f.codigo_subitem;
        var badge = f.codigo_subitem || f.subitem_id ? '<span class="badge badge-ghost badge-sm">Sub-análisis</span>'
          : enCatalogo ? '<span class="badge badge-ghost badge-sm">Catálogo</span>' : '<span class="badge badge-outline badge-sm">Nuevo</span>';
        var cant = esMO
          ? '<input class="input input-bordered input-sm w-20 text-right tabular-nums" data-campo="personas" value="' + esc(f.personas) + '" inputmode="decimal" aria-label="Personas">'
          : '<input class="input input-bordered input-sm w-24 text-right tabular-nums" data-campo="cantidad" value="' + esc(f.cantidad) + '" inputmode="decimal" aria-label="Cantidad por unidad">';
        tr.innerHTML = '<td class="w-8"><input type="checkbox" class="checkbox checkbox-sm checkbox-primary" data-campo="check"' + (f.check ? ' checked' : '') + ' aria-label="Incluir"></td>' +
          '<td class="min-w-48"><input class="input input-bordered input-sm w-full" data-campo="descripcion" list="apu-catalogo-lista" value="' + esc(f.descripcion) + '" aria-label="Descripción">' +
          (f.justificacion ? '<p class="mt-1 text-xs text-base-content/60">' + esc(f.justificacion) + '</p>' : '') + '</td>' +
          (esMO ? '' : '<td class="w-20"><input class="input input-bordered input-sm w-full" data-campo="unidad" list="apu-unidades" autocomplete="off" value="' + esc(f.unidad) + '" aria-label="Unidad"' + (f.codigo_subitem ? ' disabled' : '') + '></td>') +
          '<td class="text-right">' + cant + '</td>' +
          (esMat ? '<td class="text-right"><input class="input input-bordered input-sm w-20 text-right tabular-nums" data-campo="desperdicio_pct" value="' + esc(f.desperdicio_pct) + '" inputmode="decimal" aria-label="Desperdicio %"></td>' : '') +
          (esMO ? '<td class="text-right tabular-nums text-sm text-base-content/70" data-horas-unidad>' + horasPorUnidad(f).toFixed(4) + '</td>' : '') +
          '<td class="w-24">' + badge + '</td>' +
          '<td class="w-px"><button type="button" class="btn-icono icono-peligro" data-quitar title="Quitar" aria-label="Quitar">' + window.iconoSVG('x', 'size-5') + '</button></td>';
        cuerpo.appendChild(tr);
      });
      actualizarContador();
    }

    function actualizarContador() {
      var n = filas.filter(function (f) { return f.check; }).length;
      if (contador) contador.textContent = n + ' de ' + filas.length + ' fila' + (filas.length === 1 ? '' : 's') + ' marcada' + (n === 1 ? '' : 's');
      var restantes = Math.max(0, cfg.max_repeticiones + 1 - usadas);
      if (btnRepetir) {
        btnRepetir.disabled = restantes <= 0;
        btnRepetir.textContent = 'Proponer de nuevo' + (usadas ? ' (' + restantes + ')' : '');
      }
    }

    cuerpo.addEventListener('input', function (e) {
      var tr = e.target.closest('tr'); if (!tr) return;
      var f = filas[tr.getAttribute('data-i')], campo = e.target.getAttribute('data-campo');
      if (!f || !campo) return;
      if (campo === 'check') { f.check = e.target.checked; actualizarContador(); return; }
      f[campo] = e.target.value;
      if (campo === 'descripcion') {
        var c = porClave[e.target.value.trim().toLowerCase()];
        if (c) { f.codigo_catalogo = c.codigo; if (!f.unidad) f.unidad = c.unidad; f.nuevo = false; }
        else { f.codigo_catalogo = ''; f.nuevo = true; }
      }
      if (esMO) { var td = tr.querySelector('[data-horas-unidad]'); if (td) td.textContent = horasPorUnidad(f).toFixed(4); }
    });
    cuerpo.addEventListener('change', function (e) {
      if (e.target.getAttribute('data-campo') === 'descripcion') pintarTabla();
    });
    cuerpo.addEventListener('click', function (e) {
      var b = e.target.closest('[data-quitar]'); if (!b) return;
      filas.splice(parseInt(b.closest('tr').getAttribute('data-i'), 10), 1);
      pintarTabla();
    });
    [inRend, inHoras].forEach(function (el) {
      if (el) el.addEventListener('input', function () { cuerpo.querySelectorAll('tr[data-i]').forEach(function (tr) {
        var td = tr.querySelector('[data-horas-unidad]'); if (td) td.textContent = horasPorUnidad(filas[tr.getAttribute('data-i')]).toFixed(4); }); });
    });
    if (btnAgregar) btnAgregar.addEventListener('click', function () { filas.push(filaVacia()); pintarTabla(); });

    if (zonaConsultas) {
      zonaConsultas.addEventListener('change', function (e) {
        if (e.target.type !== 'radio') return;
        var id = e.target.name.replace(/^c-/, '');
        var c = consultas.filter(function (x) { return x.id === id; })[0];
        if (e.target.value === '__otra__') {   // la persona escribe su propia respuesta: se quitan las filas de esa consulta
          otras[id] = otras[id] || ''; decisiones[id] = otras[id];
          filas = filas.filter(function (f) { return f.consulta !== id; });
          pintarConsultas(); pintarTabla();
          var area = zonaConsultas.querySelector('[data-otra="' + id + '"]'); if (area) area.focus();
          return;
        }
        var op = c.opciones.filter(function (o) { return o.clave === e.target.value; })[0];
        delete otras[id];
        decisiones[id] = op.clave; aplicarOpcion(c, op); pintarConsultas(); pintarTabla();
      });
      zonaConsultas.addEventListener('input', function (e) {
        var id = e.target.getAttribute('data-respuesta');
        if (id) decisiones[id] = e.target.value;
        var otra = e.target.getAttribute('data-otra');
        if (otra) { otras[otra] = e.target.value; decisiones[otra] = e.target.value; }
      });
      zonaConsultas.addEventListener('click', function (e) {
        var s = e.target.closest('[data-sugerencia]');
        if (s) {
          var area = zonaConsultas.querySelector('[data-respuesta="' + s.getAttribute('data-sugerencia') + '"]');
          area.value = s.getAttribute('data-valor'); decisiones[s.getAttribute('data-sugerencia')] = area.value; return;
        }
        if (e.target.closest('[data-accion=enviar-otra]')) {
          var vacia = Object.keys(otras).some(function (k) { return !String(otras[k]).trim(); });
          if (vacia) { avisar('Escribe tu respuesta antes de enviarla a la IA.', 'warning'); return; }
          proponer(true); return;
        }
        if (e.target.closest('[data-accion=ver-propuesta]')) {
          var pendiente = Object.keys(otras).some(function (k) { return !String(otras[k]).trim(); });
          if (pendiente) { avisar('Escribe tu respuesta, o elige una de las opciones.', 'warning'); return; }
          if (Object.keys(otras).length) { proponer(true); return; }   // si escribió una respuesta propia, la IA rehace la propuesta con ella
          mostrarResultados(true); pintarConsultas();
          var tabla = raiz.querySelector('[data-tabla]'); if (tabla) tabla.scrollIntoView({ behavior: 'smooth', block: 'start' });
          return;
        }
        if (e.target.closest('[data-accion=responder]')) proponer(true);
      });
    }

    function respuestasEscritas() {
      var r = {};
      consultas.forEach(function (c) {
        if (c.tipo === 'dato' && String(decisiones[c.id] || '').trim()) r[c.id] = decisiones[c.id].trim();
        if (c.tipo === 'opciones' && otras[c.id] !== undefined && String(otras[c.id]).trim()) r[c.id] = String(otras[c.id]).trim();   // «Otra respuesta»
      });
      return r;
    }

    function proponer(conRespuestas) {
      var respuestas = conRespuestas ? respuestasEscritas() : {};
      if (conRespuestas && !Object.keys(respuestas).length) { avisar('Escribe al menos una respuesta.', 'warning'); return; }
      bloquear(raiz, true);
      progreso.iniciar(MENSAJES[tipo], cfg.promedio_ms);
      post(cfg.url_proponer, { respuestas: respuestas }).then(function (res) {
        bloquear(raiz, false);
        progreso.terminar(res.ok);
        if (res.status === 409 && res.data.continuar_url) { window.location.href = res.data.continuar_url; return; }
        if (!res.ok) { errorInicial = !filas.length; mostrarResultados(true); avisar(res.data.message, 'error'); pintarTabla(); actualizarContador(); return; }
        usadas = res.data.usadas;
        estado.respuestas = respuestas;
        errorInicial = false;
        cargarPropuesta(res.data.propuesta);
      });
    }

    if (btnRepetir) btnRepetir.addEventListener('click', function () {
      var ir = function () { proponer(Object.keys(respuestasEscritas()).length > 0); };
      if (window.confirmarUI) window.confirmarUI('Se reemplazará la propuesta actual por una nueva. ¿Continuar?', { aceptar: 'Proponer de nuevo' }).then(function (ok) { if (ok) ir(); });
      else ir();
    });

    if (btnGuardar) btnGuardar.addEventListener('click', function () {
      var datos = { filas: filas, decisiones: decisiones };
      if (esMO) { datos.rendimiento = inRend.value; datos.horas_jornada = inHoras.value; }
      var guardar = function () {
        bloquear(raiz, true);
        post(cfg.url_guardar, datos).then(function (res) {
          bloquear(raiz, false);
          if (res.status === 409 && res.data.continuar_url) { window.location.href = res.data.continuar_url; return; }
          if (!res.ok) { avisar(res.data.message, 'error'); return; }
          avisar(res.data.message, 'success');
          window.location.href = res.data.continuar_url;
        });
      };
      window.confirmarUI('Al continuar no podrás volver a este paso.', { titulo: 'Guardar el paso', aceptar: 'Guardar y continuar' })
        .then(function (ok) { if (ok) guardar(); });
    });

    if (estado.propuesta) cargarPropuesta(estado.propuesta);
    else { mostrarResultados(false); pintarTabla(); proponer(false); }   // la tabla aparece cuando llega la propuesta (y tras las preguntas)
  }

  // ── Paso 5: precios, guardar el APU y modificar con IA ───────────────────────────────────────────────────────────
  function iniciarResultado(raiz) {
    var cfg = leerJson('apu-cfg') || {};
    var progreso = Progreso(raiz);
    // Las sugerencias de la IA son una RECOMENDACIÓN: se muestran junto a cada fila y solo se usan si la persona lo decide.
    var CONFIANZA = { alta: 'badge-success', media: 'badge-warning', baja: 'badge-ghost' };
    var sugeridas = {};   // lo que la IA recomendó, para volver a mostrarlo tras refrescar la tabla
    // Vuelve a pedir la página y reemplaza SOLO la composición y el precio unitario (los precios ya cambiaron). Antes se
    // guarda lo escrito en cada fila y después se restaura, junto con las sugerencias de las filas que siguen sin precio.
    function refrescar() {
      var foto = {};
      raiz.querySelectorAll('[data-precio-fila]').forEach(function (f) {
        foto[f.getAttribute('data-insumo')] = { precio: f.querySelector('[data-precio]').value, moneda: f.querySelector('[data-moneda]').value,
          estimado: f.getAttribute('data-estimado'), fuente: f.getAttribute('data-fuente') };
      });
      return fetch(window.location.href, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (html) {
          var doc = new DOMParser().parseFromString(html, 'text/html');
          ['composicion', 'precio'].forEach(function (z) {
            var nuevo = doc.querySelector('[data-zona="' + z + '"]'), actual = raiz.querySelector('[data-zona="' + z + '"]');
            if (nuevo && actual) actual.innerHTML = nuevo.innerHTML;
          });
          raiz.querySelectorAll('[data-precio-fila]').forEach(function (f) {
            var v = foto[f.getAttribute('data-insumo')];
            if (!v) return;
            f.querySelector('[data-precio]').value = v.precio;
            f.querySelector('[data-moneda]').value = v.moneda;
            if (v.estimado) f.setAttribute('data-estimado', v.estimado);
            if (v.fuente) f.setAttribute('data-fuente', v.fuente);
          });
          mostrarSugerencias(sugeridas);
        })
        .catch(function () { window.location.reload(); });   // si algo falla, se recarga como antes
    }
    function mostrarSugerencias(sug) {
      Object.keys(sug).forEach(function (id) { sugeridas[id] = sug[id]; });
      Object.keys(sug).forEach(function (id) {
        var fila = raiz.querySelector('[data-precio-fila][data-insumo="' + id + '"]');
        if (!fila) return;
        var s = sug[id], caja = fila.querySelector('[data-sugerencia]');
        caja.classList.remove('hidden');
        caja.innerHTML = '<span class="text-base-content/70">Sugerido: <strong class="tabular-nums">' + esc(s.precio) + ' ' + esc(s.moneda) + '</strong></span> ' +
          '<span class="badge badge-soft badge-sm ' + (CONFIANZA[s.confianza] || 'badge-ghost') + '">confianza ' + esc(s.confianza) + '</span> ' +
          '<button type="button" class="btn btn-ghost btn-xs" data-usar-sugerencia>Usar</button>' +
          '<span class="block text-base-content/50">' + esc(s.fuente) + (s.nota ? ' · ' + esc(s.nota) : '') + '</span>';
        caja.setAttribute('data-precio-sug', s.precio);
        caja.setAttribute('data-moneda-sug', s.moneda);
        caja.setAttribute('data-fuente-sug', s.fuente);
      });
    }
    // ── Editar o revisar con IA una fila: el precio que se cambia vale solo para este proyecto ──
    var dlgEd = document.getElementById('apu-editar-fila'), dlgRev = document.getElementById('apu-revisar-fila');
    var filaActual = null, sugerenciaFila = null;
    function mostrar(el, si) { if (el) el.classList.toggle('hidden', !si); }
    function abrirEdicion(tr) {
      if (!dlgEd || !tr) return;
      filaActual = tr;
      var d = tr.dataset, f = dlgEd.querySelector('form'), el = f.elements;
      var mo = d.tipo === 'mano_obra', sub = !d.insumoId;
      f.querySelector('[data-titulo]').textContent = 'Editar «' + d.nombre + '»';
      f.querySelector('[data-unidad]').textContent = d.unidad ? '(' + d.unidad + ')' : '';
      el.cantidad.value = d.cantidad; el.personas.value = d.personas || ''; el.desperdicio_pct.value = d.desperdicio || '';
      el.precio.value = d.precioActual || ''; el.moneda.value = d.monedaActual || '';
      mostrar(f.querySelector('[data-campo=cantidad]'), !mo);
      mostrar(f.querySelector('[data-campo=unidad]'), !mo && !sub);      // la hora de mano de obra no se convierte: depende de la jornada
      el.unidad.value = d.unidad || ''; el.factor.value = '';
      var bf = f.querySelector('[data-bloque-factor]'); bf.classList.add('hidden'); bf.classList.remove('flex');
      mostrar(f.querySelector('[data-campo=mo]'), mo);
      mostrar(f.querySelector('[data-campo=desperdicio]'), d.tipo === 'materiales' && !sub);
      mostrar(f.querySelector('[data-campo=precio]'), !sub && !!d.precioActual);   // sin precio se carga en la propia fila
      dlgEd.showModal();
    }
    function abrirRevision(tr) {
      if (!dlgRev || !tr) return;
      filaActual = tr; sugerenciaFila = null;
      var d = tr.dataset;
      dlgRev.querySelector('[data-titulo]').textContent = 'Revisar «' + d.nombre + '» con IA';
      mostrar(dlgRev.querySelector('[data-bloque-precio]'), !!d.insumoId);
      var res = dlgRev.querySelector('[data-resultado-precio]'); res.innerHTML = ''; mostrar(res, false);
      var cant = d.tipo === 'mano_obra' ? (d.personas || '?') + ' persona(s), ' + d.cantidad + ' h por unidad' : d.cantidad + ' ' + (d.unidad || '');
      dlgRev.querySelector('[data-instruccion]').value = 'Revisa la cantidad de «' + d.nombre + '» (' + cant + ') frente al alcance del APU y corrígela solo si no es coherente.';
      dlgRev.showModal();
    }
    if (dlgEd) {
      var enviarEdicion = function (f, datos) {
        bloquear(f, true);
        post(cfg.url_fila, datos).then(function (res) {
          bloquear(f, false);
          if (!res.ok && res.data.necesita_factor) {   // unidad que no se convierte sola: se pide el factor
            f.querySelector('[data-factor-de]').textContent = res.data.unidad_actual;
            f.querySelector('[data-factor-a]').textContent = res.data.unidad_nueva;
            var bf = f.querySelector('[data-bloque-factor]'); bf.classList.remove('hidden'); bf.classList.add('flex');
            avisar(res.data.message, 'warning'); f.elements.factor.focus();
            return;
          }
          if (!res.ok) { avisar(res.data.message, 'error'); return; }
          dlgEd.close(); avisar(res.data.message, 'success'); refrescar();
        });
      };
      dlgEd.querySelector('form').addEventListener('submit', function (e) {
        e.preventDefault();
        var f = e.target, el = f.elements, d = filaActual.dataset;
        var datos = { tipo: d.tipo, indice: d.indice, cantidad: el.cantidad.value, personas: el.personas.value, rendimiento: el.rendimiento.value, desperdicio_pct: el.desperdicio_pct.value };
        if (!f.querySelector('[data-campo=precio]').classList.contains('hidden') && el.precio.value !== (d.precioActual || '')) { datos.precio = el.precio.value; datos.moneda = el.moneda.value; }
        if (d.tipo === 'mano_obra') delete datos.cantidad; else { delete datos.personas; delete datos.rendimiento; }
        var nueva = el.unidad.value.trim();
        var cambia = !f.querySelector('[data-campo=unidad]').classList.contains('hidden') && nueva && nueva !== (d.unidad || '');
        if (!cambia) { enviarEdicion(f, datos); return; }
        datos.unidad = nueva; datos.factor = el.factor.value;
        window.confirmarUI('La unidad de «' + d.nombre + '» pasará de «' + d.unidad + '» a «' + nueva + '» en el catálogo y en todos los APU que lo usan: ' +
          'las cantidades y los precios se convertirán para que el costo no cambie.', { titulo: 'Cambiar la unidad', aceptar: 'Convertir' })
          .then(function (ok) { if (ok) enviarEdicion(f, datos); });
      });
    }
    if (dlgRev) {
      dlgRev.querySelector('[data-revisar-precio]').addEventListener('click', function () {
        var d = filaActual.dataset, res = dlgRev.querySelector('[data-resultado-precio]');
        bloquear(dlgRev, true);
        post(cfg.url_sugerir, { insumo: d.insumoId }).then(function (r) {
          bloquear(dlgRev, false);
          if (!r.ok) { avisar(r.data.message, 'error'); return; }
          var s = (r.data.sugerencias || {})[d.insumoId];
          if (!s) { avisar('La IA no devolvió un precio para este insumo.', 'warning'); return; }
          sugerenciaFila = s;
          res.innerHTML = '<span>Sugerido: <strong class="tabular-nums">' + esc(s.precio) + ' ' + esc(s.moneda) + '</strong></span> ' +
            '<span class="badge badge-soft badge-sm ' + (CONFIANZA[s.confianza] || 'badge-ghost') + '">confianza ' + esc(s.confianza) + '</span> ' +
            '<button type="button" class="btn btn-primary btn-xs" data-usar-precio-fila>Usar en este proyecto</button>' +
            '<span class="block text-xs text-base-content/60">' + esc(s.fuente) + (s.nota ? ' · ' + esc(s.nota) : '') + '</span>';
          mostrar(res, true);
        });
      });
      dlgRev.querySelector('[data-resultado-precio]').addEventListener('click', function (e) {
        if (!e.target.closest('[data-usar-precio-fila]') || !sugerenciaFila) return;
        var d = filaActual.dataset;
        post(cfg.url_fila, { tipo: d.tipo, indice: d.indice, precio: sugerenciaFila.precio, moneda: sugerenciaFila.moneda, estimado: true, fuente: sugerenciaFila.fuente }).then(function (r) {
          if (!r.ok) { avisar(r.data.message, 'error'); return; }
          dlgRev.close(); avisar(r.data.message, 'success'); refrescar();
        });
      });
      dlgRev.querySelector('[data-revisar-cantidad]').addEventListener('click', function () {
        var texto = dlgRev.querySelector('[data-instruccion]').value.trim();
        if (texto.length < 5) { avisar('Escribe qué quieres que revise la IA.', 'error'); return; }
        bloquear(dlgRev, true);
        progreso.iniciar(['Leyendo la composición actual…', 'Comparando con el alcance…', 'Verificando los cambios…'], 45000);
        post(cfg.url_modificar, { instruccion: texto }).then(function (r) {
          bloquear(dlgRev, false); progreso.terminar(r.ok);
          if (!r.ok) { avisar(r.data.message, 'error'); return; }
          if (r.data.sin_cambios) { dlgRev.close(); avisar(r.data.message, 'info'); return; }
          window.location.href = r.data.continuar_url;
        });
      });
    }
    raiz.addEventListener('input', function (e) {   // si la persona corrige el valor, ya no es el de la IA
      if (!e.target.matches('[data-precio]')) return;
      var fila = e.target.closest('[data-precio-fila]'), caja = fila.querySelector('[data-sugerencia]');
      if (caja && caja.getAttribute('data-precio-sug') !== e.target.value.trim().replace(',', '.')) fila.removeAttribute('data-estimado');
    });
    raiz.addEventListener('click', function (e) {
      var u = e.target.closest('[data-usar-sugerencia]');
      if (u) {
        var f = u.closest('[data-precio-fila]'), c = f.querySelector('[data-sugerencia]');
        f.querySelector('[data-precio]').value = c.getAttribute('data-precio-sug');
        f.querySelector('[data-moneda]').value = c.getAttribute('data-moneda-sug');
        f.setAttribute('data-estimado', '1');
        f.setAttribute('data-fuente', c.getAttribute('data-fuente-sug') || '');
        return;
      }
      if (e.target.closest('[data-accion=sugerir-precios]')) {
        bloquear(raiz, true);
        progreso.iniciar(['Buscando precios de referencia en la web…', 'Comparando con tu ciudad y región…', 'Ajustando unidades y moneda…'], 30000);
        post(cfg.url_sugerir, {}).then(function (res) {
          bloquear(raiz, false);
          progreso.terminar(res.ok);
          if (!res.ok) { avisar(res.data.message, 'error'); return; }
          avisar(res.data.message, 'info');
          mostrarSugerencias(res.data.sugerencias || {});
        });
        return;
      }
      var b = e.target.closest('[data-guardar-precio]');
      if (b) {
        var fila = b.closest('[data-precio-fila]');
        var datos = { insumo: fila.getAttribute('data-insumo'), precio: fila.querySelector('[data-precio]').value,
          moneda: fila.querySelector('[data-moneda]').value, fecha: cfg.hoy, region: cfg.region,
          estimado: !!fila.getAttribute('data-estimado'), fuente: fila.getAttribute('data-fuente') || '' };
        bloquear(fila, true);
        post(cfg.url_precio, datos).then(function (res) {
          bloquear(fila, false);
          if (!res.ok) { avisar(res.data.message, 'error'); return; }
          avisar(res.data.message, 'success');
          refrescar();   // sin recargar la página: se conservan las sugerencias y lo ya escrito en las demás filas
        });
        return;
      }
      var ed = e.target.closest('[data-editar-fila]');
      if (ed) { abrirEdicion(ed.closest('tr[data-fila]')); return; }
      var rv = e.target.closest('[data-revisar-fila]');
      if (rv) { abrirRevision(rv.closest('tr[data-fila]')); return; }
      if (e.target.closest('[data-accion=guardar-apu]')) {
        window.confirmarUI('Se guardará el APU en el proyecto y se descontará 1 crédito (si aún no se cobró).', { titulo: 'Guardar APU', aceptar: 'Guardar APU' }).then(function (ok) {
          if (!ok) return;
          bloquear(raiz, true);
          var titulo = raiz.querySelector('[data-actividad]');
          post(cfg.url_guardar, { actividad: titulo ? titulo.value : '' }).then(function (res) {
            bloquear(raiz, false);
            if (!res.ok) { avisar(res.data.message, 'error'); return; }
            avisar(res.data.message, 'success');
            window.location.href = res.data.continuar_url;
          });
        });
      }
    });
  }

  // ── Ficha del APU: clic en un insumo para editar su cantidad, desperdicio y precio, o quitarlo ─────────────────────
  function iniciarLineas() {
    var dlg = document.getElementById('apu-editar-linea');
    if (!dlg) return;
    var form = dlg.querySelector('[data-editar-form]');
    var fila = null;
    function abrir(tr) {
      fila = tr;
      var d = tr.dataset, esSub = !!d.subitem;
      form.querySelector('[data-titulo]').textContent = 'Editar «' + d.nombre + '»';
      form.querySelector('[data-unidad]').textContent = d.unidad ? '(' + d.unidad + ')' : '';
      form.elements.cantidad.value = d.cantidad;
      form.elements.desperdicio_pct.value = d.desperdicio;
      form.elements.precio.value = d.precio || '';
      form.elements.moneda.value = d.moneda || '';
      form.querySelector('[data-bloque-precio]').classList.toggle('hidden', esSub);
      form.querySelector('[data-bloque-unidad]').classList.toggle('hidden', esSub);
      form.elements.unidad.value = esSub ? '' : (d.unidad || '');
      form.elements.factor.value = '';
      form.querySelector('[data-bloque-factor]').classList.add('hidden');
      var ins = form.querySelector('[data-enlace-insumo]'), sub = form.querySelector('[data-enlace-sub]');
      ins.classList.toggle('hidden', esSub || !d.urlInsumo); if (d.urlInsumo) ins.href = d.urlInsumo;
      sub.classList.toggle('hidden', !esSub); if (esSub) sub.href = d.subitem;
      dlg.showModal();
      form.elements.cantidad.focus();
    }
    document.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-editar-linea]');
      var tr = e.target.closest('tr[data-linea]');
      if (!tr) return;
      if (!btn && e.target.closest('a, button, input, select, textarea, label, summary')) return;   // enlaces y controles conservan lo suyo
      abrir(tr);
    });
    function terminado(res) {
      if (!res.ok) { avisar(res.data.message, 'error'); return; }
      try { sessionStorage.setItem('apu-aviso', res.data.message); } catch (err) { /* sin storage */ }
      window.location.reload();
    }
    function guardarLinea() {
      var el = form.elements;
      var datos = { cantidad: el.cantidad.value, desperdicio_pct: el.desperdicio_pct.value, precio: el.precio.value, moneda: el.moneda.value,
        unidad: el.unidad.value, factor: el.factor.value };
      bloquear(form, true);
      post(fila.dataset.url, datos).then(function (res) {
        bloquear(form, false);
        if (!res.ok && res.data.necesita_factor) {   // unidad que no se convierte sola: se pide el factor
          form.querySelector('[data-factor-de]').textContent = res.data.unidad_actual;
          form.querySelector('[data-factor-a]').textContent = res.data.unidad_nueva;
          form.querySelector('[data-bloque-factor]').classList.remove('hidden');
          form.querySelector('[data-bloque-factor]').classList.add('flex');
          avisar(res.data.message, 'warning');
          el.factor.focus();
          return;
        }
        terminado(res);
      });
    }
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var cambia = !fila.dataset.subitem && form.elements.unidad.value.trim() && form.elements.unidad.value.trim() !== (fila.dataset.unidad || '');
      if (!cambia) { guardarLinea(); return; }
      window.confirmarUI('La unidad de «' + fila.dataset.nombre + '» pasará de «' + fila.dataset.unidad + '» a «' + form.elements.unidad.value.trim() +
        '» en todos los APU que lo usan: sus cantidades y precios se convertirán para que el costo no cambie.',
        { titulo: 'Cambiar la unidad', aceptar: 'Convertir' }).then(function (ok) { if (ok) guardarLinea(); });
    });
    form.querySelector('[data-quitar-linea]').addEventListener('click', function () {
      window.confirmarUI('«' + fila.dataset.nombre + '» dejará de formar parte de este APU. El insumo y su precio no se borran.', { titulo: 'Quitar del APU', aceptar: 'Quitar', tipo: 'peligro' })
        .then(function (ok) {
          if (!ok) return;
          bloquear(form, true);
          post(fila.dataset.urlQuitar, {}).then(function (res) { bloquear(form, false); terminado(res); });
        });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    try {
      var m = sessionStorage.getItem('apu-aviso');
      if (m) { sessionStorage.removeItem('apu-aviso'); avisar(m, 'success'); }
    } catch (e) { /* sin storage */ }
    document.querySelectorAll('form[data-apu-form]').forEach(iniciarFormAjax);
    iniciarLineas();
    document.querySelectorAll('[data-destino]').forEach(function (sel) {   // reutilizar: pide el perfil si el destino no tiene
      var bloque = sel.closest('form').querySelector('[data-bloque-perfil-destino]');
      sel.addEventListener('change', function () {
        var o = sel.options[sel.selectedIndex];
        bloque.classList.toggle('hidden', !o || !o.value || !!o.getAttribute('data-tiene'));
      });
    });
    document.addEventListener('click', function (e) {   // incidencias: restablecer y confirmar el guardado
      var r = e.target.closest('[data-restablecer]');
      if (r) { var inp = r.closest('tr').querySelector('input[data-base]'); if (inp) inp.value = inp.getAttribute('data-base'); return; }
      var c = e.target.closest('button[data-confirmar-envio]');
      if (c && !c.dataset.confirmado) {
        e.preventDefault();
        window.confirmarUI(c.getAttribute('data-confirmar-envio'), { titulo: 'Guardar incidencias', aceptar: 'Guardar' }).then(function (ok) {
          if (!ok) return;
          c.dataset.confirmado = '1';
          c.form.requestSubmit(c);
        });
      }
    });
    document.addEventListener('click', function (e) {   // modales sin inline handlers (CSP)
      var a = e.target.closest('[data-abrir-modal]');
      if (a) { var d = document.getElementById(a.getAttribute('data-abrir-modal')); if (d && d.showModal) d.showModal(); return; }
      var c = e.target.closest('[data-cerrar-modal]');
      if (c) { var dlg = c.closest('dialog'); if (dlg) dlg.close(); }
    });
    var pagina = document.querySelector('[data-apu-pagina]');
    if (!pagina) return;
    var tipo = pagina.getAttribute('data-apu-pagina');
    if (tipo === 'actividad') iniciarActividad(pagina);
    else if (tipo === 'paso') iniciarPaso(pagina);
    else if (tipo === 'resultado') iniciarResultado(pagina);
  });
})();
