# Roles y permisos

**Vocabulario de la interfaz:** *Cargo* = `RolEmpresa` (nombre propio que pone cada empresa: ITO, Supervisor…). *Nivel de acceso* = `RolBase` (los cuatro roles base RACI fijos, que definen los permisos por defecto). En el código se conservan los nombres `RolEmpresa`/`rol_base`.

La plataforma tiene **cuatro roles base de empresa**, alineados a la matriz RACI de PMBOK, más el **Administrador** de la plataforma. Cada empresa pone sus propios nombres visibles encima de los roles base (`RolEmpresa`) y ajusta la matriz de permisos en *Inicio → Roles y permisos*.

| Rol base | RACI | Quién es | Ejemplos de nombre por módulo |
|---|---|---|---|
| **Administrador** | — | Administra la plataforma. Es el superusuario (`User.is_superuser`), no un rol de empresa: las empresas no lo ven ni lo asignan. | — |
| **Coordinador** | A (Accountable) | La cabeza de la empresa: responde por el resultado, administra miembros, roles y configuración, y aprueba. | reg: Coordinador de obra · tar: Coordinador · jor: Supervisor / Jefe de proyecto |
| **Ejecutor** | R (Responsible) | Ejecuta el trabajo. | reg: ITO, Buscador · tar: Ejecutor · jor: Empleado |
| **Especialista** | C (Consulted) | Asesora: consulta y comenta, sin ejecutar el flujo. | reg: Revisor técnico · tar: Experto · jor: Empleado técnico |
| **Observador** | I (Informed) | Solo ve: un ejecutivo, un mandante o un externo con acceso de consulta. No ejecuta ni aprueba. | reg: Visita, Mandante · tar: Seguimiento · jor: — (Asistencia no tiene observadores) |

## Coordinador acotado

Solo un **Coordinador** cuya membresía tiene `contratista` queda **acotado a ese contratista** (es el «administrador de contratista» de Registros). Los demás roles con contratista (Ejecutor, Observador…) **no se acotan**: conservan sus capacidades normales. El Coordinador acotado conserva las de gestión, pero **no recibe por rol las de ámbito empresa**: gestionar miembros y roles, marca, contratistas, crear/editar proyectos (`proyectos.manage`), la configuración de cada módulo, el perfil de jornadas de cada persona, `reg.alcance.todo`, y en Asistencia y Tareas todo lo que abarca a la empresa entera (`jor.equipo.ver`, `jor.reportes.ver`, `jor.certificado.generar`, `msj.ver_todos_proyectos`, `tar.tickets.view_all`). En Registros ve solo lo de su contratista (`reg.alcance.contratista`); en Asistencia y Tareas las vistas no filtran por contratista, por eso esas capacidades quedan fuera.

Las capacidades de ámbito empresa se marcan al registrarlas con un tercer elemento: `'cuentas.usuarios.manage': ('Gestionar miembros', {R.COORDINADOR}, {'empresa': True})`. Una excepción por persona (`UsuarioPermiso`) puede devolvérselas a un Coordinador acotado.

## Superusuario y administradores de sistema

No forman parte de la RACI: se definen en **Plataforma → Administradores** (`/panel/administradores/`), solo el superusuario.

- **Superusuario** (`User.is_superuser`): administra toda la plataforma, todas las empresas y a los demás administradores; puede bloquear, eliminar y restaurar cuentas.
- **Administrador de sistema** (`User.empresas_administradas`): se le asignan una o varias empresas. En ellas entra aunque no sea miembro y tiene las capacidades de **ámbito empresa** (miembros, cargos, marca, contratistas, proyectos, y las de Asistencia/Tareas/Mensajería que abarcan a la empresa entera). Las capacidades de cada módulo solo las tiene si además es miembro con un cargo. No ve Plataforma ni puede bloquear, eliminar o restaurar cuentas.

Si el administrador además es miembro, suma ambas cosas. Las excepciones por persona (`UsuarioPermiso`) se aplican al final y solo sobre la membresía.

## Capacidades por defecto

`✔` = el rol la tiene por defecto. La matriz se edita por empresa; en la BD solo se guardan las diferencias.

| Capacidad | Coord. | Ejecutor | Espec. | Observ. |
|---|:-:|:-:|:-:|:-:|
| `proyectos.view` | ✔ | ✔ | ✔ | ✔ |
| `proyectos.manage` ¹ | ✔ | | | |
| `cuentas.usuarios.manage` · `cuentas.roles.manage` ¹ | ✔ | | | |
| `empresas.marca.manage` · `empresas.contratistas.manage` ¹ | ✔ | | | |
| **Registros** `reg.txtss.ver` · `reg.construccion.ver` · `reg.construccion_base.ver` | ✔ | ✔ | ✔ | ✔ |
| `reg.alcance.todo` ¹ | ✔ | | | ✔ |
| `reg.alcance.contratista` | ✔ | | | |
| `reg.cargar_datos` · `reg.concluir` | ✔ | ✔ | | |
| `reg.activar` · `reg.cambiar_responsable` · `reg.reabrir` ² · `reg.items_obra` | ✔ | | | |
| `reg.config.manage` (sin rol por defecto: solo superusuario) | | | | |
| **Tareas** `tar.tickets.create` · `edit_any` · `assign` · `close` · `unarchive` · `view_backlog` · `tar.etiquetas.manage` | ✔ | | | |
| `tar.tickets.move` | ✔ | ✔ | | |
| `tar.tickets.view_all` ¹ · `view_waiting` · `tar.chat.view_all` | ✔ | | | ✔ |
| `tar.tickets.board_by_ticket` · `tar.dashboard.view` | ✔ | | ✔ | ✔ |
| `tar.chat.write` | ✔ | ✔ | ✔ | |
| **Asistencia** `jor.fichar` · `jor.ausencias.solicitar` | ✔ | ✔ | ✔ | |
| `jor.equipo.ver` ¹ · `ausencias.gestionar` · `calendario.manage` · `reportes.ver` ¹ · `certificado.generar` ¹ · `etiquetas.manage` | ✔ | | | |
| `jor.stats.view` | ✔ | | | |
| `jor.perfiles.manage` · `jor.config.manage` ¹ · `jor.excepciones.gestionar` ¹ | ✔ | | | |
| **Mensajería** `msj.usar` | ✔ | ✔ | ✔ | ✔ |
| `msj.ver_todos_proyectos` ¹ | ✔ | | | |

¹ Capacidad de ámbito empresa: un Coordinador acotado a un contratista no la recibe por rol.

² En los tipos de registro con revisiones (hoy «Supervisión Campo»), `reg.cargar_datos` permite **crear** una revisión y `reg.reabrir` permite **elegir cuál es la vigente**. Un registro emitido no se reabre: se corrige con una revisión nueva.

## Decisiones y notas

- **Asistencia no tiene observadores.** Al importar desde skylog, todos los empleados (incluidos los de cargo PM o Supervisor) entran como Ejecutor y conservan su cargo en el perfil de jornadas; quien deba administrar y ver a todo el equipo se asciende a Coordinador a mano. El rol Observador no recibe ninguna capacidad `jor.*`.
- **Proyectos desde Asistencia.** La entrada «Proyectos» del menú de Asistencia abre la lista de Proyectos; ahí, quien tenga `jor.etiquetas.manage` **y** `proyectos.manage` (hoy solo el Coordinador con ámbito empresa) puede agregar al modelo los proyectos que los reportes mencionan.
- **Observador y Entrada.** Tampoco ve la columna Entrada de Tareas (tickets sin refinar) ni figura en la leyenda del tablero. Se puede habilitar en la matriz.
- **Planilla de pago:** el certificado incluye los perfiles activos de Coordinador, Especialista y Ejecutor. La cabeza de la empresa, si no va en planilla, se excluye desactivando su perfil en Asistencia.
- **Sin comparar nombres de rol en el código:** se razona siempre por capacidades (`cuentas.capacidades`) o, en pocos casos, por rol base (`RolBase`).

## Migración desde los seis roles PMBOK anteriores

| Antes | Ahora |
|---|---|
| PMO · Director de Proyecto | Coordinador |
| Patrocinador · Interesado | Observador |
| Especialista · Miembro | igual (Miembro pasa a llamarse Ejecutor; el valor interno sigue siendo `MIEMBRO`, ver `cuentas/0004_rol_miembro_ejecutor.py`) |

La migración `cuentas/0003_roles_raci.py` convierte los roles de cada empresa: fusiona los roles sembrados («PMO» y «Director de Proyecto» en «Coordinador»; «Patrocinador» e «Interesado» en «Observador») moviendo sus membresías y accesos por módulo al rol que se conserva. Los roles con nombre propio (ITO, Supervisor…) se conservan y solo cambian de rol base. Las diferencias de permisos del rol que se conserva se mantienen: conviene revisarlas.

**Mensajería (módulo `msj`).** Se activa por empresa y, como los demás módulos, se puede deshabilitar a una persona (`AccesoModulo`): sin `msj.usar` no hay chat. Quien lo tiene lee y escribe en *General* y en sus mensajes directos; el canal de un *proyecto* lo ve su equipo y quien tenga `msj.ver_todos_proyectos` (Coordinador ¹). Los directos son privados.
