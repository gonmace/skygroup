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
    var timer = null;
    function pintar(valor, texto) {
      if (barra) barra.value = valor;
      if (pct) pct.textContent = Math.round(valor) + ' %';
      if (msg && texto) msg.textContent = texto;
    }
    return {
      iniciar: function (mensajes, promedioMs) {
        if (!caja) return;
        mensajes = mensajes && mensajes.length ? mensajes : ['Trabajando en ello…'];
        var inicio = Date.now(), media = Math.max(5000, promedioMs || 40000);
        caja.classList.remove('hidden');
        pintar(2, mensajes[0]);
        clearInterval(timer);
        timer = setInterval(function () {
          var t = Date.now() - inicio, v = 92 * (1 - Math.exp(-2.2 * t / media));
          pintar(v, mensajes[Math.min(mensajes.length - 1, Math.floor(v / 92 * mensajes.length))]);
        }, 300);
      },
      terminar: function (ok) {
        clearInterval(timer);
        if (!caja) return;
        if (ok) { pintar(100, 'Listo.'); setTimeout(function () { caja.classList.add('hidden'); }, 350); }
        else caja.classList.add('hidden');
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

  function iniciarFormAjax(form) {
    var progreso = Progreso(form);
    var mensajes = (form.getAttribute('data-mensajes') || '').split('|').filter(Boolean);
    var promedio = parseInt(form.getAttribute('data-promedio') || '0', 10);
    var urlRepetir = form.getAttribute('data-url-repetir');   // paso 1: ya existe el borrador → se vuelve a comprobar ahí
    var alerta = form.querySelector('[data-aviso-ia]');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (alerta) alerta.classList.add('hidden');
      var destino = form.getAttribute('data-url') || form.getAttribute('action') || window.location.href;
      bloquear(form, true);
      progreso.iniciar(mensajes, promedio);
      post(destino, valoresForm(form)).then(function (res) {
        bloquear(form, false);
        progreso.terminar(res.ok);
        var d = res.data;
        if (d.borrador_id && urlRepetir) {   // el borrador ya se creó: los siguientes envíos lo reutilizan
          form.setAttribute('data-url', urlRepetir.replace('/0/', '/' + d.borrador_id + '/'));
          var b = form.querySelector('[type=submit]');
          if (b && !res.ok) b.textContent = 'Reintentar';
        }
        if (!res.ok) { avisar(d.message, 'error'); return; }
        if (d.estado === 'proyecto_poco_claro' || d.estado === 'no_coherente') {
          if (alerta) { alerta.querySelector('[data-aviso-texto]').textContent = d.falta || d.razon || d.message; alerta.classList.remove('hidden'); }
          avisar(d.message, 'warning');
          var area = form.querySelector('[data-proyecto-descripcion]');
          if (d.estado === 'proyecto_poco_claro' && area) { area.closest('[data-bloque-descripcion]').classList.remove('hidden'); area.focus(); }
          var boton = form.querySelector('[type=submit]');
          if (boton) boton.textContent = 'Comprobar de nuevo';
          return;
        }
        avisar(d.message, 'success');
        if (d.continuar_url) window.location.href = d.continuar_url;
        else if (d.sin_cambios) { var dlg = form.closest('dialog'); if (dlg) dlg.close(); }
      });
    });
  }

  // Paso 1: según el proyecto elegido se pide su perfil de cálculo y/o su descripción.
  function iniciarActividad(raiz) {
    var info = leerJson('apu-info-proyectos') || {};
    var sel = raiz.querySelector('[name=proyecto]');
    var desc = raiz.querySelector('[data-bloque-descripcion]');
    var area = raiz.querySelector('[data-proyecto-descripcion]');
    var perfil = raiz.querySelector('[data-perfil]');
    var filtro = raiz.querySelector('[data-filtro-proyecto]');
    function actualizar() {   // el perfil se propone con el del proyecto (editable); la descripción se pide si no alcanza
      var p = info[sel.value];
      if (!p) { desc.classList.add('hidden'); return; }
      if (perfil && p.perfil_id && !perfil.dataset.tocado) perfil.value = String(p.perfil_id);
      desc.classList.toggle('hidden', !!p.descripcion_ok);
      if (area && !p.descripcion_ok && !area.value) area.value = p.descripcion;
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

    var filas = [], consultas = [], decisiones = {}, usadas = estado.usadas || 0;
    var errorInicial = false;

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
      decisiones = {};
      consultas.forEach(function (c) {
        if (c.tipo === 'opciones') {
          var op = c.opciones.filter(function (o) { return o.clave === c.recomendada; })[0] || c.opciones[0];
          decisiones[c.id] = op.clave;
          aplicarOpcion(c, op);
        } else if (estado.respuestas && estado.respuestas[c.id]) decisiones[c.id] = estado.respuestas[c.id];
      });
      if (esMO) {
        if (p.rendimiento && inRend && !inRend.value) inRend.value = p.rendimiento;
        if (p.horas_jornada && inHoras && !inHoras.value) inHoras.value = p.horas_jornada;
      }
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
          (c.motivo ? '<p class="mt-0.5 text-sm text-base-content/60">' + esc(c.motivo) + '</p>' : '') + '<div class="mt-3 space-y-2">';
        if (c.tipo === 'opciones') {
          c.opciones.forEach(function (o) {
            var marcada = decisiones[c.id] === o.clave;
            html += '<label class="flex cursor-pointer items-start gap-3 rounded-box border bg-base-100 p-3 ' + (marcada ? 'border-primary' : 'border-base-300') + '">' +
              '<input type="radio" class="radio radio-primary radio-sm mt-0.5" name="c-' + esc(c.id) + '" value="' + esc(o.clave) + '"' + (marcada ? ' checked' : '') + '>' +
              '<span class="min-w-0 flex-1 text-sm"><span class="font-medium">' + esc(o.etiqueta) + '</span>' +
              (o.clave === c.recomendada ? ' <span class="badge badge-primary badge-soft badge-sm ml-1">Recomendado</span>' : '') +
              (o.codigo_subitem ? ' <span class="badge badge-ghost badge-sm ml-1">Sub-análisis del catálogo</span>' : '') +
              ((o.filas || []).length ? '<span class="mt-0.5 block text-xs text-base-content/60">' + o.filas.map(function (f) { return esc(f.descripcion); }).join(' · ') + '</span>' : '') +
              '</span></label>';
          });
        } else {
          hayDatos = true;
          (c.opciones || []).length && (html += '<div class="flex flex-wrap gap-2">' + c.opciones.map(function (o) {
            return '<button type="button" class="btn btn-xs btn-outline" data-sugerencia="' + esc(c.id) + '" data-valor="' + esc(o.etiqueta) + '">' + esc(o.etiqueta) + '</button>';
          }).join('') + '</div>');
          html += '<textarea class="textarea textarea-bordered w-full text-sm" rows="2" data-respuesta="' + esc(c.id) + '" placeholder="Tu respuesta">' + esc(decisiones[c.id] || '') + '</textarea>';
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
          (esMO ? '' : '<td class="w-20"><input class="input input-bordered input-sm w-full" data-campo="unidad" value="' + esc(f.unidad) + '" aria-label="Unidad"' + (f.codigo_subitem ? ' disabled' : '') + '></td>') +
          '<td class="text-right">' + cant + '</td>' +
          (esMat ? '<td class="text-right"><input class="input input-bordered input-sm w-20 text-right tabular-nums" data-campo="desperdicio_pct" value="' + esc(f.desperdicio_pct) + '" inputmode="decimal" aria-label="Desperdicio %"></td>' : '') +
          (esMO ? '<td class="text-right tabular-nums text-sm text-base-content/70" data-horas-unidad>' + horasPorUnidad(f).toFixed(4) + '</td>' : '') +
          '<td class="w-24">' + badge + '</td>' +
          '<td class="w-px"><button type="button" class="btn btn-ghost btn-square btn-sm text-error" data-quitar title="Quitar" aria-label="Quitar">✕</button></td>';
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
        var op = c.opciones.filter(function (o) { return o.clave === e.target.value; })[0];
        decisiones[id] = op.clave; aplicarOpcion(c, op); pintarConsultas(); pintarTabla();
      });
      zonaConsultas.addEventListener('input', function (e) {
        var id = e.target.getAttribute('data-respuesta');
        if (id) decisiones[id] = e.target.value;
      });
      zonaConsultas.addEventListener('click', function (e) {
        var s = e.target.closest('[data-sugerencia]');
        if (s) {
          var area = zonaConsultas.querySelector('[data-respuesta="' + s.getAttribute('data-sugerencia') + '"]');
          area.value = s.getAttribute('data-valor'); decisiones[s.getAttribute('data-sugerencia')] = area.value; return;
        }
        if (e.target.closest('[data-accion=responder]')) proponer(true);
      });
    }

    function respuestasEscritas() {
      var r = {};
      consultas.forEach(function (c) { if (c.tipo === 'dato' && String(decisiones[c.id] || '').trim()) r[c.id] = decisiones[c.id].trim(); });
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
        if (!res.ok) { errorInicial = !filas.length; avisar(res.data.message, 'error'); pintarTabla(); actualizarContador(); return; }
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
    else { pintarTabla(); proponer(false); }
  }

  // ── Paso 5: precios, guardar el APU y modificar con IA ───────────────────────────────────────────────────────────
  function iniciarResultado(raiz) {
    var cfg = leerJson('apu-cfg') || {};
    raiz.addEventListener('click', function (e) {
      var b = e.target.closest('[data-guardar-precio]');
      if (b) {
        var fila = b.closest('[data-precio-fila]');
        var datos = { insumo: fila.getAttribute('data-insumo'), precio: fila.querySelector('[data-precio]').value,
          moneda: fila.querySelector('[data-moneda]').value, fecha: cfg.hoy, region: cfg.region };
        bloquear(fila, true);
        post(cfg.url_precio, datos).then(function (res) {
          bloquear(fila, false);
          if (!res.ok) { avisar(res.data.message, 'error'); return; }
          try { sessionStorage.setItem('apu-aviso', res.data.message); } catch (err) { /* sin storage */ }
          window.location.reload();
        });
        return;
      }
      if (e.target.closest('[data-accion=guardar-apu]')) {
        window.confirmarUI('Se guardará el APU en el proyecto y se descontará 1 crédito (si aún no se cobró).', { titulo: 'Guardar APU', aceptar: 'Guardar APU' }).then(function (ok) {
          if (!ok) return;
          bloquear(raiz, true);
          post(cfg.url_guardar, {}).then(function (res) {
            bloquear(raiz, false);
            if (!res.ok) { avisar(res.data.message, 'error'); return; }
            avisar(res.data.message, 'success');
            window.location.href = res.data.continuar_url;
          });
        });
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    try {
      var m = sessionStorage.getItem('apu-aviso');
      if (m) { sessionStorage.removeItem('apu-aviso'); avisar(m, 'success'); }
    } catch (e) { /* sin storage */ }
    document.querySelectorAll('form[data-apu-form]').forEach(iniciarFormAjax);
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
