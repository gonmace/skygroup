// Pantallas de acceso: mostrar/ocultar contraseña.
document.querySelectorAll('[data-ver-clave]').forEach((boton) => {
  const campo = document.getElementById(boton.dataset.verClave);
  if (!campo) return;
  boton.addEventListener('click', () => {
    const visible = campo.type === 'text';
    campo.type = visible ? 'password' : 'text';
    boton.setAttribute('aria-pressed', String(!visible));
    boton.setAttribute('aria-label', visible ? 'Mostrar contraseña' : 'Ocultar contraseña');
    boton.querySelector('[data-ojo]')?.classList.toggle('opacity-40', visible);
  });
});
