# ── Configuración inicial ──────────────────────────────────────────────────────
setup:
	bash setup.sh

# ── Docker de desarrollo (Redis + PostgreSQL + n8n opcionales) ─────────────────
CURRENT_UID := $(shell id -u)
CURRENT_GID := $(shell id -g)

dev-up:
	@[ -f .env ] || { echo "Error: .env no encontrado. Ejecuta 'make setup' primero."; exit 1; }
	@command -v docker >/dev/null 2>&1 || { echo "Error: Docker no encontrado (necesario para PostgreSQL y Redis)."; exit 1; }
	@set -a && . ./.env && set +a; \
	PROFILES=""; \
	[ -n "$${POSTGRES_DB}" ] && PROFILES="--profile postgres"; \
	[ -n "$${N8N_DOMAIN}" ] && { PROFILES="$$PROFILES --profile n8n"; mkdir -p volumes/n8n; }; \
	[ "$${N8N_MCP_ENABLED}" = "true" ] && [ -n "$${N8N_DOMAIN}" ] && PROFILES="$$PROFILES --profile n8n-mcp"; \
	UID=$(CURRENT_UID) GID=$(CURRENT_GID) docker compose -f docker-compose.dev.yml $$PROFILES up -d --wait

dev-down:
	docker compose -f docker-compose.dev.yml down

dev-logs:
	docker compose -f docker-compose.dev.yml logs -f

dev-check:
	@echo "Verificando entorno de desarrollo..."
	@[ -f .env ] && echo "  ✓ .env existe" || echo "  ✗ .env no encontrado — ejecuta: make setup"
	@command -v python >/dev/null 2>&1 && echo "  ✓ Python disponible" || echo "  ✗ Python no encontrado"
	@command -v docker >/dev/null 2>&1 && echo "  ✓ Docker disponible" || echo "  ✗ Docker no encontrado"
	@docker compose -f docker-compose.dev.yml ps 2>/dev/null | grep -q "Up" \
		&& echo "  ✓ Contenedores activos" \
		|| echo "  ✗ Contenedores detenidos — ejecuta: make dev-up"
	@python -c "import redis; r=redis.from_url('redis://localhost:6379/0'); r.ping()" 2>/dev/null \
		&& echo "  ✓ Redis accesible en localhost:6379" \
		|| { \
			python -c "import redis" 2>/dev/null \
				&& echo "  ✗ Redis no accesible — ¿está make dev-up corriendo?" \
				|| echo "  ✗ Redis no accesible — paquete 'redis' no instalado (ejecuta: make install)"; \
		}

# ── n8n ───────────────────────────────────────────────────────────────────────
n8n-export:
	bash docker/n8n-export.sh

n8n-import:
	bash docker/n8n-import.sh

# Actualizar n8n: pull nueva imagen + restart del contenedor
# Los datos (workflows, credenciales) se preservan en el volumen ./volumes/n8n
n8n-update:
	@[ -f .env ] || { echo "Error: .env no encontrado."; exit 1; }
	@set -a && . ./.env && set +a; \
	[ -n "$${N8N_DOMAIN}" ] || { echo "Error: N8N_DOMAIN no definido en .env"; exit 1; }; \
	echo "▶ Descargando nueva imagen de n8n..."; \
	docker build --pull --build-arg N8N_VERSION=$${N8N_VERSION:-latest} -t $${PROJECT_NAME}_n8n:latest -f docker/n8n.Dockerfile .; \
	echo "▶ Reiniciando contenedor n8n..."; \
	docker compose --profile n8n up -d --no-deps n8n; \
	echo "✓ n8n actualizado."

# ── Django local ──────────────────────────────────────────────────────────────
install:
	pip install -r requirements-dev.txt
	python manage.py tailwind install
	@echo ""
	@[ -f .env ] || echo "  Siguiente paso: ejecuta 'make setup' para generar el .env"

# Levanta PostgreSQL + Redis (+ n8n) en Docker, espera a que estén healthy y arranca
# Tailwind en background + runserver con django-browser-reload.
# Python/templates: recarga automática. CSS: refrescar manualmente tras Tailwind recompilar.
# Los contenedores quedan activos al salir; para detenerlos: make dev-down.
dev: dev-up
	python manage.py migrate
	@trap 'kill $$(jobs -p) 2>/dev/null' EXIT INT TERM; \
	python manage.py tailwind start & \
	python manage.py runserver

tailwind:
	python manage.py tailwind start

# ── Comandos Django (dev: directo | prod: dentro del container) ───────────────
MANAGE := $(shell [ -f .env ] && . ./.env && [ "$${DEBUG}" = "False" ] && echo "docker compose exec django python manage.py" || echo "python manage.py")

migrate:
	$(MANAGE) migrate

migrations:
	$(MANAGE) makemigrations

shell:
	$(MANAGE) shell

superuser:
	$(MANAGE) createsuperuser

collect:
	$(MANAGE) collectstatic --noinput

# Copia solo los archivos PÚBLICOS al bucket (no toca media/privado). Para todo: make media-cdn
sync-media:
	$(MANAGE) sync_media

# Sube la media local al bucket y (opcional) libera el disco. Ej.: make media-cdn ARGS="--dry-run"
#   ARGS="--borrar-local --antiguedad 7d" | --prefijo photos/   (solo borra lo verificado en el bucket)
media-cdn:
	$(MANAGE) media_a_cdn $(ARGS)

# Desbloquea todos los accesos bloqueados por django-axes (si el bloqueado es el propio admin)
axes-reset:
	$(MANAGE) axes_reset

# ── Base de datos (dev) ────────────────────────────────────────────────────────
db-shell:
	@[ -f .env ] && . ./.env; \
	if [ -n "$${POSTGRES_DB}" ]; then \
		docker compose -f docker-compose.dev.yml exec postgres psql -U $${POSTGRES_USER} -d $${POSTGRES_DB}; \
	else \
		echo "Modo SQLite — usa: sqlite3 db.sqlite3"; \
	fi

db-reset:
	@[ -f db.sqlite3 ] && rm db.sqlite3 && echo "SQLite eliminado." || true
	python manage.py migrate

# ── Producción ────────────────────────────────────────────────────────────────
# make deploy                  → backup solo si hay migraciones pendientes
# make deploy BACKUP=always    → fuerza backup  |  BACKUP=never → lo omite
deploy:
	bash deploy.sh

nginx:
	bash nginx-deploy.sh

check-ports:
	bash check-ports.sh

# Backups de PostgreSQL (backups/*.sql.gz, retención: últimos 10)
backup:
	bash scripts/backup.sh manual

# make restore FILE=backups/20250101-120000-manual.sql.gz
restore:
	@[ -n "$(FILE)" ] || { echo "Uso: make restore FILE=backups/archivo.sql.gz"; exit 1; }
	bash scripts/restore.sh $(FILE)

# Vuelve a la imagen anterior (o make rollback TAG=<sha>). No revierte migraciones.
rollback:
	bash scripts/rollback.sh $(TAG)

ps:
	docker compose --profile postgres --profile n8n --profile n8n-mcp ps

restart:
	docker compose restart django

logs:
	docker compose logs -f --tail 100 django

down:
	docker compose --profile postgres --profile n8n --profile n8n-mcp down

.PHONY: setup dev-up dev-down dev-logs dev-check n8n-export n8n-import n8n-update install dev tailwind \
        migrate migrations shell superuser collect sync-media media-cdn axes-reset db-shell db-reset \
        deploy nginx check-ports backup restore rollback ps restart logs down
