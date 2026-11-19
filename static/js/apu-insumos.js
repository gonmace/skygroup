// Insumos (APU): seleccionar y eliminar en bloque. Solo se carga para el superusuario; el servidor lo vuelve a exigir.
(function () {
  var barra = document.querySelector('[data-bulk]');
  if (!barra) return;
  var form = document.getElementById('form-bulk');
  var inTodos = form.querySelector('[data-todos]');
  var selPagina = barra.querySelector('[data-sel-pagina]');
  var btnFiltrados = barra.querySelector('[data-sel-filtrados]');
  var btnEliminar = barra.querySelector('[data-eliminar]');
  var contador = barra.querySelector('[data-contador]');
  var total = parseInt(barra.getAttribute('data-total') || '0', 10);
  var enPagina = parseInt(barra.getAttribute('data-en-pagina') || '0', 10);
  var filas = Array.prototype.slice.call(document.querySelectorAll('[data-fila]'));
  var modoTodos = false;   // true: se eliminan TODOS los que cumplen el filtro, de todas las páginas

  function marcadas() { return filas.filter(function (f) { return f.checked; }).length; }
  function pintar() {
    var n = modoTodos ? total : marcadas();
    inTodos.value = modoTodos ? '1' : '';
    contador.textContent = n + (n === 1 ? ' seleccionado' : ' seleccionados');
    btnEliminar.disabled = n === 0;
    selPagina.checked = filas.length > 0 && marcadas() === filas.length;
    selPagina.indeterminate = marcadas() > 0 && marcadas() < filas.length;
    // si hay más insumos que los de esta página, se ofrece seleccionarlos todos
    btnFiltrados.classList.toggle('hidden', modoTodos || !(selPagina.checked && total > enPagina));
  }
  selPagina.addEventListener('change', function () {
    modoTodos = false;
    filas.forEach(function (f) { f.checked = selPagina.checked; });
    pintar();
  });
  filas.forEach(function (f) { f.addEventListener('change', function () { modoTodos = false; pintar(); }); });
  btnFiltrados.addEventListener('click', function () { modoTodos = true; filas.forEach(function (f) { f.checked = true; }); pintar(); });
  btnEliminar.addEventListener('click', function () {
    var n = modoTodos ? total : marcadas();
    if (!n) return;
    var texto = '¿Eliminar ' + n + ' insumo' + (n === 1 ? '' : 's') + '? Los que usa algún APU no se borran. Esta acción no se puede deshacer.';
    var enviar = function () { form.submit(); };
    if (window.confirmarUI) window.confirmarUI(texto, { titulo: 'Eliminar insumos', aceptar: 'Eliminar', tipo: 'peligro' }).then(function (ok) { if (ok) enviar(); });
    else enviar();
  });
  pintar();
})();
