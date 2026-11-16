// Alertas tipo toast de Tareas. Ahora son un adaptador de window.avisar (static/js/shell.js), que es el único sistema de avisos:
// expone window.Alert = { show, success, error, warning, info, hide } con la misma firma de antes.
(function () {
  'use strict';

  var TAG_TYPE = { error: 'error', success: 'success', warning: 'warning', info: 'info', debug: 'info' };
  var vivos = {};

  var Alert = {
    show: function (message, type, options) {
      type = TAG_TYPE[type] || 'info';
      options = options || {};
      if (!window.avisar) return null;
      var el = window.avisar(message, type, { fijo: options.autoHide === 0 && options.fijo === true });
      var id = 'alert-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7);
      el.id = id; vivos[id] = el;
      return id;
    },
    hide: function (id) {
      var el = vivos[id] || document.getElementById(id);
      if (el) el.remove();
      delete vivos[id];
    },
    success: function (msg, opts) { return this.show(msg, 'success', opts); },
    error: function (msg, opts) { return this.show(msg, 'error', opts); },
    warning: function (msg, opts) { return this.show(msg, 'warning', opts); },
    info: function (msg, opts) { return this.show(msg, 'info', opts); }
  };

  window.Alert = Alert;

  // Mensajes renderizados por Django (#server-messages): se muestran como avisos al cargar y se descartan del DOM.
  document.addEventListener('DOMContentLoaded', function () {
    var host = document.getElementById('server-messages');
    if (!host) return;
    Array.prototype.forEach.call(host.querySelectorAll('li'), function (li) {
      Alert.show(li.textContent, TAG_TYPE[li.getAttribute('data-tag')] || 'info');
    });
    host.remove();
  });
})();
