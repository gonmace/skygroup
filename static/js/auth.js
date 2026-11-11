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

// Dentro de un iframe (Nextcloud) solo se ofrece «Entrar con Nextcloud»; respaldo si el servidor no vio Sec-Fetch-Dest.
if (window.self !== window.top) {
  const nc = document.querySelector('[data-nextcloud-entrar]');
  if (nc) {
    document.querySelectorAll('[data-solo-fuera-iframe]').forEach((el) => el.classList.add('hidden'));
    nc.classList.replace('btn-outline', 'btn-primary');
  }
}
