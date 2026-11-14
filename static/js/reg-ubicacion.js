// Botón «Usar mi ubicación» del widget de ubicación GPS. CSP-safe: sin inline.
// Mientras captura muestra un spinner y escucha el GPS (watchPosition) para quedarse con la lectura más precisa:
// se detiene al llegar a OBJETIVO_M o al agotar MAX_MS, y conserva la mejor que haya visto.
(function () {
  'use strict';

  var OBJETIVO_M = 10;     // con ±10 m o menos no se espera más
  var MAX_MS = 20000;      // tiempo máximo afinando

  // Misma escala que el servidor (reg_actividades/widgets/ubicacion.py): ≤20 m buena, ≤50 m media, más, baja.
  function calidad(m) {
    return m <= 20 ? ['Precisión buena', 'badge-success'] : m <= 50 ? ['Precisión media', 'badge-warning'] : ['Precisión baja', 'badge-ghost'];
  }

  document.querySelectorAll('[data-ubicacion]').forEach(function (caja) {
    var boton = caja.querySelector('[data-usar-gps]');
    if (!boton) return;
    var estado = caja.querySelector('[data-gps-estado]');
    var chip = caja.querySelector('[data-precision-chip]');
    var spinner = caja.querySelector('[data-gps-spinner]');
    var icono = caja.querySelector('[data-gps-icono]');
    var vigilia = null, reloj = null, mejor = null;

    var lat = caja.querySelector('[data-lat]'), lon = caja.querySelector('[data-lon]');
    var lectura = caja.querySelector('[data-lectura]'), titulo = caja.querySelector('[data-lectura-titulo]');
    var disco = caja.querySelector('[data-lectura-icono]');
    function refrescarLectura() {   // la lectura grande sigue a los campos (captura o edición a mano)
      var hay = lat.value.trim() !== '' && lon.value.trim() !== '';
      if (lectura) lectura.textContent = hay ? lat.value.trim() + ', ' + lon.value.trim() : '—';
      if (titulo) titulo.textContent = hay ? 'Ubicación registrada' : 'Sin ubicación';
      // «Google Maps» abre lo que hay en pantalla, aunque aún no se haya guardado el paso.
      var enlaces = caja.querySelectorAll('[data-mapa-enlace]');
      var la = parseFloat(lat.value.replace(',', '.')), lo = parseFloat(lon.value.replace(',', '.'));
      var valido = hay && isFinite(la) && isFinite(lo);
      enlaces.forEach(function (a) {
        if (valido) a.href = 'https://maps.google.com/?q=' + la + ',' + lo;
        a.classList.toggle(a.getAttribute('data-modo'), !valido);
      });
      if (disco) {
        ['bg-success/15', 'text-success'].forEach(function (c) { disco.classList.toggle(c, hay); });
        ['bg-base-300', 'text-base-content/50'].forEach(function (c) { disco.classList.toggle(c, !hay); });
      }
    }

    // ── Grados, minutos y segundos ⇄ decimal. Los campos con `name` son los decimales (lo único que se envía). ──
    var EJES = { lat: { campo: lat, pos: 'N', neg: 'S', max: 90 }, lon: { campo: lon, pos: 'E', neg: 'W', max: 180 } };
    function dms(eje, parte) { return caja.querySelector('[data-dms="' + eje + '-' + parte + '"]'); }
    function num(v) { return parseFloat(String(v).trim().replace(',', '.')); }

    function decimalAGms(eje) {   // decimal → campos °′″ (si el decimal está vacío o es inválido, los vacía)
      var e = EJES[eje], g = dms(eje, 'g');
      if (!g) return;
      var v = num(e.campo.value);
      if (!isFinite(v)) { ['g', 'm', 's'].forEach(function (p) { dms(eje, p).value = ''; }); return; }
      var a = Math.abs(v), grados = Math.floor(a), resto = (a - grados) * 60, min = Math.floor(resto);
      var seg = Math.round((resto - min) * 60 * 100) / 100;
      if (seg >= 60) { seg = 0; min += 1; }
      if (min >= 60) { min = 0; grados += 1; }
      g.value = grados; dms(eje, 'm').value = min; dms(eje, 's').value = seg;
      dms(eje, 'h').value = v < 0 ? e.neg : e.pos;
    }
    function gmsADecimal(eje) {   // campos °′″ → decimal (solo si son válidos; no pisa lo escrito si falta algo)
      var e = EJES[eje], g = num(dms(eje, 'g').value);
      var m = dms(eje, 'm').value.trim() === '' ? 0 : num(dms(eje, 'm').value);
      var sg = dms(eje, 's').value.trim() === '' ? 0 : num(dms(eje, 's').value);
      if (!isFinite(g) || !isFinite(m) || !isFinite(sg) || g < 0 || m < 0 || m >= 60 || sg < 0 || sg >= 60) return;
      var v = g + m / 60 + sg / 3600;
      if (v > e.max) return;
      e.campo.value = ((dms(eje, 'h').value === e.neg ? -1 : 1) * v).toFixed(6);
      refrescarLectura();
    }
    function sincronizarGms() { decimalAGms('lat'); decimalAGms('lon'); }
    ['lat', 'lon'].forEach(function (eje) {
      ['g', 'm', 's', 'h'].forEach(function (p) {
        var c = dms(eje, p);
        if (c) c.addEventListener(p === 'h' ? 'change' : 'input', function () { gmsADecimal(eje); });
      });
    });
    lat.addEventListener('input', function () { refrescarLectura(); decimalAGms('lat'); });
    lon.addEventListener('input', function () { refrescarLectura(); decimalAGms('lon'); });
    sincronizarGms();

    // Selector de formato (decimal / grados, min, seg).
    var panelDec = caja.querySelector('[data-panel-dec]'), panelGms = caja.querySelector('[data-panel-dms]');
    caja.querySelectorAll('[data-modo-coord]').forEach(function (b) {
      b.addEventListener('click', function () {
        var gms = b.getAttribute('data-modo-coord') === 'dms';
        if (panelDec) panelDec.classList.toggle('hidden', gms);
        if (panelGms) panelGms.classList.toggle('hidden', !gms);
        caja.querySelectorAll('[data-modo-coord]').forEach(function (o) {
          var activo = o === b;
          o.classList.toggle('btn-neutral', activo);
          o.setAttribute('aria-pressed', activo ? 'true' : 'false');
        });
      });
    });
    function mensaje(t) { if (estado) estado.textContent = t; }
    function ocupado(si) {
      boton.disabled = si;
      boton.setAttribute('aria-busy', si ? 'true' : 'false');
      if (spinner) spinner.classList.toggle('hidden', !si);
      if (icono) icono.classList.toggle('hidden', si);
    }
    function escribir(c) {
      var m = Math.round(c.accuracy);
      lat.value = c.latitude.toFixed(6);
      lon.value = c.longitude.toFixed(6);
      refrescarLectura();
      sincronizarGms();
      caja.querySelector('[data-acc]').value = m;
      if (chip) {
        var q = calidad(m);
        chip.className = 'badge gap-1 ' + q[1];
        chip.textContent = q[0] + ' (±' + m + ' m)';
      }
    }
    function terminar(error) {
      if (vigilia !== null) { navigator.geolocation.clearWatch(vigilia); vigilia = null; }
      if (reloj !== null) { clearTimeout(reloj); reloj = null; }
      ocupado(false);
      if (!mejor) { mensaje(error || 'No se pudo obtener la ubicación (revisa el permiso del navegador).'); return; }
      var m = Math.round(mejor.accuracy);
      mensaje('Ubicación capturada (±' + m + ' m). ' + (m > 50 ? 'La precisión es baja: sal a cielo abierto y vuelve a intentar. ' : '') + 'Guarda el paso para conservarla.');
    }

    boton.addEventListener('click', function () {
      if (!navigator.geolocation) { mensaje('Tu navegador no permite obtener la ubicación.'); return; }
      mejor = null;
      ocupado(true);
      mensaje('Obteniendo ubicación…');
      vigilia = navigator.geolocation.watchPosition(function (pos) {
        if (!mejor || pos.coords.accuracy < mejor.accuracy) {
          mejor = pos.coords;
          escribir(mejor);
        }
        if (mejor.accuracy <= OBJETIVO_M) { terminar(); return; }
        mensaje('Mejorando la precisión… ahora ±' + Math.round(mejor.accuracy) + ' m');
      }, function (err) {
        // Permiso denegado: no tiene caso seguir. Otro fallo: se sigue esperando hasta el límite de tiempo.
        if (err && err.code === 1) terminar('Permiso de ubicación denegado: actívalo en el navegador.');
      }, { enableHighAccuracy: true, maximumAge: 0, timeout: MAX_MS });
      reloj = setTimeout(function () { terminar(); }, MAX_MS);
    });
  });
})();
