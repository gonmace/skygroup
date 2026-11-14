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

## Credenciales de servicios externos
Las claves de servicios externos de la plataforma (hoy: Google Maps) se cargan en **Plataforma → Credenciales** (solo
superusuario) y viven en `cuentas.models.CredencialesPlataforma` (una sola para todas las empresas). El `.env`
(`GOOGLE_MAPS_API_KEY`) es solo el respaldo. Para leer la clave usar `CredencialesPlataforma.clave_google_maps()` (o
`reg_actividades.mapas.clave_google()`), nunca `settings.GOOGLE_MAPS_API_KEY` directo. Una credencial nueva = un campo
nuevo en ese modelo + su formulario en `panel/forms.py` (`CredencialesForm`); el campo nunca se muestra entero.
