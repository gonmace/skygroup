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
- **`administrador`** → contorno suave **rosa** (`nav-nivel badge-plat-admin`): solo superusuario y administradores de
  sistema de la empresa (`registrar_item(..., solo_admin=True)`; p. ej. APU → Usuarios).
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

## Dictado por voz en los textarea
Todo `<textarea>` (también los que se insertan por JS) recibe solo un botón de micrófono: `static/js/dictado.js`
(Web Speech API del navegador; sin soporte, p. ej. Firefox, no aparece). Escribe en la posición del cursor y dispara
`input`. Para excluir uno: `data-sin-dictado`. Estilos `.dictado-*` en `styles.css`. Los errores salen como toast.

## APU (Análisis de Precios Unitarios, módulo `apu`, en Beta)
Se llama **APU** en toda la interfaz. La palabra «especificación» no se usa en este módulo (modelos, URLs, plantillas,
campos ni textos): queda reservada para el futuro módulo de especificaciones. Tampoco se agrega nada a la app `proyectos`;
el APU solo se enlaza al proyecto por FK (`ItemModelo.proyecto`).
- **Apps**: `apu_motor` (cálculo en Python puro, sin país), `apu_catalogo` (insumos, precios, APU = `ItemModelo`,
  perfiles, incidencias por proyecto `ProyectoAPU`, base de APU) y `apu_generador` (asistente con IA, créditos, consumo).
- **Se entra desde el módulo APU** (menú lateral), no desde el proyecto. **Primer paso: habilitar un proyecto para APU**
  (APU → Proyectos → Habilitar, solo quien gestiona perfiles): se elige su perfil de cálculo —siempre uno de la empresa; una
  plantilla se copia—, la región de sus precios (`ProyectoAPU.region`, editable en Incidencias) y su descripción (≥15 palabras). El generador y «reutilizar» solo trabajan con proyectos
  habilitados (`ProyectoAPU`); sin ninguno, «Nuevo APU» lleva a habilitar. Todo APU pertenece a un proyecto; la base de APU
  se reutiliza en otros proyectos (copia con `origen`) y se puede modificar con un prompt.
- **La IA vive SOLO en n8n** (`n8n/workflows/APU_*.json`, ver su README): Django arma el payload, llama con
  `core.n8n.llamar_webhook_seguro` (vía `apu_generador/ia.py`), normaliza y guarda. Nada de SDKs de LLM ni prompts en
  Python. Los workflows se construyen con **nodos nativos editables** (sin nodos Code; prompts en nodos «Prompt · …» de
  Edit Fields; sticky notes) en el n8n de desarrollo (Docker) y luego se migran a producción. Modelo: API de OpenAI.
- **Generador** (`apu_generador`): borrador `APUBorrador` que guarda el paso; cada paso tiene un endpoint «proponer»
  (llama a n8n, no guarda) y otro «guardar» (solo lo marcado). **Sin vuelta atrás**: un paso guardado queda cerrado
  (409) y su URL redirige al paso actual. Si se corta, queda en *Pendientes*.
- **Vocabulario por empresa**: lo confirmado se agrega al catálogo `Insumo` de la empresa (sin duplicar por mayúsculas,
  tildes o espacios) y la IA debe reutilizar el término exacto. La IA pregunta ante dudas (consultas `opciones`/`dato`).
- **Créditos** (`apu_generador/creditos.py`): 1 crédito por generar (al guardar), reutilizar y cada modificación con IA.
  Límite por persona (3/día, 10/mes por defecto) y por empresa (20/día, 100/mes); si la empresa lo agota, nadie genera.
  Superusuario no consume; el administrador no tiene límite personal pero sí consume el de la empresa.
- **Jornada**: si la empresa tiene Asistencia (`jor`), todo APU exige jornada en curso (`acceso_apu`); exentos
  superusuario y administradores. Usar `acceso_apu(...)` en toda vista nueva del módulo, nunca `acceso_modulo` directo.
- **Incidencias por proyecto** (`ProyectoAPU`): ajustes de porcentaje/factor del perfil solo para ese proyecto; el precio
  unitario no se guarda, se calcula con `apu_catalogo.calculo.analizar`.
- **Eliminar un APU** (`apu_lineas:apu_eliminar`): solo quien lo creó (`ItemModelo.creado_por`) y el superusuario —ni siquiera
  otro coordinador o administrador—; un APU sin creador solo lo elimina el superusuario. Se borra su composición, no los
  insumos ni sus precios, y no se puede si otro APU lo usa como sub-análisis. Los botones solo aparecen para quien puede.
- **Semáforo de precios** (excepción a la regla de colores, pedida expresamente): en *APU → lista* la barra izquierda de
  cada fila indica qué tan completos están los precios de sus insumos (sub-análisis incluidos): verde = todos con precio,
  amarillo = faltan algunos, rojo = ninguno tiene precio (`calculo.Analisis.estado_precios`). Son colores de estado
  (`success`/`warning`/`error`), no de nivel de acceso, y siempre van con texto (leyenda, `title` y `sr-only`).
- **Precios estimados por IA**: en el paso de precios, «Sugerir precios con IA» (`apu-precios`, búsqueda web) propone
  precios de los insumos sin precio como **recomendación**: no se guardan solos ni cobran créditos; los que la persona
  acepta se guardan con `PrecioInsumo.estimado=True` y se muestran con la insignia «Estimado» hasta que los corrija.
- **Tokens y costo** (solo superusuario): `LlamadaIA` guarda la ejecución de n8n; el uso se lee de la API de n8n
  (`N8N_API_URL`/`N8N_API_KEY`) y el costo sale de `TarifaModeloIA` (botón «Verificar tarifas»).
