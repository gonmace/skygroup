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
Un superusuario **se ve como «Superusuario» (ámbar)**, no como administrador. Solo se ve como **«Administrador» (rosa)** si
además está asignado como administrador de esa empresa (`Membresia.es_admin_aqui`). En Usuarios, los administradores sin cargo
salen como filas de la tabla (rosa; más la ámbar si además es superusuario). Un superusuario que no tiene cargo ni está
asignado como administrador de esa empresa **no se lista** (no recibe mensajes ni tareas);
en la lista de Administradores (plataforma) también se muestran ambas insignias. Usar siempre las propiedades de `Membresia`
al mostrar cargo o color de una persona, nunca `m.rol.nombre` / `badge-rol-{{ m.rol.jerarquia }}` directamente:
`m.cargo_visible`, `m.clase_color`, `m.clase_avatar`. En Usuarios su cargo no es editable (se muestra fijo).

## Estándar de interfaz (regla única de estilo)

Referencia visual y viva: **`docs/estandar-interfaz.html`** (ábrelo en el navegador; el selector de arriba cambia el color de módulo).
Todo lo nuevo se construye con las clases del sistema y este estándar; no se inventan colores, radios ni sombras por pantalla.
**Excepción: los cards de módulo de Inicio (`.mod-card*`, `home/templates`) no se tocan.**

**Cuatro principios.** (1) Contorno fino de 1 px en todo lo que se toca o agrupa. (2) Color = fondo pastel + texto del color; el relleno
pleno solo al pasar el cursor. (3) El color dice algo: el del módulo (`--mod-soft/-ink/-line`) identifica dónde estás; verde, rojo, ámbar y
azul son solo de estado; violeta, rosa y ámbar de plataforma son de nivel de acceso y no se reutilizan. (4) Formas: píldora (botones,
insignias, segmentado), 12 px (campos, fichas, iconos), 16 px (tarjetas, tablas). Nada más.

- **Botones** (`.btn`): de color = pastel + contorno 1 px + texto del color; al pasar el cursor se rellenan. El principal toma el color del
  módulo; los de estado (`-success`, `-error`, `-warning`, `-info`), el suyo. Fantasma y neutro llevan anillo de 1 px. Una acción principal
  por zona. Nunca `border: 0` ni relleno sólido en reposo. Destructivas siempre con confirmación (toast).
- **Iconos** (`templates/components/icon.html`, trazo 1,8, sin relleno; 16 px junto a texto, 20 en botones de icono, 24 en encabezados,
  32 en tarjetas de módulo). Acciones repetidas en filas = solo icono con `title` y `aria-label` (nunca texto ni `▲ ▼ ✕ ✓`).
  Color por significado: ver/abrir/info = **azul**; editar/renombrar = **turquesa** (`--edit`); guardar/confirmar/agregar = **verde**;
  eliminar/borrar/error = **rojo intenso**, en botón de fila **solo el icono** (sin fondo ni contorno) y en una ficha con pastel + contorno;
  neutro/mover/fusionar/copiar = gris (copiar pasa a check verde 1,5 s); encabezados, vacíos e IA = color del módulo en ficha.
  **Icono de PDF** (`name="pdf"`): siempre con el **color propio de PDF, rojo `#d93025`** (fijo dentro de `icon.html`, no hereda el color del botón ni
  el de «error»). Va en botones de «Generar PDF» / «Descargar PDF», con o sin texto, en cualquier módulo; no se le pone `icono-ver` ni otra clase de color.
  Ficha de icono (avisos, estados, tarjetas): 38 px, 12 px de radio, pastel + contorno 1 px. Persona = círculo con iniciales.
- **Campos** (`.input`, `.select`, `.textarea`, también filtros): borde 1 px del color del módulo; al enfocar, color pleno y halo. Elegir una
  opción entre 2–4 = **control segmentado** (`.segmentado`: pista con contorno, activa = pastel + tinta + contorno), no un desplegable.
- **Interruptor**: `role="switch"`; apagado gris con contorno; encendido pastel verde + perilla verde + check; pequeño en tablas.
  Un cambio que afecta a otra persona pide confirmación en toast.
- **Tarjetas y tablas** (`.card`, `.superficie`, `.table-card`): 16 px, filete 1 px del módulo (`--elev-1/-2`) y sombra corta; las que son
  enlace (`.card-enlace`) suben 2 px al pasar el cursor. Recuadros de dato `.dato-tile` (el principal `.dato-tile-fuerte`).
  Tabla: cabecera propia, títulos en gris pequeño, línea tenue entre filas, acciones en la última columna solo con iconos.
- **Estado en filas**: franja izquierda de 4 px + fondo al 6 % + línea teñida + **insignia con icono y texto** (nunca solo color).
  Concluido/completo = verde, parcial = ámbar, vacío/sin precio = rojo, sin estado = neutro. Variante sobria (listas largas): solo franja.
- **Insignias y píldoras**: pastel + contorno fino + texto en negrita; `.dato-resumen` para cifras con punto de estado. Los cargos conservan
  `badge-rol-*`.
- **Miniaturas**: recorte centrado (`object-fit: cover`), carga diferida y `alt` siempre; 12 px de radio y contorno del módulo. Tres formatos:
  cuadrada 88 px (adjuntos), tarjeta de galería 4:3 (Registros → Imágenes) y chat (≤ 220 px). Estados: normal, hover (zoom 5 % + ojo),
  elegida, cargando, archivo, error y «+N». Acciones sobre la imagen en cuadros de 24 px; quitar = único rojo, solo icono.
- **Mensajes**: ver la sección siguiente (toast con superficie del 9 % del color del estado, contorno, ficha, título + detalle, acción
  opcional, cierre con icono y barra de tiempo que se pausa al pasar el cursor).
- **Estructura de pantalla**: enlace de vuelta, título de 24 px + descripción corta + acciones (una principal), resumen en recuadros, luego
  tablas o tarjetas.
- Dentro de un módulo (`[data-modulo]`) filete, anillos y campos toman el color del módulo; fuera de uno, gris/marca.
Las clases viven en `theme/static_src/src/styles.css`; tras tocarlas, `cd theme/static_src && npm run build`.

## Mensajes al usuario: siempre en toast (regla de interfaz)

Todo mensaje que la interfaz le muestre a la persona sale como **toast** arriba a la derecha, no como banner dentro de la
página, `alert()` ni `confirm()` del navegador:

- **Avisos** (éxito, error, advertencia, información; también los de acciones AJAX y el progreso de una operación larga):
  `window.avisar(texto, tipo, {fijo, titulo, accion: {texto, alClick}})` de `static/js/shell.js`. `tipo` es `success`, `error`, `warning` o
  `info`. El aviso lleva ficha con icono, **título** (por defecto «Listo», «No se pudo completar», «Atención», «Información») y el `texto`
  como detalle, una acción opcional («Deshacer», «Reintentar», «Ver») y cierre con icono. Se cierra solo (error a los 12 s, el resto a los
  6 s) con una barra de tiempo que se detiene al pasar el cursor; `{fijo: true}` es para el progreso (sin barra): devuelve el elemento, y quien
  lo creó lo actualiza y lo quita (`el.remove()`). `window.Alert` (Tareas) es solo un adaptador de `avisar`; no hay otro sistema de avisos.
  Estilos `.aviso*` y `.ficha*` en `styles.css`.
- **Mensajes de Django** (`messages.success/error/...` en la vista): ya los pinta `templates/shell.html` con el mismo marcado; no
  hace falta nada más.
- **Confirmaciones**: `await window.confirmarUI(mensaje, {titulo, aceptar, tipo})` (Promise<boolean>), con el mismo aspecto (ficha, título,
  mensaje y botones Cancelar + acción). En botones, formularios y `<option>` sin JS propio basta `data-confirmar="…"`. Si el mensaje es
  destructivo, `tipo: 'peligro'` (ficha roja con papelera).
- Si la página se recarga justo después de la acción, el toast se perdería: guardarlo en `sessionStorage` y mostrarlo en
  `DOMContentLoaded` (`window.avisar` se define al terminar de cargar; ver `static/js/reg-imagenes.js`).
- Las respuestas JSON de las vistas llevan un `message` legible y **específico** (qué pasó y por qué), no un «0» a secas;
  el JS lo muestra tal cual en el toast.
- Los errores de validación de un formulario junto a su campo (`templates/components/campos.html`) siguen en línea,
  porque señalan qué campo corregir; el resumen del resultado (guardado, falló) sí va en toast.

Pendientes de migrar (aún usan banner): `reg_construccion/detalle.html`, `reg_actividades/paso.html`, `jor_diario/inicio.html`, `panel/correo.html`,
`panel/almacenamiento.html`, `panel/nextcloud.html`, `panel/credenciales.html`. Al tocar una de esas pantallas, migrarla.

## Credenciales de servicios externos (propias de cada empresa)
Las claves de servicios externos (hoy: Google Maps y la API de n8n con que se mide la IA de APU) son **propias de cada
empresa** y nunca se comparten: las carga el superusuario en **empresa → Credenciales** (`/<slug>/config/credenciales/`,
menú «Empresa», contorno ámbar) y viven en `cuentas.models.CredencialesEmpresa` (una por empresa). El `.env`
(`GOOGLE_MAPS_API_KEY`, `N8N_API_URL`, `N8N_API_KEY`) es solo el respaldo del servidor para la empresa que no tiene las
suyas. Para leerlas usar siempre **con la empresa**: `CredencialesEmpresa.clave_google_maps(empresa)` /
`CredencialesEmpresa.n8n_api(empresa)` (o `reg_actividades.mapas.clave_google(empresa)`), nunca `settings.…` directo.
Una credencial nueva = un campo nuevo en ese modelo + su formulario en `panel/forms.py` (`CredencialesForm`); el campo
nunca se muestra entero (solo cómo termina). Los campos de clave deben admitir claves largas (la de n8n es un JWT de ~290).

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
- **Tokens y costo** (solo superusuario): `LlamadaIA` guarda la ejecución de n8n; el uso se lee de la API de n8n DE LA EMPRESA
  de cada llamada (empresa → Credenciales; el `.env` es el respaldo) y el costo sale de `TarifaModeloIA` (botón «Verificar tarifas»).
