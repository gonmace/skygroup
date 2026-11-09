// Mapa de la lista de proyectos: un punto por proyecto (su primera ubicación), con capas Mapa/Satélite.
// Sin estilos ni scripts inline: el CSP solo permite 'self'. Los datos llegan en <script id="proyectos-puntos">.
(function () {
  'use strict';

  var SATELITE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
  var CALLES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  var COLORES = { INGENIERIA: '#7c3aed', CONSTRUCCION: '#2563eb', PARALIZADO: '#d97706', CONCLUIDO: '#16a34a', CANCELADO: '#dc2626' };

  function popup(p) {
    var d = document.createElement('div');
    var a = document.createElement('a');
    a.href = p.url; a.textContent = (p.codigo ? p.codigo + ' · ' : '') + p.nombre; a.className = 'font-semibold';
    var s = document.createElement('div');
    s.textContent = p.estado_txt;
    d.appendChild(a); d.appendChild(s);
    if (p.detalle) { var t = document.createElement('div'); t.textContent = p.detalle; d.appendChild(t); }
    return d;
  }

  function selector(mapa, satelite, calles) {
    var Control = L.Control.extend({
      options: { position: 'topright' },
      onAdd: function () {
        var caja = L.DomUtil.create('div', 'leaflet-control segmentado');
        var bs = {};
        [['calles', 'Mapa'], ['sat', 'Satélite']].forEach(function (par) {
          var b = L.DomUtil.create('button', '', caja);
          b.type = 'button'; b.textContent = par[1]; bs[par[0]] = b;
        });
        function usar(cual) {
          if (cual === 'sat') { mapa.removeLayer(calles); satelite.addTo(mapa); }
          else { mapa.removeLayer(satelite); calles.addTo(mapa); }
          Object.keys(bs).forEach(function (k) {
            bs[k].setAttribute('aria-pressed', k === cual);
          });
        }
        bs.calles.addEventListener('click', function () { usar('calles'); });
        bs.sat.addEventListener('click', function () { usar('sat'); });
        usar('calles');
        L.DomEvent.disableClickPropagation(caja);
        return caja;
      }
    });
    mapa.addControl(new Control());
  }

  function iniciar() {
    var lienzo = document.querySelector('[data-proyectos-mapa]');
    var datos = document.getElementById('proyectos-puntos');
    if (!lienzo || !datos || typeof L === 'undefined') return;
    var puntos = JSON.parse(datos.textContent || '[]');
    if (!puntos.length) return;
    var mapa = L.map(lienzo, { maxZoom: 21 });
    var satelite = L.tileLayer(SATELITE, { attribution: '© Esri', maxZoom: 21, maxNativeZoom: 19 });
    var calles = L.tileLayer(CALLES, { attribution: '© OpenStreetMap', maxZoom: 21, maxNativeZoom: 19 });
    selector(mapa, satelite, calles);
    var marcadores = puntos.map(function (p) {
      var tip = document.createElement('span');
      tip.textContent = p.nombre;   // elemento, no string: Leaflet insertaría un string como HTML
      var m = L.circleMarker([p.lat, p.lon], {
        radius: 8, color: '#fff', weight: 2, fillColor: COLORES[p.estado] || '#6b7280', fillOpacity: 1
      }).bindPopup(popup(p)).bindTooltip(tip);
      return { id: p.id, tipo: p.tipo, marcador: m, latlng: [p.lat, p.lon] };
    });

    function mostrar(tipo) {   // tipo vacío = todos; ajusta el encuadre a lo que queda visible
      var visibles = [];
      marcadores.forEach(function (x) {
        var ver = !tipo || x.tipo === tipo;
        if (ver) { x.marcador.addTo(mapa); visibles.push(x.latlng); } else { mapa.removeLayer(x.marcador); }
      });
      if (visibles.length > 1) mapa.fitBounds(L.latLngBounds(visibles), { padding: [30, 30] });
      else if (visibles.length === 1) mapa.setView(visibles[0], 15);
    }

    // Botones de tipo (uno por tipo presente, con su cantidad). Solo si hay más de un tipo que elegir.
    var cuenta = {};
    puntos.forEach(function (p) { cuenta[p.tipo] = (cuenta[p.tipo] || 0) + 1; });
    var tipos = Object.keys(cuenta).sort();
    var barra = document.querySelector('[data-mapa-tipos]');
    if (barra && tipos.length > 1) {
      var botones = [];
      [['', 'Todos', puntos.length]].concat(tipos.map(function (t) { return [t, t, cuenta[t]]; })).forEach(function (d) {
        var b = document.createElement('button');
        b.type = 'button';  b.dataset.tipo = d[0];
        b.textContent = d[1] + ' ' + d[2];
        b.addEventListener('click', function () {
          botones.forEach(function (o) {
            var on = o === b;
            o.setAttribute('aria-pressed', on);
          });
          mostrar(d[0]);
        });
        botones.push(b); barra.appendChild(b);
      });
      botones[0].setAttribute('aria-pressed', 'true');
    }
    mostrar('');

    // «Ubicar» desde la tabla: el mapa abre con todo a la vista y vuela hasta el proyecto elegido.
    var destino = lienzo.dataset.ubicar && marcadores.filter(function (x) { return String(x.id) === lienzo.dataset.ubicar; })[0];
    if (destino) {
      var reducido = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (reducido) { mapa.setView(destino.latlng, 17); destino.marcador.openPopup(); }
      else {
        mapa.flyTo(destino.latlng, 17, { duration: 1.6 });
        setTimeout(function () { destino.marcador.openPopup(); }, 1700);   // al aterrizar (moveend puede dispararse antes por invalidateSize)
      }
    }
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(function () { mapa.invalidateSize(); }).observe(lienzo);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
  else iniciar();
})();
