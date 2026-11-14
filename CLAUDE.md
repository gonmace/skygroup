# SkyGroup — reglas del proyecto

## Colores por nivel de acceso (regla de interfaz)

Los colores identifican **quién accede**. Al agregar o cambiar pantallas, menús o insignias, respétalos:

| Nivel | Color | Clase CSS | Dónde |
|---|---|---|---|
| Cargo Coordinador (A) | violeta | `badge-rol-0` | cargos, avatares, insignias |
| Ejecutor (R) / Especialista (C) / Observador (I) | azul / verde / gris | `badge-rol-1` / `-2` / `-3` | ídem |
| Administrador de sistema | rosa | `badge-plat-admin` | cabecera, lista de Administradores |
| Superusuario | ámbar | `badge-plat-super` | cabecera, lista de Administradores |

No usar estos colores para otra cosa (el rojo es solo para errores/«Bloqueado»; el azul de marca no identifica un rol).
Las clases viven en `theme/static_src/src/styles.css`; tras tocarlas, recompilar con `cd theme/static_src && npm run build`.

### Barra lateral: contorno suave según quién accede
Cada entrada del menú (`panel/menu.py`) lleva un `nivel`:
- **`coordinador`** → contorno suave **violeta** (`nav-nivel badge-rol-0`): la entrada exige una capacidad que el Ejecutor
  (`RolBase.MIEMBRO`) **no** tiene por defecto. Se calcula solo con `cuentas.capacidades.solo_coordinador(capacidad)`;
  no se marca a mano.
- **`superusuario`** → contorno suave **ámbar** (`nav-nivel badge-plat-super`): entradas de Plataforma, `solo_superusuario=True`
  y las que solo ve el superusuario dentro de una empresa (p. ej. Nextcloud).
- **Sin nivel** → sin contorno: accesos que también tiene el Ejecutor.

Al registrar una entrada nueva (`registrar_item`) basta con indicar su `capacidad` (o `solo_superusuario=True`); el color sale
de ahí. Las entradas creadas a mano en `_items_config`, `construir_menu` y `_items_plataforma` deben pasar `nivel=` con
`_nivel_item(...)`. Si un menú nuevo no sigue esta regla, el contorno no aparecerá.

### Cabecera
Bajo el nombre del usuario (arriba a la derecha) se muestra su **cargo** en la empresa activa (color de su nivel); si no
tiene cargo, su papel de plataforma («Administrador» rosa). **Un superusuario siempre se identifica como «Superusuario»
(ámbar)**, aunque además sea miembro con un cargo. Lo provee `empresas.context_processors.papel_plataforma`
(`mi_cargo`, `papel_plataforma`).

### Superusuario que además es miembro de una empresa
Para el resto de la interfaz (listas de usuarios, equipo, asistencia, ficha de persona) se muestra como **«Administrador»**
(rosa), no con el cargo que tenga asignado. Usar siempre las propiedades de `Membresia` al mostrar cargo o color de una
persona, nunca `m.rol.nombre` / `badge-rol-{{ m.rol.jerarquia }}` directamente:
`m.cargo_visible`, `m.clase_color`, `m.clase_avatar`. En Usuarios su cargo no es editable (se muestra fijo).

## Mensajes al usuario: siempre en toast (regla de interfaz)

Todo mensaje que la interfaz le muestre a la persona sale como **toast** arriba a la derecha, no como banner dentro de la
página, `alert()` ni `confirm()` del navegador:

- **Avisos** (éxito, error, advertencia, información; también los de acciones AJAX y el progreso de una operación larga):
  `window.avisar(texto, tipo, {fijo})` de `static/js/shell.js`. `tipo` es `success`, `error`, `warning` o `info`; se
  cierra solo (error a los 12 s, el resto a los 6 s) salvo `{fijo: true}`, pensado para el progreso: devuelve el
  elemento, y quien lo creó lo actualiza y lo quita (`el.remove()`).
- **Mensajes de Django** (`messages.success/error/...` en la vista): ya los pinta `templates/shell.html` como toast; no
  hace falta nada más.
- **Confirmaciones**: `await window.confirmarUI(mensaje, {titulo, aceptar, tipo})` (Promise<boolean>), también con forma
  de toast. En botones y formularios sin JS propio basta `data-confirmar="…"`. Si el mensaje es destructivo, `tipo: 'peligro'`.
- Si la página se recarga justo después de la acción, el toast se perdería: guardarlo en `sessionStorage` y mostrarlo en
  `DOMContentLoaded` (`window.avisar` se define al terminar de cargar; ver `static/js/reg-imagenes.js`).
- Las respuestas JSON de las vistas llevan un `message` legible y **específico** (qué pasó y por qué), no un «0» a secas;
  el JS lo muestra tal cual en el toast.
- Los errores de validación de un formulario junto a su campo (`templates/components/campos.html`) siguen en línea,
  porque señalan qué campo corregir; el resumen del resultado (guardado, falló) sí va en toast.

Pendientes de migrar (aún usan banner o diálogo del navegador): `static/js/jor-marcar.js` (`alert`),
`reg_construccion/detalle.html`, `reg_actividades/paso.html`, `jor_diario/inicio.html`, `panel/correo.html`,
`panel/almacenamiento.html`, `panel/nextcloud.html`, `panel/credenciales.html`. Al tocar una de esas pantallas, migrarla.

## Credenciales de servicios externos
Las claves de servicios externos de la plataforma (hoy: Google Maps) se cargan en **Plataforma → Credenciales** (solo
superusuario) y viven en `cuentas.models.CredencialesPlataforma` (una sola para todas las empresas). El `.env`
(`GOOGLE_MAPS_API_KEY`) es solo el respaldo. Para leer la clave usar `CredencialesPlataforma.clave_google_maps()` (o
`reg_actividades.mapas.clave_google()`), nunca `settings.GOOGLE_MAPS_API_KEY` directo. Una credencial nueva = un campo
nuevo en ese modelo + su formulario en `panel/forms.py` (`CredencialesForm`); el campo nunca se muestra entero.
