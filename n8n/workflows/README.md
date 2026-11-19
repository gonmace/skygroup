# Workflows de n8n versionados

Exports de los workflows que usa skygroup. En desarrollo el contenedor `skygroup_n8n` (`docker compose -f
docker-compose.dev.yml --profile n8n up -d`) monta esta carpeta en `/home/node/.n8n/workflows-import` (solo lectura).
Importar uno: `docker exec skygroup_n8n n8n import:workflow --input=/home/node/.n8n/workflows-import/<archivo>.json`.
Producción: `make n8n-import` (después de validar en desarrollo).

Credencial necesaria: **OpenAI** (`openAiApi`) con el nombre «OpenAi account». Tras importar, abre cada workflow, elige la
credencial en sus nodos «Modelo …» y actívalo (o `n8n publish:workflow --id=<id>` y reinicia el contenedor).

## APU (Análisis de Precios Unitarios con IA)

Reglas de construcción (para poder editarlos y mejorarlos a mano desde la interfaz de n8n):
- Solo nodos nativos (Webhook, Edit Fields, Switch, IF, AI Agent + OpenAI Chat Model, Structured Output Parser, Respond to
  Webhook). **Sin nodos Code.**
- **El prompt y el modelo de cada agente ya NO viven en n8n**: skygroup los manda en el payload (`body.ia.<paso>` =
  `{prompt, modelo, razonamiento, version}`) y se editan en la web (**APU → Plantillas**, solo superusuario; cada tipo de
  trabajo —obras civiles, montaje, eléctrica, mantenimiento…— tiene los suyos, con historial de versiones). El nodo
  **«Prompt · …»** (Edit Fields) solo lee `body.ia.<paso>.prompt` y llega al agente con `{{ $json.system_prompt }}`; el nodo
  «Modelo …» lee `body.ia.<paso>.modelo` y `.razonamiento`. n8n queda como ejecutor: agente, modelo, búsqueda web, esquema de
  salida. Si falta el prompt, Django lo dice y no llama a n8n (no hay prompt de respaldo aquí).
- El esquema de cada salida está en su nodo «Esquema · …» (Structured Output Parser). Si lo cambias, revisa
  `apu_generador/ia.py` (normalización) y la tabla de abajo.
- Todos responden `ejecucion_id` (`$execution.id`): skygroup lo usa para medir los tokens de cada ejecución con la API
  pública de n8n (`N8N_API_URL` / `N8N_API_KEY`).
- Ningún payload ni prompt lleva país: el contexto lo dan la descripción del proyecto y el catálogo de la empresa.

| Archivo | Workflow (id) | Webhook | Modelos |
|---|---|---|---|
| `APU_01coherencia.json` | APU · 01 Coherencia (`apu0coherencia01`) | `apu-coherencia` | el de cada prompt (web) |
| `APU_02-04insumos.json` | APU · 02-04 Insumos (`apu0insumos0001`) | `apu-insumos` | el de cada prompt (web) |
| `APU_05modificar.json` | APU · 05 Modificar (`apu0modificar001`) | `apu-modificar` | el de cada prompt (web) |
| `APU_06tarifas.json` | APU · 06 Tarifas (`apu0tarifas00001`) | `apu-tarifas` | gpt-5.1 con búsqueda web (fijo; no depende del tipo de trabajo) |
| `APU_07precios.json` | APU · 07 Precios estimados (`apu0precios00001`) | `apu-precios` | el de su prompt (web); necesita el modelo con búsqueda web |

### `apu-coherencia`
Entrada: `{actividad, unidad, descripcion, region, proyecto:{nombre, descripcion, tipo, ciudad, region}, categorias:[nombre…], historial:[{pregunta,respuesta}] (preguntas de alcance ya respondidas), ultima_ronda, ia:{coherencia, clasificacion}}` (las categorías de APU de la empresa; la IA debe reutilizar una exacta y solo proponer una nueva si ninguna sirve).
Salida (una de; el proyecto y su descripción se dan por correctos, solo se revisa la actividad):
- `{coherente:false, razon, ejecucion_id}`;
- `{coherente:true, sistema_constructivo, tipo_elemento, material_principal, proceso_principal, categoria, actividad_ajustada?, alcance?, ejecucion_id}` (`actividad_ajustada`: el título sin la cantidad total; `alcance`: esa cantidad con su unidad; `resumen_alcance`: 3 a 6 frases con lo que cubre el ítem por 1 unidad, que se guarda en `APUBorrador.resumen_alcance` (interno: la persona no lo ve ni lo edita; se define con las preguntas) y viaja a `apu-insumos`; `consultas`: preguntas para cerrar el alcance, mismo formato que en `apu-insumos`, vacías si no falta nada; con ellas Skygroup deja el borrador en el paso 1, y en `ultima_ronda` no se hacen).

### `apu-insumos`
Entrada: `{ia:{<tipo>, verificar}, tipo: materiales|mano_obra|equipos, actividad, unidad, region, resumen_alcance (siempre presente: ya resume el proyecto y los detalles, por eso NO se mandan `proyecto` ni `descripcion`), clasificacion, confirmado,
catalogo:[{codigo,descripcion,unidad}], catalogo_items:[…], decisiones_previas:[{pregunta,elegida}],
aclaraciones:[{pregunta,respuesta}] (lo respondido en otros pasos), historial:[{pregunta,respuesta}], ultima_ronda}`.
Si el título es genérico y faltan datos que definen la composición (p. ej. «Hormigón armado»: resistencia, elemento, tipo
de armadura…), la primera respuesta trae solo `consultas` de tipo `dato` y `filas` vacío.
Salida: `{filas:[{descripcion, unidad, cantidad | personas, desperdicio_pct, codigo_catalogo, codigo_subitem, nuevo,
justificacion, check}], consultas:[{id, tipo: opciones|dato, pregunta, motivo, recomendada, opciones:[{clave, etiqueta,
codigo_subitem, filas}]}], rendimiento?, horas_jornada?, ejecucion_id}`.
Un segundo agente (modelo mini) deja `check:false` en las filas no esenciales.
TODA consulta (`opciones` o `dato`) trae `recomendada` (la clave de la opción que recomienda la IA) y `por_que` (por qué); en las
consultas `dato` las opciones son respuestas sugeridas, la más recomendable primero. Skygroup las muestra como «Recomendado» y
deja la respuesta recomendada ya escrita para que la persona la acepte o la corrija.

### `apu-modificar`
Entrada: `{ia:{modificar, verificar_titulo}, instruccion, actividad, unidad, resumen_alcance, apu:{materiales,mano_obra,equipos}, catalogo, catalogo_items}`. `resumen_alcance` es el alcance guardado en el APU (`ItemModelo.resumen_alcance`); un APU anterior al alcance manda en su lugar un texto con el proyecto. No se manda `proyecto` aparte.
Salida: `{materiales:{filas}, mano_obra:{filas, rendimiento, horas_jornada}, equipos:{filas}, actividad, resumen_cambios,
ejecucion_id}`. `actividad` es el título del APU: la IA lo ajusta si la instrucción cambia lo que describe (p. ej. «Hormigón H21
en columnas» → «Hormigón H25 en vigas») y lo devuelve igual si no; solo el título, sin unidad ni paréntesis. En skygroup es un cambio
más de la página de revisión, y el título también se puede editar en el paso 5. Un segundo agente (modelo mini)
verifica el título y la unidad contra la composición resultante y la instrucción y devuelve además `unidad` (la original salvo que
cambie lo que se mide) y `motivo_titulo` (por qué cambió, que skygroup muestra bajo el campo); ambos se revisan como cambios más.

### `apu-tarifas`
Entrada: `{modelos:[…]}`. Salida: `{tarifas:[{modelo, entrada_usd_mtok, salida_usd_mtok}], fuente, ejecucion_id}`.

### `apu-precios`
Precios de referencia (RECOMENDACIÓN, no oficiales) de los insumos sin precio. Entrada: `{ia:{precios}, moneda, region, fecha,
insumos:[{id, descripcion, unidad, tipo}]}`. Salida: `{precios:[{id, precio, moneda, confianza: alta|media|baja,
fuente, nota}], ejecucion_id}`. Skygroup los muestra como sugerencia en el paso de precios; los que la persona acepta se
guardan en `PrecioInsumo` con `estimado=True`.

### Prueba rápida
```bash
curl -sS -X POST "$N8N_BASE_URL/webhook/apu-coherencia" -H 'Content-Type: application/json' \
  -d '{"actividad":"Muro de ladrillo 6H e=12 cm","unidad":"m2","descripcion":"","region":"","proyecto":{"nombre":"Escuela","descripcion":"Escuela de dos plantas con muros de ladrillo, losa alivianada y terminaciones sencillas para uso educativo.","tipo":"","ciudad":"Tarija","region":""}}'
```
