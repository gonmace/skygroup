# Probar «Iniciar jornada»

## Cómo funciona
Marcar exige (`jor_diario/servicios.py`, `verificacion.py`, `dispositivo.py`, `jor_empleados/equipos.py`, `static/js/jor-marcar.js`):
1. **Computador** por defecto; desde un celular solo si `Perfil.puede_movil` (interruptor en *Equipo*). Aplica a iniciar y a finalizar.
2. **Ubicación** obligatoria: se guarda la lectura de GPS más precisa; no hay geocerca ni validación contra la sede.
3. **Equipo habitual** (uno por tipo: computador y celular): el primero queda registrado; marcar desde otro pide un motivo y deja la jornada pendiente de revisión (administradores y/o coordinadores, según *Configuración*).

## Requisitos para probar
- Usuario con `jor.fichar` (Ejecutor/Miembro). HTTPS en un celular real (la ubicación lo exige): ngrok (`.ngrok-free.app` ya está en `ALLOWED_HOSTS`).
- En escritorio: Chrome DevTools → Sensors (ubicación) y, para el celular, emulación de dispositivo.

## Recorrido
1. Computador: `/<empresa>/jornadas/` → «Iniciar jornada» → permitir ubicación → «Jornada en curso».
2. Otro navegador o ventana de incógnito (equipo distinto): pide el motivo y queda «Pendiente de aprobación»; aparece en *Excepciones*.
3. Celular emulado sin el interruptor: aviso «Inicia tu jornada desde la computadora»; con el interruptor encendido en *Equipo*, inicia y finaliza.
4. Reporte (obligatorio si `exige_reporte`) → «Finalizar jornada» → «Jornada cerrada».
