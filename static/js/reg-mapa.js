// Widgets de mapa de Registros (mapa_1p / mapa_2_puntos): mapa Leaflet con los puntos del registro y botón que pide
// al servidor la imagen estática para el informe. Sin estilos ni scripts inline: el CSP solo permite 'self'.
(function () {
  'use strict';

  var SATELITE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
  var CALLES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';

  function tinta(hex) {   // blanco o negro según la luminancia del color del marcador
    var n = parseInt(hex.slice(1), 16), c = [n >> 16, (n >> 8) & 255, n & 255].map(function (v) {
      v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 0.18 ? '#000' : '#fff';
  }

  function marcador(p) {
    var el = document.createElement('div');
    el.className = 'reg-mapa-pin';
    el.style.setProperty('--pin', p.color);          // CSSOM: permitido por el CSP (a diferencia de style="")
    el.style.setProperty('--pin-ink', tinta(p.color));
    el.textContent = p.label;
    return L.divIcon({ className: '', html: el, iconSize: [28, 28], iconAnchor: [14, 14] });
  }

  function selectorDeCapas(mapa, satelite, calles) {
    var Control = L.Control.extend({
      options: { position: 'topleft' },
      onAdd: function () {
        var caja = L.DomUtil.create('div', 'leaflet-control join');
        var botones = {};
        [['sat', 'Satélite'], ['calles', 'Calles']].forEach(function (par) {
          var b = L.DomUtil.create('button', 'btn btn-xs join-item', caja);
          b.type = 'button'; b.textContent = par[1]; botones[par[0]] = b;
        });
        function usar(cual) {
          if (cual === 'calles') { mapa.removeLayer(satelite); calles.addTo(mapa); }
          else { mapa.removeLayer(calles); satelite.addTo(mapa); }
          botones.sat.classList.toggle('btn-neutral', cual === 'sat');
          botones.calles.classList.toggle('btn-neutral', cual === 'calles');
          botones.sat.setAttribute('aria-pressed', cual === 'sat');
          botones.calles.setAttribute('aria-pressed', cual === 'calles');
        }
        botones.sat.addEventListener('click', function () { usar('sat'); });
        botones.calles.addEventListener('click', function () { usar('calles'); });
        usar('sat');
        L.DomEvent.disableClickPropagation(caja);
        return caja;
      }
    });
    mapa.addControl(new Control());
  }

  function dibujar(w, puntos) {
    var lienzo = w.querySelector('[data-mapa-lienzo]');
    if (!lienzo || !puntos.length || typeof L === 'undefined') return;
    var mapa = L.map(lienzo, { zoomControl: false, maxZoom: 21 });
    var satelite = L.tileLayer(SATELITE, { attribution: '© Esri', maxZoom: 21, maxNativeZoom: 19 });
    var calles = L.tileLayer(CALLES, { attribution: '© OpenStreetMap', maxZoom: 21, maxNativeZoom: 19 });
    satelite.addTo(mapa);
    selectorDeCapas(mapa, satelite, calles);
    puntos.forEach(function (p) {
      L.marker([p.lat, p.lon], { icon: marcador(p), title: p.label })
        .addTo(mapa)
        .bindPopup(p.label + '<br>Lat: ' + p.lat.toFixed(6) + '<br>Lon: ' + p.lon.toFixed(6));
    });
    if (puntos.length > 1) {
      var latlngs = puntos.map(function (p) { return [p.lat, p.lon]; });
      L.polyline(latlngs, { color: '#fff', weight: 2, opacity: 0.8, dashArray: '6 4' }).addTo(mapa);
      mapa.fitBounds(L.latLngBounds(latlngs), { padding: [40, 40] });
    } else {
      mapa.setView([puntos[0].lat, puntos[0].lon], 17);
    }
    L.control.zoom({ position: 'bottomright' }).addTo(mapa);
    if (typeof ResizeObserver !== 'undefined') {   // el contenedor puede medir 0 al iniciar (pestaña/panel oculto)
      new ResizeObserver(function () { mapa.invalidateSize(); }).observe(lienzo);
    }
  }

  function formatear(m) {
    return m < 1000 ? Math.round(m) + ' m' : (m / 1000).toFixed(3) + ' km (' + Math.round(m) + ' m)';
  }

  function guardar(w) {
    var boton = w.querySelector('[data-mapa-guardar]'), estado = w.querySelector('[data-mapa-estado]');
    if (!boton) return;
    var meta = document.querySelector('meta[name="csrf-token"]');
    boton.addEventListener('click', function () {
      boton.disabled = true;
      estado.textContent = 'Generando la imagen…';
      fetch(w.dataset.saveUrl, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'X-CSRFToken': meta ? meta.content : '', 'X-Requested-With': 'XMLHttpRequest' }
      }).then(function (r) {
        return r.json().catch(function () { return { success: false, error: 'Respuesta inesperada del servidor.' }; });
      }).then(function (d) {
        if (!d.success) { estado.textContent = d.error || 'No se pudo guardar la imagen.'; return; }
        var img = w.querySelector('[data-mapa-imagen]');
        if (img) { img.src = d.image_url; img.classList.remove('hidden'); }
        var dist = w.querySelector('[data-mapa-distancia]');
        if (dist && d.distancia_total_metros != null) {
          dist.querySelector('[data-mapa-distancia-valor]').textContent = formatear(d.distancia_total_metros);
          dist.classList.remove('hidden');
        }
        boton.textContent = 'Actualizar imagen';
        estado.textContent = 'Imagen guardada.';
      }).catch(function () {
        estado.textContent = 'Error de conexión. Inténtalo de nuevo.';
      }).then(function () { boton.disabled = false; });
    });
  }

  function iniciar() {
    document.querySelectorAll('[data-mapa]:not([data-mapa-listo])').forEach(function (w) {
      w.setAttribute('data-mapa-listo', '');
      var puntos = [];
      try { puntos = JSON.parse(w.dataset.puntos || '[]'); } catch (e) { /* sin puntos */ }
      dibujar(w, puntos);
      guardar(w);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
  else iniciar();
})();
