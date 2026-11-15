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
- Cada prompt de sistema vive en su propio nodo **«Prompt · …»** (Edit Fields) y llega al agente con
  `{{ $json.system_prompt }}`: mejorar un prompt es editar un texto.
- El esquema de cada salida está en su nodo «Esquema · …» (Structured Output Parser). Si lo cambias, revisa
  `apu_generador/ia.py` (normalización) y la tabla de abajo.
- Todos responden `ejecucion_id` (`$execution.id`): skygroup lo usa para medir los tokens de cada ejecución con la API
  pública de n8n (`N8N_API_URL` / `N8N_API_KEY`).
- Ningún payload ni prompt lleva país: el contexto lo dan la descripción del proyecto y el catálogo de la empresa.

| Archivo | Workflow (id) | Webhook | Modelos |
|---|---|---|---|
| `APU_01coherencia.json` | APU · 01 Coherencia (`apu0coherencia01`) | `apu-coherencia` | gpt-5-mini, gpt-5.1 |
| `APU_02-04insumos.json` | APU · 02-04 Insumos (`apu0insumos0001`) | `apu-insumos` | gpt-5.1, gpt-4.1-mini |
| `APU_05modificar.json` | APU · 05 Modificar (`apu0modificar001`) | `apu-modificar` | gpt-5.1 |
| `APU_06tarifas.json` | APU · 06 Tarifas (`apu0tarifas00001`) | `apu-tarifas` | gpt-5.1 con búsqueda web |
| `APU_07precios.json` | APU · 07 Precios estimados (`apu0precios00001`) | `apu-precios` | gpt-5.1 con búsqueda web |

### `apu-coherencia`
Entrada: `{actividad, unidad, descripcion, region, proyecto:{nombre, descripcion, tipo, ciudad, region}}`.
Salida (una de):
- `{proyecto_claro:false, falta, ejecucion_id}` — la descripción del proyecto no alcanza;
- `{coherente:false, razon, ejecucion_id}`;
- `{coherente:true, sistema_constructivo, tipo_elemento, material_principal, proceso_principal, categoria, ejecucion_id}`.

### `apu-insumos`
Entrada: `{tipo: materiales|mano_obra|equipos, actividad, unidad, descripcion, region, proyecto, clasificacion, confirmado,
catalogo:[{codigo,descripcion,unidad}], catalogo_items:[…], decisiones_previas:[{pregunta,elegida}],
aclaraciones:[{pregunta,respuesta}] (lo respondido en otros pasos), historial:[{pregunta,respuesta}], ultima_ronda}`.
Si el título es genérico y faltan datos que definen la composición (p. ej. «Hormigón armado»: resistencia, elemento, tipo
de armadura…), la primera respuesta trae solo `consultas` de tipo `dato` y `filas` vacío.
Salida: `{filas:[{descripcion, unidad, cantidad | personas, desperdicio_pct, codigo_catalogo, codigo_subitem, nuevo,
justificacion, check}], consultas:[{id, tipo: opciones|dato, pregunta, motivo, recomendada, opciones:[{clave, etiqueta,
codigo_subitem, filas}]}], rendimiento?, horas_jornada?, ejecucion_id}`.
Un segundo agente (modelo mini) deja `check:false` en las filas no esenciales.

### `apu-modificar`
Entrada: `{instruccion, actividad, unidad, proyecto, apu:{materiales,mano_obra,equipos}, catalogo, catalogo_items}`.
Salida: `{materiales:{filas}, mano_obra:{filas, rendimiento, horas_jornada}, equipos:{filas}, resumen_cambios, ejecucion_id}`.

### `apu-tarifas`
Entrada: `{modelos:[…]}`. Salida: `{tarifas:[{modelo, entrada_usd_mtok, salida_usd_mtok}], fuente, ejecucion_id}`.

### `apu-precios`
Precios de referencia (RECOMENDACIÓN, no oficiales) de los insumos sin precio. Entrada: `{moneda, region, fecha,
proyecto, insumos:[{id, descripcion, unidad, tipo}]}`. Salida: `{precios:[{id, precio, moneda, confianza: alta|media|baja,
fuente, nota}], ejecucion_id}`. Skygroup los muestra como sugerencia en el paso de precios; los que la persona acepta se
guardan en `PrecioInsumo` con `estimado=True`.

### Prueba rápida
```bash
curl -sS -X POST "$N8N_BASE_URL/webhook/apu-coherencia" -H 'Content-Type: application/json' \
  -d '{"actividad":"Muro de ladrillo 6H e=12 cm","unidad":"m2","descripcion":"","region":"","proyecto":{"nombre":"Escuela","descripcion":"Escuela de dos plantas con muros de ladrillo, losa alivianada y terminaciones sencillas para uso educativo.","tipo":"","ciudad":"Tarija","region":""}}'
```
