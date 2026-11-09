# ── Stage 1: compilar CSS con Node (solo build, no va a producción) ─────────────
FROM node:24-slim AS css-builder

WORKDIR /app/theme/static_src

# Capa cacheable: las dependencias npm solo se reinstalan si cambia el lockfile
COPY theme/static_src/package.json theme/static_src/package-lock.json ./
RUN npm ci

# Tailwind escanea templates y apps al compilar (ver @source en styles.css)
# Se copia todo el repo (menos lo de .dockerignore) para que Tailwind vea todas las apps y static/js
COPY . /app
RUN npm run build

# ── Stage 2: imagen Python de producción (sin Node ni módulos npm) ─────────────
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=core.settings

WORKDIR /app

# WeasyPrint (PDF del reporte de Construcción) necesita pango y una fuente
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# psycopg2-binary trae libpq: no hacen falta gcc ni libpq-dev
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Usuario no-root (UID 1000: coincide con el dueño de ./staticfiles y ./media en el host)
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app

COPY --chown=app:app ./ ./

# CSS ya compilado y minificado desde la stage anterior
COPY --from=css-builder --chown=app:app /app/static/css/dist/ ./static/css/dist/

USER app

HEALTHCHECK --interval=15s --timeout=5s --start-period=300s --retries=3 \
    CMD python -c "import os, urllib.request as u; \
h=(os.environ.get('ALLOWED_HOSTS') or 'localhost').split(',')[0].strip(); \
r=u.Request('http://127.0.0.1:8000/healthz', headers={'Host': h, 'X-Forwarded-Proto': 'https'}); \
u.urlopen(r, timeout=4)" || exit 1

CMD ["sh", "entrypoint.sh"]
