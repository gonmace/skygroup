# Probar «Iniciar jornada»

## Cómo funciona
Marcar exige tres cosas a la vez (`jor_diario/servicios.py`, `verificacion.py`, `static/js/jor-passkey.js`):
1. **Celular**: el User-Agent debe ser móvil (si no, se añade el motivo `no_movil`).
2. **Passkey vinculado** (huella/PIN): un solo celular por persona (`DispositivoMarcacion`).
3. **GPS**: el navegador envía 3 lecturas; se valida edad (<15 s), precisión, saltos imposibles y distancia a la sede (`Sede.lat/lon/radio_m/precision_max_m`).

Si algo falla y la persona tiene `puede_excepcion`, escribe un motivo y la jornada queda «pendiente de aprobación»
(notifica a quien tenga `jor.excepciones.gestionar`, pantalla `jornadas/excepciones/`). Si no, se rechaza.

## Requisitos para probar
- Usuario con rol que tenga `jor.fichar` (Ejecutor/Miembro) y membresía con **sede con coordenadas**.
- En un celular real hace falta HTTPS (passkeys y GPS lo exigen): usa ngrok (`.ngrok-free.app` ya está en `ALLOWED_HOSTS`).
- En escritorio: Chrome DevTools → Sensors (ubicación) + emulación móvil + WebAuthn → virtual authenticator.

## Recorrido
1. Entrar a `/<empresa>/jornadas/` → «Aún no has iniciado tu jornada».
2. «Vincular este celular» → recarga y el botón «Iniciar jornada» se habilita.
3. En la sede → «Iniciar jornada» → «Jornada en curso».
4. Fuera del radio → error «Estás fuera del radio de la sede» (con excepción: pide motivo → pendiente).
5. Rellenar reporte (obligatorio si `exige_reporte`) → «Finalizar jornada» → Confirmar → «Jornada cerrada».

## Prueba automática (2026-11-08)
Playwright con Chromium móvil, authenticator virtual y GPS simulado, sobre una BD sqlite desechable: vincular, iniciar, rechazo fuera de sede y finalizar pasan. Se corrigió un bug: `post()` en `jor-passkey.js` mandaba un `FormData` vacío y el servidor respondía 400, impidiendo vincular y marcar.
