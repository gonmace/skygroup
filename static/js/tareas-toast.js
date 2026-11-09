// Alertas tipo toast (reemplaza los banners estáticos de Django messages). CSP-safe:
// sin inline. Expone window.Alert = { show, success, error, warning, info, hide }.
(function () {
  'use strict';

  var ICONS = {
    success: '<svg class="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>',
    error: '<svg class="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>',
    warning: '<svg class="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
    info: '<svg class="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>'
  };
  var CLOSE_ICON = '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  var TAG_TYPE = { error: 'error', success: 'success', warning: 'warning', info: 'info', debug: 'info' };

  var Alert = {
    container: null,

    _ensureContainer: function () {
      if (this.container) return this.container;
      this.container = document.getElementById('alert-container');
      if (!this.container) {
        this.container = document.createElement('div');
        this.container.id = 'alert-container';
        this.container.className = 'toast toast-top toast-end z-50';
        document.body.appendChild(this.container);
      }
      return this.container;
    },

    show: function (message, type, options) {
      type = type || 'info';
      options = options || {};
      var autoHide = options.autoHide !== undefined ? options.autoHide : 0;
      var id = 'alert-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7);

      var el = document.createElement('div');
      el.id = id;
      el.className = 'alert alert-' + type + ' text-sm py-2 shadow-lg';
      el.style.cssText = 'opacity:0;transform:translateX(1rem);transition:opacity .2s ease,transform .2s ease';
      el.innerHTML = (ICONS[type] || ICONS.info)
        + '<span class="flex-1"></span>'
        + '<button type="button" class="alert-close shrink-0 opacity-60 hover:opacity-100" aria-label="Cerrar">' + CLOSE_ICON + '</button>';
      el.querySelector('.flex-1').textContent = message;  // texto plano: nunca se interpreta como HTML
      el.querySelector('.alert-close').addEventListener('click', function () { Alert.hide(id); });

      this._ensureContainer().appendChild(el);
      requestAnimationFrame(function () { el.style.opacity = '1'; el.style.transform = 'translateX(0)'; });

      if (autoHide > 0) setTimeout(function () { Alert.hide(id); }, autoHide);
      return id;
    },

    hide: function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.style.opacity = '0';
      el.style.transform = 'translateX(1rem)';
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 200);
    },

    success: function (msg, opts) { return this.show(msg, 'success', Object.assign({ autoHide: 5000 }, opts)); },
    error: function (msg, opts) { return this.show(msg, 'error', opts); },
    warning: function (msg, opts) { return this.show(msg, 'warning', opts); },
    info: function (msg, opts) { return this.show(msg, 'info', opts); }
  };

  window.Alert = Alert;

  // Mensajes renderizados por Django (ver base_app.html #server-messages): se muestran
  // como toasts al cargar la página y se descartan del DOM para no reprocesarlos.
  document.addEventListener('DOMContentLoaded', function () {
    var host = document.getElementById('server-messages');
    if (!host) return;
    Array.prototype.forEach.call(host.querySelectorAll('li'), function (li) {
      var type = TAG_TYPE[li.getAttribute('data-tag')] || 'info';
      Alert.show(li.textContent, type, { autoHide: 5000 });
    });
    host.remove();
  });
})();
