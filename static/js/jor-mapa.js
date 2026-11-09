// Mapa de ubicaciones de jornadas (solo administradores): dónde marcó cada persona al iniciar y al finalizar.
// Sin estilos ni scripts inline: el CSP solo permite 'self'. Los datos llegan en <script id="jor-puntos">.
(function () {
  'use strict';

  var SATELITE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
  var CALLES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  var COLORES = { inicio: '#16a34a', fin: '#dc2626' };   // inicio verde, cierre rojo (mismos que la leyenda)
  var RADIO = { inicio: 11, fin: 6 };                      // el cierre más pequeño: si coinciden, el inicio no queda tapado
  var TITULO = { inicio: 'Inicio', fin: 'Cierre' };

  function popup(p) {
    var d = document.createElement('div');
    var a = document.createElement('a');
    a.href = p.url; a.textContent = p.nombre; a.className = 'font-semibold';
    d.appendChild(a);
    [TITULO[p.tipo] + ' · ' + p.hora + (p.precision != null ? ' · ±' + p.precision + ' m' : ''), p.verificacion]
      .forEach(function (t) { var l = document.createElement('div'); l.textContent = t; d.appendChild(l); });
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
          Object.keys(bs).forEach(function (k) { bs[k].setAttribute('aria-pressed', k === cual); });
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
    var lienzo = document.querySelector('[data-jor-mapa]');
    var datos = document.getElementById('jor-puntos');
    if (!lienzo || !datos || typeof L === 'undefined') return;
    var puntos = JSON.parse(datos.textContent || '[]');
    if (!puntos.length) return;
    var mapa = L.map(lienzo, { maxZoom: 21 });
    var satelite = L.tileLayer(SATELITE, { attribution: '© Esri', maxZoom: 21, maxNativeZoom: 19 });
    var calles = L.tileLayer(CALLES, { attribution: '© OpenStreetMap', maxZoom: 21, maxNativeZoom: 19 });
    selector(mapa, satelite, calles);
    puntos.slice().sort(function (a, b) { return (a.tipo === 'fin') - (b.tipo === 'fin'); })   // los cierres se dibujan encima
      .forEach(function (p) {
      var tip = document.createElement('span');
      tip.textContent = p.nombre + ' · ' + TITULO[p.tipo] + ' ' + p.hora;   // elemento: Leaflet insertaría un string como HTML
      L.circleMarker([p.lat, p.lon], {
        radius: RADIO[p.tipo], color: '#fff', weight: 2, fillColor: COLORES[p.tipo], fillOpacity: 1
      }).bindPopup(popup(p)).bindTooltip(tip).addTo(mapa);
    });
    var ll = puntos.map(function (p) { return [p.lat, p.lon]; });
    if (ll.length > 1) mapa.fitBounds(L.latLngBounds(ll), { padding: [30, 30], maxZoom: 17 });
    else mapa.setView(ll[0], 16);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar); else iniciar();
})();
