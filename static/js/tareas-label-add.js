// Alta rápida de un tipo de actividad desde el formulario de ticket: POSTea a
// tickets:label_add (AJAX) y agrega el checkbox nuevo ya tildado a la lista, sin
// perder lo cargado en el formulario. Si el nombre ya existía, solo lo tilda.
// CSP-safe: sin inline.
(function () {
  'use strict';

  var box = document.querySelector('[data-label-add]');
  if (!box) return;
  var url = box.getAttribute('data-url');
  var nameInput = box.querySelector('[data-label-add-name]');
  var colorSelect = box.querySelector('[data-label-add-color]');
  var btn = box.querySelector('[data-label-add-btn]');
  var options = document.querySelector('[data-label-options]');
  if (!url || !nameInput || !colorSelect || !btn || !options) return;

  function getCSRF() {
    var input = document.querySelector('[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  function addOption(data) {
    var existing = options.querySelector('input[name="etiquetas"][value="' + data.id + '"]');
    if (existing) { existing.checked = true; return; }
    // Mismo markup que las opciones renderizadas por el template (ticket_form.html).
    var label = document.createElement('label');
    label.className = 'inline-flex items-center gap-1.5 cursor-pointer rounded-lg border border-base-300 px-2.5 py-1.5 hover:bg-base-200 transition-colors';
    var input = document.createElement('input');
    input.type = 'checkbox';
    input.name = 'etiquetas';
    input.value = data.id;
    input.className = 'checkbox checkbox-xs checkbox-primary';
    input.checked = true;
    var chip = document.createElement('span');
    chip.className = 'label-chip';
    chip.setAttribute('data-color', data.color);
    chip.textContent = data.name;
    label.appendChild(input);
    label.appendChild(chip);
    options.appendChild(label);
  }

  function submit() {
    var name = (nameInput.value || '').trim();
    if (!name) { nameInput.focus(); return; }
    btn.disabled = true;
    var fd = new FormData();
    fd.append('name', name);
    fd.append('color', colorSelect.value);
    fd.append('csrfmiddlewaretoken', getCSRF());
    fetch(url, { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        btn.disabled = false;
        if (!data.ok) {
          if (window.Alert) Alert.show(data.error || 'No se pudo crear el tipo de actividad.', 'error');
          return;
        }
        addOption(data);
        nameInput.value = '';
        if (window.Alert) {
          Alert.show(data.created
            ? 'Tipo de actividad «' + data.name + '» creado y seleccionado.'
            : '«' + data.name + '» ya existía — quedó seleccionado.', 'success');
        }
      })
      .catch(function () {
        btn.disabled = false;
        if (window.Alert) Alert.show('No se pudo crear el tipo de actividad.', 'error');
      });
  }

  btn.addEventListener('click', submit);
  // Enter en el input crea el tipo (y NO envía el formulario del ticket).
  nameInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); submit(); }
  });
})();
