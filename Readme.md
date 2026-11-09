# Django Skeleton

Skeleton para desplegar Django en un VPS con nginx como reverse proxy. Incluye soporte opcional para n8n (automatización) y n8n-MCP (integración con Claude Code / clientes MCP).

## Stack

| Componente | Tecnología |
|---|---|
| Framework | Django 6.1+ (Python 3.14) |
| Servidor ASGI | Gunicorn + worker `uvicorn-worker` (HTTP y WebSocket; `GUNICORN_WORKERS`, default 3), contenedor no-root |
| Base de datos | PostgreSQL 17 (contenedor o host) |
| Cache / Sesiones | Redis 8 (sesiones `cached_db`) |
| CSS | Tailwind CSS v4.3 + DaisyUI v5.7 |
| Archivos estáticos | Whitenoise (`CompressedManifestStaticFilesStorage`) + nginx (`gzip_static`) |
| Seguridad | django-axes (handler de DB, gestionable desde el admin), django-csp, HSTS |
| Hot reload (dev) | django-browser-reload |
| Automatización (opcional) | n8n |
| MCP Server (opcional) | n8n-MCP |
| Reverse proxy | Nginx (host) + Let's Encrypt |

---

## Quick Start (VPS)

```bash
# 1. Clonar el proyecto
git clone <repo> miproyecto && cd miproyecto

# 2. Configurar — genera .env de forma interactiva
make setup

# 3. Configurar nginx (SOLO la primera vez — no volver a ejecutar tras certbot)
make nginx

# 4. Obtener certificado SSL
sudo certbot --nginx -d tudominio.com
# Si n8n está habilitado, agregar también: -d n8n.tudominio.com

# 5. Desplegar
make deploy
```

Para deploys posteriores solo se necesita `make deploy` (ver sección *Deploy*). **Nunca volver a ejecutar `make nginx`** después de que certbot configuró el SSL.

---

## Desarrollo local

### Opción A — Mínimo (Redis y PostgreSQL en Docker)

`make setup` en modo desarrollo siempre configura PostgreSQL (contenedor) y `make dev` levanta `dev-up`, así que **requiere Docker**. Sin `POSTGRES_DB` en `.env` Django cae a SQLite (`SQLITE_PATH`), útil solo para scripts puntuales.

```bash
make install           # instala dependencias Python + Tailwind
make setup             # genera .env
make dev               # dev-up + migrate + tailwind watcher + runserver
```

### Opción B — Completo (PostgreSQL + Redis en Docker)

```bash
make install           # instala dependencias Python + Tailwind
make setup             # genera .env con PostgreSQL
make dev               # levanta Redis + PostgreSQL (+ n8n/MCP) y arranca Django + Tailwind
make dev-check         # verifica que todo esté corriendo
make dev-down          # detiene los contenedores de desarrollo
```

En ambos casos Django corre nativo en el host (no en Docker). Redis en Docker es accesible en `localhost:6379`.

### Hot reload

`make dev` lanza Tailwind en background y Django con `django-browser-reload`:

- **Python y templates**: Django recarga automáticamente → el browser se refresca solo
- **CSS**: Tailwind recompila el CSS → refrescar el browser manualmente

### Dos terminales (alternativa a `make dev`)

```bash
# Terminal 1 — watcher CSS
python manage.py tailwind start

# Terminal 2 — servidor Django
python manage.py runserver
```

### Comportamiento automático según `.env`

| Variable | Ausente | Presente |
|---|---|---|
| `POSTGRES_DB` | SQLite | PostgreSQL |
| `N8N_DOMAIN` | n8n deshabilitado | n8n en contenedor |
| `REDIS_URL` | con `DEBUG=True`: caché y Channels en memoria (sin Redis); con `DEBUG=False`: `redis://localhost:6379/0` | valor configurado |

---

## PostgreSQL: contenedor vs host

Controla el comportamiento con `POSTGRES_MODE` en `.env`:

### Contenedor Docker (default)
```env
POSTGRES_MODE=container
POSTGRES_HOST=postgres
```
PostgreSQL corre en Docker, incluido en `docker-compose.yml` con el profile `postgres`.

### PostgreSQL del servidor host
```env
POSTGRES_MODE=host
POSTGRES_HOST=host.docker.internal
```
Los contenedores se conectan al PostgreSQL instalado en el VPS via `host.docker.internal`. El contenedor postgres **no se inicia**.

**Requisitos para modo host:**
1. `listen_addresses` en `postgresql.conf` debe incluir la IP del bridge Docker (o `*`)
2. `pg_hba.conf` debe aceptar conexiones desde la red Docker (`172.16.0.0/12`):
   ```
   host  all  all  172.16.0.0/12  md5
   ```
3. Crear manualmente las bases de datos del proyecto y `n8n`

---

## Servicios opcionales

Los servicios opcionales se activan via Docker Compose profiles. `deploy.sh` los gestiona automáticamente según el `.env`.

### n8n

Habilitar en `.env`:
```env
N8N_DOMAIN=n8n.tudominio.com
N8N_ENCRYPTION_KEY=clave-generada-por-setup
```

- Subdominio propio con imagen custom (Python 3.12 integrado para Code nodes)
- Comparte PostgreSQL con base de datos separada (`n8n`)
- Workflows en `n8n/workflows/` se importan automáticamente al arrancar
- Exportar workflows del dev: `make n8n-export`
- **`N8N_ENCRYPTION_KEY` debe mantenerse constante** — cambiarla invalida credenciales guardadas

### n8n-MCP

Requiere n8n habilitado. Habilitar en `.env`:
```env
N8N_MCP_ENABLED=true
N8N_API_KEY=<generar en n8n: Settings > API>
N8N_MCP_AUTH_TOKEN=token-generado-por-setup
```

Expone un servidor MCP sobre HTTP en `https://n8n.tudominio.com/mcp`. Permite integrar n8n con Claude Code u otros clientes MCP.

---

## Puertos

Los servicios usan puertos consecutivos desde `APP_PORT`. Para cambiarlos, ajusta solo `APP_PORT` en `.env` (los demás se calculan en `setup.sh`).

| Servicio | Puerto default | Variable |
|---|---|---|
| Django | 8000 | `APP_PORT` |
| n8n | 8001 | `N8N_PORT` |
| n8n-MCP | 8002 | `N8N_MCP_PORT` |
| Redis | interno | — |
| PostgreSQL | 5432 | `POSTGRES_HOST_PORT` (solo dev) |

En producción todos los puertos bindean a `127.0.0.1` — solo accesibles via nginx. Redis no expone puerto al exterior en producción (en desarrollo se publica en `127.0.0.1:6379`).

---

## Actualizar n8n

n8n no tiene actualización desde la UI web. El proceso es:

```bash
make n8n-update   # rebuild imagen custom + restart contenedor
```

Esto reconstruye la imagen con la última versión de n8n, reinicia el contenedor y preserva todos los datos en `./volumes/n8n`. Para controlar la versión exacta, edita la imagen base en `docker/n8n.Dockerfile`.

---

## Tailwind + DaisyUI

Las versiones se gestionan en `theme/static_src/package.json` (devDependencies):

- **Tailwind CSS**: `^4.3.3`
- **DaisyUI**: `^5.7.50`

En **desarrollo**: `make install` → `npm install` instala los paquetes.

En **producción**: el Dockerfile usa `npm ci && npm run build` en una stage Node aislada. El CSS compilado y minificado se copia a la imagen Python final. **Los módulos npm no están en la imagen de producción.**

Para actualizar versiones: edita `package.json`, corre `npm update` en `theme/static_src/` y regenera `package-lock.json`.

---

## Archivos estáticos

Whitenoise + nginx trabajando en conjunto:

1. `collectstatic` genera archivos con hashes en el nombre (`styles.abc123.css`) y versiones `.gz` pre-comprimidas
2. nginx intercepta `/static/` y sirve directamente desde `staticfiles/` con `gzip_static on` — usa los `.gz` sin comprimir on-the-fly
3. Cache `immutable` con 365 días es seguro porque los filenames cambian en cada deploy

---

## Redis

Redis es siempre activo en producción (con `DEBUG=True` y sin `REDIS_URL` se usan caché y Channels en memoria) y optimiza tres aspectos clave:

| Aspecto | Sin Redis | Con Redis |
|---|---|---|
| Cache | `LocMemCache` por worker (no compartido) | Cache compartido entre los 3 workers Gunicorn |
| Sesiones | Escrituras a PostgreSQL en cada request | Cache en memoria, sin tocar la DB |
| Channels (WebSocket) | `InMemoryChannelLayer` (un solo proceso) | `channels_redis`: mensajes entre workers y notificaciones en vivo |

---

## Variables de entorno

| Variable | Requerida | Descripción |
|---|---|---|
| `PROJECT_NAME` | Sí | Nombre usado en contenedores y nginx |
| `DOMAIN` | Sí | Dominio principal de Django |
| `SECRET_KEY` | Sí | Clave secreta de Django |
| `DEBUG` | No | `False` en prod (default) |
| `ALLOWED_HOSTS` | Sí | Dominios permitidos (CSV) |
| `CSRF_TRUSTED_ORIGINS` | Sí | Orígenes confiables CSRF (CSV) |
| `ADMIN_URL` | No | URL del admin (default: `admin/`) |
| `APP_PORT` | No | Puerto Django (default: `8000`) |
| `POSTGRES_MODE` | No | `container` o `host` (default: `container`) |
| `POSTGRES_DB` | Sí | Nombre de la base de datos |
| `POSTGRES_USER` | Sí | Usuario PostgreSQL |
| `POSTGRES_PASSWORD` | Sí | Contraseña PostgreSQL |
| `POSTGRES_HOST` | No | Host PostgreSQL (default: `postgres`) |
| `POSTGRES_PORT` | No | Puerto PostgreSQL (default: `5432`) |
| `REDIS_URL` | No | URL de Redis (default: `redis://localhost:6379/0`; en Docker lo fija `entrypoint.sh` a `redis://redis:6379/0`) |
| `N8N_DOMAIN` | No | Subdominio de n8n (activa el servicio) |
| `N8N_PORT` | No | Puerto externo n8n (default: `8001`) |
| `N8N_ENCRYPTION_KEY` | Si n8n | Clave de cifrado de n8n (**no cambiar**) |
| `INTERNAL_API_TOKEN` | No | Token de los endpoints internos para n8n/cron (cabecera `X-Internal-Token`); vacío = deshabilitados |
| `N8N_MCP_ENABLED` | No | `true` para habilitar n8n-MCP |
| `N8N_MCP_PORT` | No | Puerto externo MCP (default: `8002`) |
| `N8N_API_KEY` | Si MCP | API key de n8n para el servidor MCP |
| `N8N_MCP_AUTH_TOKEN` | Si MCP | Token de autenticación del MCP |
| `EMAIL_HOST` | No | SMTP host (activa email backend; vacío = backend de consola) |
| `EMAIL_PORT` · `EMAIL_USE_TLS` · `EMAIL_HOST_USER` · `EMAIL_HOST_PASSWORD` | No | Credenciales SMTP |
| `DEFAULT_FROM_EMAIL` · `ADMIN_EMAIL` | No | Remitente por defecto y correo del administrador |
| `SITE_URL` | No | URL pública sin barra final (enlaces absolutos en correos) |
| `GUNICORN_WORKERS` | No | Workers de Gunicorn (default: `3`) |
| `REDIS_MAXMEMORY` | No | Límite de memoria de Redis (default: `256mb`) |
| `POSTGRES_HOST_PORT` | No | Puerto de PostgreSQL publicado en el host (solo dev) |
| `SQLITE_PATH` | No | Ruta del SQLite si no hay `POSTGRES_DB` |
| `FOTO_MAX_SIZE` · `ATTACHMENT_MAX_SIZE` | No | Límites de subida en bytes (25 MB por foto, 20 MB por adjunto); nginx admite 30M por petición |
| `S3_URL_EXPIRE` | No | Segundos de validez de las URLs firmadas de archivos privados (default: `300`) |
| `DISK_ALERT_PERCENT` | No | % de disco a partir del cual el panel avisa (default: `85`) |
| `GOOGLE_MAPS_API_KEY` | No | Mapa estático del informe de Registros |
| `N8N_VERSION` · `N8N_MCP_VERSION` | No | Versión de las imágenes de n8n / n8n-MCP (default: `latest`) |
| `BACKUP_KEEP` | No | Copias a conservar en `scripts/backup.sh` (default: `10`) |

---

## Comandos

| Comando | Descripción |
|---|---|
| `make setup` | Wizard interactivo — genera `.env` |
| `make install` | Instala dependencias Python y Tailwind |
| `make dev-up` | Levanta servicios de desarrollo (Docker) |
| `make dev-down` | Detiene servicios de desarrollo |
| `make dev-logs` | Logs de servicios de desarrollo |
| `make dev-check` | Verifica estado del entorno de desarrollo |
| `make dev` | `dev-up` + migrate + tailwind start + runserver |
| `make sync-media` | Copia al bucket solo los archivos **públicos** de `media/` (no toca `media/privado/`) |
| `make media-cdn ARGS="--dry-run"` | Sube toda la media local (pública y privada) a su bucket; `--borrar-local --antiguedad 7d` libera disco |
| `make n8n-import` | Importa workflows y credenciales de n8n desde `n8n/` |
| `make tailwind` | Compila el CSS una vez (`npm run build`) |
| `make axes-reset` | Desbloquea todos los accesos bloqueados por axes |
| `make migrate` | Ejecuta migraciones |
| `make migrations` | Crea migraciones |
| `make superuser` | Crea superusuario |
| `make shell` | Django shell |
| `make collect` | collectstatic |
| `make db-shell` | Abre psql (PostgreSQL) o indica sqlite3 |
| `make db-reset` | Elimina SQLite y vuelve a migrar |
| `make n8n-export` | Exporta workflows de n8n dev a `n8n/workflows/` |
| `make n8n-update` | Actualiza n8n en producción (rebuild + restart) |
| `make check-ports` | Verifica disponibilidad de puertos |
| `make nginx` | Instala config nginx (**solo primera vez**) |
| `make deploy` | Despliega en VPS (git pull + verifica puertos + rebuild) |
| `make logs` | Logs de Django en producción |
| `make down` | Detiene contenedores de producción (todos los profiles) |
| `make backup` | Backup de PostgreSQL a `backups/*.sql.gz` (retención: 10) |
| `make restore FILE=...` | Restaura un backup (destructivo, pide confirmación) |
| `make rollback [TAG=sha]` | Vuelve a la imagen anterior de Django (no revierte migraciones) |
| `make ps` / `make restart` | Estado / reinicio de Django en producción |

---

## Estructura

```
├── core/                    # settings, urls, asgi, routing (WebSocket), interno (API para n8n/cron)
├── home/                    # Portada pública, healthz, comandos de siembra
├── cuentas/ empresas/       # Usuarios, roles/capacidades (ROLES.md), empresas, contratistas, tenancy
├── proyectos/ archivos/     # Proyecto común a los módulos; media/CDN/S3 (ex-app `cdn`)
├── notificaciones/ mje_mensajes/ panel/   # Notificaciones en vivo; mensajes; panel de la empresa y de la plataforma
├── reg_*/                   # Módulo Registros (base, construccion_base, txtss, construccion, fotos, actividades)
├── tar_*/                   # Módulo Tareas (tickets, adjuntos)
├── jor_*/                   # Módulo Asistencia (empleados, diario, actividades, reportes)
├── ROLES.md                 # Roles base RACI y matriz de capacidades
├── templates/               # Globales (base, shell, components/, 404, 500, robots.txt)
├── theme/                   # App Tailwind (static_src/ con npm build)
├── static/                  # Assets estáticos (img, js, vendor)
├── staticfiles/             # collectstatic output (generado)
├── media/                   # Uploads de usuarios (generado)
├── n8n/workflows/           # Workflows n8n versionados en git
├── volumes/                 # Datos persistentes de contenedores (gitignored)
│   └── n8n/                 # Datos de n8n (workflows, credenciales)
├── db/                      # Datos PostgreSQL en producción (gitignored)
├── docker/
│   ├── n8n.Dockerfile       # n8n con Python 3.12 (para Code nodes)
│   ├── n8n-export.sh        # Script de exportación de workflows
│   ├── n8n-import.sh        # Importa workflows y credenciales
│   └── init-db.sql          # Crea la base de datos n8n al iniciar postgres
├── Dockerfile               # Multi-stage: Node (CSS build) → Python (prod)
├── docker-compose.yml       # Producción: postgres* + redis + django + n8n* + mcp*
├── docker-compose.dev.yml   # Desarrollo: postgres* + redis + n8n* + mcp*
├── entrypoint.sh            # Espera PG + Redis, collectstatic, migrate, gunicorn
├── nginx.conf               # Template nginx Django
├── nginx-n8n.conf           # Template nginx n8n (con marcador {{MCP_BLOCK}})
├── nginx-n8n-mcp.conf       # Location block para n8n-MCP (SSE)
├── nginx-deploy.sh          # Genera e instala config nginx (solo primera vez)
├── deploy.sh                # Despliegue VPS (build, backup condicional, healthcheck, rollback)
├── scripts/                 # lib.sh, backup.sh, restore.sh, rollback.sh, traer_legacy_reg.sh
├── setup.sh                 # Wizard de configuración inicial
├── check-ports.sh           # Verifica disponibilidad de puertos
├── Makefile
├── .env.example             # Plantilla de variables de entorno
├── requirements.txt         # Dependencias Python de producción
└── requirements-dev.txt     # + daphne, browser-reload (desarrollo y CI)
```

`*` servicio opcional (Docker Compose profile)

---

## Deploy

`make deploy` (`deploy.sh`) despliega con downtime de segundos:

1. `git pull --ff-only` y re-ejecución del script actualizado.
2. Build de la imagen **mientras la versión actual sigue sirviendo**; se etiqueta con el SHA de git.
3. **Backup condicional**: solo si hay migraciones pendientes y la DB ya tiene datos. `BACKUP=always|never` lo fuerza u omite (`make deploy BACKUP=always`). Si el backup falla, el deploy se aborta sin tocar nada.
4. `docker compose up -d` recrea solo lo que cambió (sin `down`).
5. Espera el healthcheck (`/healthz`: DB + cache). Si falla y no se aplicaron migraciones → **rollback automático** a la imagen anterior; si se aplicaron, indica `make restore` / `make rollback`.
6. Conserva las 3 últimas imágenes de la app y registra `.deploy/previous`.

Backups periódicos independientes del deploy (cron diario, 03:00):

```cron
0 3 * * * cd /ruta/al/proyecto && bash scripts/backup.sh diario >/dev/null
```

`backup.sh` respalda **solo PostgreSQL**. La carpeta `media/` (incluida `media/privado/`) no está incluida: respáldala aparte (o muévela a un bucket con `make media-cdn`).

### Inicio de jornada verificado (sin agente de escritorio)

La jornada se marca **desde el celular personal** de cada persona, en tres capas (`jor_diario/verificacion.py`, `jor_empleados/passkeys.py`):

1. **Identidad:** el celular se vincula una vez con una passkey (WebAuthn, huella/PIN del teléfono; al servidor solo llega la clave pública). Un celular activo por persona; un administrador lo libera desde *Equipo → persona* si se pierde o se cambia.
2. **Presencia:** 3 lecturas de GPS contra la geocerca de la **Sede** (`lat`, `lon`, `radio_m`, `precision_max_m`; se cargan en *Ajustes → Sedes*). Se valida precisión, antigüedad de las lecturas, saltos imposibles y que el navegador sea móvil. La IP y el user-agent se guardan solo como auditoría.
3. **Excepción, no bloqueo:** si la presencia no valida, la persona indica un motivo y la jornada queda `excepción pendiente`; los coordinadores (`jor.excepciones.gestionar`) la aprueban o rechazan en *Equipo → Excepciones*. **Asistencia, estadísticas y certificado solo cuentan jornadas verificadas o aprobadas** (`Jornada.objects.computables()`). `Perfil.puede_excepcion` en falso rechaza esas marcaciones en vez de enviarlas a revisión.

Requisitos de despliegue: HTTPS (WebAuthn no funciona sin él, salvo `localhost`), el dominio estable (la passkey queda atada al dominio) y cargar las coordenadas de cada sede; **una sede sin coordenadas manda toda marcación a revisión**. Riesgo residual: quien esté dentro del radio puede marcar, y Android con ubicación simulada puede engañar al GPS; se mitiga con las comprobaciones anteriores y la bandeja de excepciones.

Tareas recurrentes de Asistencia (no hay nada que las programe por defecto; usa cron o un workflow de n8n):

```cron
# cierra las jornadas vencidas cada hora
0 * * * * cd /ruta/al/proyecto && docker compose exec -T django python manage.py cerrar_jornadas_vencidas >/dev/null
```

**Es obligatorio en producción:** nada lo programa automáticamente; sin esta línea en el `crontab` del VPS las jornadas abiertas nunca se cierran. El nombre del servicio (`django`) es el de `docker-compose.yml`.

**Backups:** `make backup` (y cada `make deploy`) genera el volcado SQL y, aparte, `backups/<fecha>-<etiqueta>-media.tar.gz` con `media/`. Para programarlo: `0 3 * * * cd /ruta/al/proyecto && bash scripts/backup.sh diario >/dev/null`.

Con n8n, los mismos trabajos se disparan por los endpoints internos (`INTERNAL_API_TOKEN`, ver «Plataforma multi-empresa y módulos»).

**Migrar desde la antigua app `cdn`:** la migración `archivos/0002` copia su configuración. Una sola vez, en una base que ya tuvo `cdn`, elimina sus restos:

```bash
python manage.py shell -c "from django.db import connection as c; cur=c.cursor(); cur.execute(\"DELETE FROM django_migrations WHERE app='cdn'\")"
python manage.py remove_stale_contenttypes --noinput
```

Las versiones de n8n / n8n-MCP son `latest` por defecto; fíjalas con `N8N_VERSION` / `N8N_MCP_VERSION` en `.env`. PostgreSQL se mantiene en 17 (la 18 cambia el layout de datos; migrar requiere dump/restore: `make backup` → cambiar imagen → `make restore`).

---

## Media y CDN (configurable desde el admin)

Por defecto los uploads se guardan en el propio VPS (`media/`, servidos por nginx en `/media/`). Desde el admin, **Almacenamiento de media / CDN → Configuración**, se puede cambiar sin tocar código ni reiniciar:

| Modo | Qué hace |
|---|---|
| **Este servidor** (defecto) | Archivos en el VPS. Con *URL de la CDN* definida, las URLs públicas pasan por una CDN *pull* que apunta al sitio (ej. `https://cdn.midominio.com` → se sirve `/media/…`). |
| **S3-compatible** | Archivos en un bucket (AWS S3, Cloudflare R2, DigitalOcean Spaces, MinIO…). Con *URL de la CDN*, las URLs usan el dominio personalizado del bucket. |

- Los cambios aplican de inmediato (config cacheada en Redis, invalidada al guardar). Al guardar en modo S3 se prueba la conexión y se avisa si falla.
- El origen de la CDN/bucket se agrega solo al CSP (`img-src`, `media-src`).
- Los archivos ya subidos **no se mueven solos** al cambiar de modo: `make media-cdn` sube lo que está en `media/` (público y privado, cada uno a su bucket); `make sync-media` copia solo lo público. Ninguno borra salvo con `--borrar-local`.
- En plantillas/código usa siempre `campo.url` (no `{{ MEDIA_URL }}`) para que respete la configuración.
- Las credenciales S3 se guardan en la base de datos: usa una clave limitada a ese bucket.

---

## Notas de seguridad

- **Admin URL aleatorio** — generado por `setup.sh` (no se publica en `robots.txt`)
- **Brute-force protection** — django-axes bloquea tras 5 intentos fallidos (1h de cooldown). Los intentos se guardan en la DB: en el admin, **Axes → Access attempts** (filtro *Locked Out*); para desbloquear a alguien, selecciona su registro y bórralo. Si el bloqueado es el propio admin: `make axes-reset`. En producción la IP real se toma de `X-Real-IP` (nginx)
- **CSP headers** — política estricta vía django-csp, relajada en DEBUG para browser-reload
- **HSTS** — habilitado en producción (1 año, incluye subdominios)
- **Static files** — hashes en filenames + cache `immutable` 365 días, seguros porque cambian en cada deploy

---

## Checklist de personalización

- [ ] Cambiar favicon: reemplazar `static/img/favicon.svg`
- [ ] Definir `ADMIN_EMAIL` en `.env` para recibir errores 500 por email (requiere SMTP)
- [ ] Ajustar zona horaria y locale → `TIME_ZONE`, `LANGUAGE_CODE` en `settings.py`
- [ ] Personalizar tema DaisyUI en `theme/static_src/src/styles.css`
- [ ] Al agregar nuevas apps: `INSTALLED_APPS` + `@source "../../../<app>"` en `styles.css`

---

## Arquitectura y convenciones

`core/settings.py` es único; el comportamiento cambia por variables de entorno:

- Sin `POSTGRES_DB` → SQLite · con `POSTGRES_DB` → PostgreSQL.
- `POSTGRES_MODE=host` → los contenedores usan `host.docker.internal`.
- Sin `EMAIL_HOST` → emails por consola · con `EMAIL_HOST` → SMTP.
- `DEBUG=True` → browser-reload y Tailwind activos · `DEBUG=False` → HSTS, CSP estricto e IP real de axes vía `X-Real-IP`.

Reglas a respetar al extender el proyecto:

- **Apps nuevas:** añadir a `INSTALLED_APPS` y `@source "../../../<app>"` en `theme/static_src/src/styles.css`.
- **Media:** usar siempre `campo.url`; la app `archivos` decide si es disco local o S3/CDN (`MediaCspMiddleware` va después de `CSPMiddleware`).
- **CSP:** formato django-csp 4 (`CONTENT_SECURITY_POLICY`).
- **Deploy:** imagen etiquetada con el SHA de git (`${PROJECT_NAME}_app:<sha>`), healthcheck en `/healthz`, contenedor no-root (UID 1000: `staticfiles/` y `media/` deben ser de ese usuario). PostgreSQL fijo en 17.
- **nginx:** `make nginx` solo una vez; certbot modifica el archivo y `deploy.sh` nunca lo toca.
- **n8n:** `N8N_ENCRYPTION_KEY` no se cambia nunca.
- **Windows:** en `settings.py`, dentro de `if DEBUG:`, `NPM_BIN_PATH = r'C:\Program Files\nodejs\npm.cmd'`.

---

## Plataforma multi-empresa y módulos

skygroup es una plataforma para varias **empresas** (tenants) con **módulos** que se ven como aplicaciones (selector de apps en la cabecera y barra lateral propia por módulo).

**Vocabulario (no mezclar):** *Empresa* = el cliente de la plataforma (URL `/<slug>/`). Dentro de cada empresa, las organizaciones externas son *Contratistas* (`empresas.Contratista`), nunca «empresa». El *Proyecto* (`proyectos.Proyecto`) es único por empresa y cada empresa puede renombrarlo (p. ej. «Sitios»): usa siempre `{{ termino_proyecto }}` / `{{ termino_proyectos }}` en las plantillas.

| Grupo | Apps |
|---|---|
| Comunes (sin prefijo) | `cuentas` (usuario por correo, roles RACI, membresías, capacidades) · `empresas` (marca, tenancy, contratistas) · `proyectos` · `archivos` (storage híbrido local/S3, configuración de CDN/S3 en el admin, `media_a_cdn`) · `notificaciones` (campana + WebSocket) · `panel` (menú por aplicaciones, configuración y panel global) |
| Tareas `tar_` | `tar_tickets` (tablero kanban, subtickets, aprobación, chat, dashboard, tiempo real) · `tar_adjuntos` |
| Registros `reg_` | `reg_base` (alcance de datos, capacidades, estado, tipos de registro activos por empresa, revisiones) · `reg_construccion_base` («Supervisión Campo»: reporte de visita de supervisión con hallazgos, plantilla estándar para cualquier empresa) · `reg_txtss` · `reg_construccion` («Construcción») · `reg_fotos` (fotos con EXIF y miniaturas) · `reg_actividades` (pasos y widgets configurables por empresa) |
| Asistencia `jor_` | `jor_empleados` (perfil por membresía, configuración) · `jor_diario` (jornadas, reporte diario, equipo, ausencias, calendario, cierre automático con `cerrar_jornadas_vencidas`) · `jor_actividades` (clasificación de las actividades del reporte, categorías y etiquetas por empresa) · `jor_reportes` (asistencia y estadísticas, con exportación a Excel, y certificado de pago sobre la plantilla .xlsx que sube cada empresa) · `jor_visitas` (observadores: personas con rol Observador y bitácora de sus ingresos) |
| Mensajería `msj` | `mje_mensajes` (chat en tiempo real: canal General, un canal por proyecto y mensajes directos, con @menciones, imágenes adjuntas y no leídos). Se activa por empresa (`Empresa.modulos`) y por persona (`AccesoModulo`); es una **ventana flotante** disponible en todas las pantallas (icono de la barra superior o tarjeta del lanzador): no tiene páginas propias ni cambia de página; `mensajes/?c=<id>` solo redirige al inicio con la ventana abierta (destino de las notificaciones). WebSocket en `ws/empresa/<slug>/mensajes/`. Los avisos automáticos del sistema van a la campana, no al chat |
| Análisis de Precios Unitarios con IA `apu` | Módulo anunciado como «Próximamente»: está registrado (activable por empresa y por persona, con tarjeta en el lanzador) pero aún no tiene apps ni pantallas. |

**Convenciones**
- **Permisos:** un solo sistema de *capacidades* (`cuentas.capacidades`). Cada app las declara con `registrar()` en `ready()`; en vistas se usa `@requiere_capacidad(...)` o el decorador del módulo (`acceso_tareas(...)`). Nunca compares nombres de rol: cada empresa define sus roles (`RolEmpresa`) sobre 4 roles base RACI (Coordinador, Ejecutor, Especialista, Observador; el Administrador de la plataforma es el superusuario) y edita la matriz en *Inicio → Roles y permisos*. El menú «Inicio» de cada empresa reúne su información (proyectos, usuarios, contratistas, roles y marca); «Plataforma» es solo del superusuario y se abre desde el menú de usuario. Ver [ROLES.md](ROLES.md).
- **Inicio de sesión con Nextcloud:** opcional, OAuth2 (`cuentas/nextcloud.py`). El superusuario lo activa en *Plataforma → Nextcloud* (URL, Client ID/secret y empresas donde se muestra el botón; el login sin empresa lo muestra siempre). En Nextcloud (Ajustes → Seguridad → Cliente OAuth 2.0) se registra la URI de redirección que muestra esa pantalla (`<SITE_URL>/acceso/nextcloud/callback/`, sin slug de empresa). Solo entra a cuentas ya vinculadas por `User.nextcloud_uid`; nunca crea usuarios ni membresías y **no vincula por correo** (el correo de Nextcloud lo edita cada persona sin verificarlo). El vínculo lo hace la persona con su sesión iniciada (*menú del usuario → Vincular Nextcloud*, o *Desvincular*) o un administrador fijando el uid a mano en el admin de Django. Quien entra por Nextcloud sin vínculo recibe un aviso con esos pasos.
- **Menú:** cada módulo registra sus entradas con `panel.menu.registrar_item(...)` (con `condicion=fn(request)` para mostrarlas solo si aplica, p. ej. si la empresa tiene activo un tipo de registro).
- **Tipos de registro (módulo Registros):** los tipos existen en código (`reg_base.tipos.registrar_tipo`) pero cada empresa activa solo los que usa (*Registros → Configuración → Tipos de registro*, solo superusuario). Un tipo desactivado se oculta (menú y rutas dan 404) sin borrar datos. «Supervisión Campo» (`construccion-base`) se activa sola en toda empresa nueva y siembra su plantilla de pasos estándar, que la empresa edita (`reg_construccion_base.estandar.sembrar_estandar`; «restaurar» la vuelve al estándar). El reporte tiene 6 pasos (datos de la visita, actividades ejecutadas, recursos presentes, hallazgos, verificación de observaciones previas, instrucciones y acuerdos) y cada widget de un paso es un botón de la línea de tiempo. Un botón de fotos puede exigir metadatos con `exigir_metadatos: true` en su configuración: la subida se rechaza si la foto no trae fecha y coordenadas EXIF (las reenviadas por WhatsApp las pierden) y la galería fuerza la cámara en el celular (`capture`); el estándar lo activa en las imágenes de actividades (mínimo 4). Un tipo puede admitir **revisiones** (`RevisionesMixin` + `con_revisiones=True`): cada revisión se crea copiando la anterior con un comentario obligatorio, las anteriores se conservan y se elige la vigente.
- **Aislamiento:** todo dato operativo cuelga de `empresa` y toda consulta se acota a `request.empresa` (un id de otra empresa debe dar 404).
- **Archivos privados:** `storages['privado']`, ruta `<empresa_id>/<módulo>/…`. Un módulo con autorización propia llama `archivos.registro.proteger_modulo('<código>')`. Nunca expongas el `.url` de un archivo privado: sírvelo desde una vista que valide el acceso. En producción los privados deben ir en un bucket privado (configuración de `archivos`).
- **Endpoints internos (n8n/cron):** protegidos con `X-Internal-Token` = `INTERNAL_API_TOKEN` (`core/interno.py`; sin token configurado responden 404). Asistencia: `POST /api/jor/interno/cerrar-vencidas/`, `GET /api/jor/interno/actividades/pendientes/?empresa=<slug>` y `POST /api/jor/interno/actividades/clasificar/` (clasificación con LLM de lo que las palabras clave dejaron en «otros»), y `POST /api/mensajes/interno/cerrar-dia/` (el de `/api/jor/interno/mensajes/…` sigue vivo; ya no hace nada —el chat no tiene confirmación— y existe solo para no romper los cron/n8n ya configurados).
- **Tiempo real:** Channels. Rutas WebSocket `ws/empresa/<slug>/<módulo>/` registradas en `core/routing.py`; los avisos salen tras el `commit` (`tar_tickets/realtime.py`). Producción: `gunicorn core.asgi -k uvicorn.workers.UvicornWorker`; en desarrollo, daphne reemplaza `runserver` (solo con `DEBUG`).
- **CSP estricto:** sin `<script>` ni `style=` inline; el JS va en `static/js/` y los colores por empresa se sirven en `/<slug>/marca/tema.css`.
- **Tests:** `DEBUG=True python manage.py test` (los de WebSocket usan `TransactionTestCase`). Los tests de permisos usan un módulo de prueba (`tst`) para no pisar las capacidades reales.
- **Importar Registros desde reg.tekon-rl.cl:** `scripts/traer_legacy_reg.sh` (solo lee del servidor: `pg_dump` + `rsync` del media; variables `REG_SSH`, `REG_PORT`, `REG_DB_CONTAINER`, `REG_MEDIA_REMOTO`) deja JSONL en `backups/legacy/reg/` y fotos/mapas en `backups/legacy/reg_media/`. Luego `manage.py importar_reg <slug> [--limpiar] [--sin-archivos] [--dry-run]`: contratistas, usuarios (con su hash y una membresía según `user_type`), sitios → proyectos, pasos/widgets/plantillas (incluida la tabla de avance), registros TX/TSS y Construcción, datos de pasos (planos → `{widget: {…}}`), fotos y mapas. Es idempotente (`legacy_source='reg'` + `legacy_id`); `--limpiar` borra antes los datos de ejemplo de la empresa. Si dos pasos del original comparten nombre con widgets distintos, el segundo recibe el sufijo de su tipo (`sitio-torre`).
- **Dev con otra base:** `SQLITE_PATH=/ruta/otra.sqlite3` (cambiar `AUTH_USER_MODEL` obliga a recrear un `db.sqlite3` antiguo).

## Producto

**Para quién:** desarrolladores que conocen Python, Django, Docker y la línea de comandos, y quieren desplegar Django en un VPS con las decisiones de infraestructura ya tomadas, con criterio y no al azar.

**Objetivo:** un starter kit listo para producción (Tailwind v4 + DaisyUI v5, PostgreSQL/Redis en Docker Compose, Gunicorn tras nginx, n8n opcional) que resuelva el boilerplate (deploy, settings, estáticos, cabeceras de seguridad). Éxito = de `git clone` a un deploy en producción en menos de 30 minutos.

**Personalidad:** moderno, elegante, con opinión. Tono seguro y directo, como buena documentación escrita por quien usa la herramienta.

**Qué evitar:** plantillas Bootstrap genéricas, landing pages de SaaS infladas (testimonios, precios, CTAs ruidosos) y proyectos abandonados (README débil, estilos inconsistentes).

**Principios:** (1) cada píxel se gana su lugar, sin decoración; (2) valores por defecto con opinión y fáciles de sobrescribir; (3) el modo oscuro es de primera clase; (4) densidad sobre espaciosidad; (5) predecible antes que ingenioso. Accesibilidad: WCAG AA en ambos temas, animaciones respetan `prefers-reduced-motion`, idioma principal español (`lang="es"`).

---

## Sistema de diseño

**Idea rectora: "The Confident Default".** Una sola familia tipográfica, un solo acento y superficies planas. Las definiciones reales viven en `theme/static_src/src/styles.css` (temas DaisyUI `light` y `dark`).

### Color

| Rol | Light | Dark | Uso |
|---|---|---|---|
| Azul sistema (primario) | `#007AFF` | `#0A84FF` | Acciones primarias, selección activa, focus. ≤10% de la pantalla |
| Info (neutro) | `#4F5D6E` | `#9FB0C4` | Información; neutro para no competir con la marca |
| Superficie (`base-100`) | `#ffffff` | `#2b2c31` | Tarjetas, inputs, paneles |
| Fondo (`base-200`) | `#f2f2f7` | `#1f2024` | Shell de página, sidebar |
| Borde (`base-300`) | `#e5e5ea` | `#43444b` | Divisores y bordes en reposo |
| Texto | `#000000` / `#45484d` / `#6b7280` | `#e8e8ed` / `#8e8e93` | Principal / secundario / terciario (nunca para cuerpo) |
| Éxito · Aviso · Error | `#10b981` · `#f59e0b` · `#ea580c` | `#34d399` · `#fbbf24` · `#fb923c` | Estados semánticos (texto del aviso en oscuro: `#000`) |

El color es semántico, no estético: si no comunica acción, estado o severidad, no va en pantalla.

### Tipografía

Una sola pila `-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter Variable', 'Helvetica Neue', system-ui, sans-serif` (Inter Variable, vía `@fontsource-variable/inter`, sustituye a SF Pro fuera de dispositivos Apple) y `ui-monospace, Menlo, Monaco, 'Cascadia Code'` para código.

| Nivel | Peso / tamaño | Uso |
|---|---|---|
| Display | 700 · 1.875rem · lh 1.2 | Título de página (uno por vista), `text-wrap: balance` |
| Title | 600 · 1.25rem · lh 1.3 | Secciones y títulos de tarjeta |
| Body | 400 · 1rem · lh 1.5 | Prosa, máx. 65–75ch |
| Label | 500 · 0.875rem · lh 1.4 | Etiquetas, botones, navegación |
| Mono | 400 · 0.875rem · lh 1.6 | Comandos, variables de entorno, rutas |

Ningún texto de UI por debajo de 13px.

### Elevación y componentes

- **Plano por defecto:** la profundidad se logra con capas tonales (`base-100/200/300`), no con sombras. Solo la UI flotante (modales, dropdowns, tooltips, toasts) puede llevar sombra.
- **Radios:** 8px en botones e inputs, 16px en tarjetas, 4px en código inline.
- **Botón primario:** fondo azul primario, texto blanco, padding 10×20, alto mínimo 40px; hover más oscuro, sin movimiento ni escala; focus `outline: 2px solid #007AFF; outline-offset: 2px`. Variantes *ghost* y *base* para acciones secundarias/terciarias. Deshabilitado: 40% de opacidad.
- **Inputs:** contorno de 1px `#cccccc`, alto mínimo 48px, focus con borde azul primario y halo suave, error con borde `#ea580c`.
- **Tarjetas:** `bg-base-100` sobre `bg-base-200`, sin sombra, padding 24px (16px en variantes compactas).
- **Botones de acción en tablas (estándar):** las acciones de fila son **solo icono, con color y sin texto**: `btn btn-ghost btn-square btn-sm` + `text-<color> hover:bg-<color>/10`, con `title` y `aria-label` (el texto va ahí, para tooltip y lectores de pantalla). Icono `size-5` vía `{% include "components/icon.html" with name="..." cls="size-5" %}` (SVG local, el CSP no permite fuentes). Iconos y colores fijos: Editar → `pencil` `text-primary-text`; Ver como → `eye` `text-info`; Permisos → `shield` `text-success`; Eliminar/Quitar → `trash` `text-error`; PDF → `pdf` `text-red-600`. Los botones fuera de tablas (Nuevo, Guardar, cabeceras) siguen siendo **icono + texto** (`plus` para Nuevo). Una acción nueva obliga a añadir su icono a `templates/components/icon.html` y a esta lista.
- **Navegación:** barra superior de 56px con borde inferior, nunca con sombra; en móvil, patrón `drawer` de DaisyUI.
- **Bloques de código:** `bg-base-200`, mono 0.875rem, padding 16px, radio 8px.

### Hacer y no hacer

**Hacer:** probar contraste en ambos temas (≥4.5:1), definir todos los estados (hover, focus, active, disabled), usar monoespaciada para todo lo que se copia, y preferir estados de carga tipo *skeleton*.

**No hacer:** franjas de color de más de 1px en un borde lateral de tarjetas/alertas, degradados, glassmorphism decorativo, rejillas de tarjetas idénticas icono+título+texto, eyebrows en mayúsculas en cada sección, numeración 01/02/03 decorativa, ni modales como primera solución para flujos secundarios.
