# Prompt: crear un nuevo tipo de registro

Plantilla para pedirle a Claude Code un nuevo tipo de registro del módulo **Registros** (`reg_`).
Copia el bloque «Prompt», reemplaza cada `{…}` con los datos de la necesidad y pégalo en una sesión nueva.
Todo lo que no tenga `{}` ya está resuelto por la arquitectura del proyecto.

---

## Cómo llenarlo (guía rápida)

| Campo | Qué poner | Ejemplo |
|---|---|---|
| `{CLAVE}` | slug corto en minúsculas, va en la URL (`/registros/<clave>/…`) | `inspeccion-epp` |
| `{APP}` | nombre de la app Django, `reg_` + clave con `_` | `reg_inspeccion_epp` |
| `{MODELO}` | clase del modelo, `Reg` + CamelCase | `RegInspeccionEpp` |
| `{NOMBRE}` | nombre visible en menú y listas | `Inspección de EPP` |
| `{DESCRIPCION}` | una frase para *Tipos de registro* | `Control del equipo de protección personal en frente de obra.` |
| `{PARECIDO_A}` | tipo existente más cercano (`txtss`, `construccion`, `construccion-base`) | `construccion-base` |

---

## Prompt

````text
Necesito crear un NUEVO TIPO DE REGISTRO en el módulo Registros (reg_) de skygroup.

## 1. Necesidad
- Nombre visible: {NOMBRE}
- Clave (slug de URL): {CLAVE}
- App Django: {APP}
- Modelo: {MODELO}
- Descripción (para la pantalla «Tipos de registro»): {DESCRIPCION}
- Para qué sirve / quién lo llena / cuándo: {PROPOSITO_Y_FLUJO_DE_USO}
- Tipo existente más parecido, que debes tomar como referencia de código: {PARECIDO_A}
  (txtss = simple con alternativas A–E; construccion = visitas con tabla de avance y PDF;
  construccion-base = pasos configurables, hallazgos, revisiones y plantilla estándar)

## 2. Datos del registro
Campos propios del modelo (además de los de `reg_base.models.RegistroBase`: empresa, proyecto,
user/responsable, fecha, is_active/is_deleted, legacy_*, fotos, datos_pasos):
{LISTA_DE_CAMPOS: nombre | tipo | obligatorio | opciones/valores | etiqueta}

Regla de unicidad (condicionada a `is_deleted=False`): {CLAVE_UNICA, p. ej. proyecto+fecha, o «ninguna»}
¿Un proyecto acumula varias visitas/instancias? {SI_NO_Y_COMO_SE_DISTINGUEN}
¿Tiene estado «concluido» (concluir/reabrir)? {SI_NO}
¿Usa contratista (FK a `empresas.Contratista`, validando que sea de la misma empresa)? {SI_NO}
¿Tiene revisiones (`RevisionesMixin`, `con_revisiones=True`)? {SI_NO}
Valores denormalizados / calculados (avance, completitud, puntaje…): {CAMPOS_CALCULADOS_Y_REGLA}

## 3. Pasos y widgets (línea de tiempo del registro)
Cada paso es una etapa; cada widget de un paso es un botón de la línea de tiempo.
Widgets disponibles en `reg_actividades/widgets/` (form_dinamico, lista, camera/fotos, ubicacion,
comentario, firma, tabla, tabla_avance, poste, distancia, mapas…); si hace falta uno nuevo, créalo
con `@registrar` siguiendo `reg_actividades/widgets/base.py`.

Pasos (en orden):
{PASOS: nombre_interno | título | descripción | widgets [(slug_widget, config)] | ¿opcional? | fotos mínimas | ¿exigir_metadatos EXIF?}

¿Se siembra una plantilla estándar de pasos al activar el tipo (`al_habilitar` + `restaurar`,
como `reg_construccion_base/estandar.py`) o los pasos los define cada empresa a mano? {ESTANDAR_O_MANUAL}

## 4. Acceso y permisos
- Capacidad de lectura: `reg.{CLAVE_CON_GUION_BAJO}.ver` — visible para: {ROLES_BASE: todos / Coordinador, Ejecutor, Especialista, Observador}
- Capacidades que ya existen y se reutilizan (`reg.cargar_datos`, `reg.concluir`, `reg.reabrir`,
  `reg.cambiar_responsable`, `reg.activar`, alcance `reg.alcance.todo` / `reg.alcance.contratista`):
  {CUALES_SE_REUTILIZAN_Y_SI_HAY_ALGUNA_NUEVA_CON_SU_ROL}
- Alcance de datos: se usa `reg_base.alcance` (sin capacidad de alcance, solo ve los propios).

## 5. Salidas
- Lista: columnas, filtros y orden: {COLUMNAS_FILTROS_ORDEN}
- Detalle: {QUE_MUESTRA_Y_ACCIONES}
- PDF del reporte (patrón `reg_construccion/pdf/` + `reg_base/pdf.py`): {SI_NO_Y_CONTENIDO}
- Panel en el Resumen de Registros (`panel=` + `plantilla_panel=`): {SI_NO_Y_METRICAS}
- Entrada de menú: icono {ICONO}, orden {ORDEN}, sección {SECCION_O_NINGUNA}
- Importación / exportación (Excel, CSV): {SI_NO}

## 6. Reglas de negocio y casos borde
{REGLAS: validaciones, cálculos, bloqueos (ver reg_construccion/bloqueo.py), estados, notificaciones,
integraciones con tareas (tar_) o jornadas (jor_), etc.}

## Cómo debes hacerlo (restricciones del proyecto)
1. Explora primero `{PARECIDO_A}` (modelo, apps.py, urls.py, views.py, forms.py, templates, pdf, tests)
   y `reg_base/tipos.py`, `reg_base/apps.py`; copia su estructura y estilo, no inventes otra.
2. Crea la app `{APP}` con: `apps.py`, `models.py`, `forms.py`, `views.py`, `urls.py`, `templates/{APP}/`,
   `migrations/`, `tests.py` (+ `pdf/` y `dashboard.py` si se piden).
3. En `AppConfig.ready()` llama a `reg_base.tipos.registrar_tipo('{CLAVE}', modelo, 'reg.{CLAVE_CON_GUION_BAJO}.ver',
   '{APP}:detalle', '{NOMBRE}', descripcion=…, [al_habilitar, restaurar, panel, plantilla_panel, con_revisiones])`.
4. Registra la capacidad de lectura en `reg_base/apps.py` (`registrar('reg', {...})`) y la entrada de menú con
   `panel.menu.registrar_item('reg', …, condicion=activo('{CLAVE}'))`. No reintroduzcas roles fijos por módulo:
   solo los 4 roles base RACI (Coordinador, Ejecutor, Especialista, Observador); actualiza `ROLES.md`.
5. Añade `{APP}` a `INSTALLED_APPS` (`core/settings.py`) y `path('', include('{APP}.urls'))` en `core/urls.py`.
6. Todas las vistas: `tipo_de_request(request, '{CLAVE}')` (404 si la empresa no lo tiene activo), consultas
   siempre acotadas por `request.empresa`, alcance con `reg_base.alcance`, borrado lógico (`soft_delete`).
7. Las fotos usan `reg_fotos` y los datos de pasos `reg_actividades.DatoPaso` (relaciones genéricas ya
   incluidas en `RegistroBase`); no crees tablas paralelas. Archivos por `archivos`/`cdn`, nunca rutas locales.
8. Si el tipo debe aparecer en el Resumen (`reg_base/views.py`, tarjetas) o en la pantalla de Tipos de registro,
   intégralo ahí igual que los demás.
9. Vocabulario: «Empresa» = solo el tenant; las organizaciones externas son «Contratistas». «Proyecto» se muestra
   con el nombre propio que la empresa le dio. Textos de UI en español.
10. UI: botones de acción en tablas = solo icono de color, sin texto; fuera de tablas = icono + texto.
11. Genera y aplica migraciones (`makemigrations {APP}`; `migrate`), sin tocar migraciones existentes.
12. Tests (`python manage.py test {APP}`): modelo y unicidad, aislamiento entre empresas, permisos por rol y por
    alcance, tipo desactivado → 404, flujo crear→llenar pasos→concluir→reabrir, y PDF si aplica. Corre también
    `reg_base`, `reg_fotos` y `reg_actividades` para verificar que no hay regresiones.
13. Verifica en la app real (login, activar el tipo en *Registros → Configuración → Tipos de registro*, crear un
    registro, ver lista/detalle/PDF) antes de dar por terminado.
14. Actualiza `Readme.md` (sección «Tipos de registro»). No hagas commit salvo que lo pida.

## Entrega
Resume: archivos creados/modificados, capacidades nuevas, pasos sembrados, comandos para activar el tipo en una
empresa, resultado de los tests y lo que quedó pendiente o decidiste por tu cuenta.
````

---

## Ejemplo mínimo ya llenado

```text
Nombre: Inspección de EPP · Clave: inspeccion-epp · App: reg_inspeccion_epp · Modelo: RegInspeccionEpp
Descripción: Control del equipo de protección personal en el frente de obra.
Propósito: el ITO revisa cada día al personal del frente y marca quién incumple.
Parecido a: construccion-base
Campos: cuadrilla | CharField(80) | sí ; n_personas | PositiveInteger | sí ; n_sin_epp | PositiveInteger | sí
Unicidad: proyecto+fecha+cuadrilla · Concluido: sí · Contratista: sí · Revisiones: no
Calculado: cumplimiento_pct = (n_personas - n_sin_epp) / n_personas
Pasos: ie_datos (form_dinamico) → ie_evidencia (camera_widget, mín. 3, exigir_metadatos) → ie_firma (firma_widget)
Estándar: sí (sembrar al activar) · Lectura: todos los roles · Reutiliza reg.cargar_datos y reg.concluir
Lista: fecha, proyecto, cuadrilla, cumplimiento %, estado · PDF: sí · Panel: promedio de cumplimiento 30 días
Menú: icono shield, orden 20, sección Supervisión · Excel: no
Regla: si cumplimiento < 90 % la visita no puede concluirse sin un comentario.
```
