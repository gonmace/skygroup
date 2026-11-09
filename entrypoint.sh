#!/bin/sh
set -e

MAX_TRIES=60   # 60 intentos x 2s = 2 min

wait_for() {
    name="$1"; shift
    i=0
    echo "Esperando a ${name}..."
    until python -c "$@" 2>/dev/null; do
        i=$((i + 1))
        if [ "$i" -ge "$MAX_TRIES" ]; then
            echo "Error: ${name} no disponible tras $((MAX_TRIES * 2))s." >&2
            exit 1
        fi
        sleep 2
    done
    echo "${name} listo."
}

wait_for PostgreSQL "
import psycopg2, os
psycopg2.connect(
    dbname=os.environ['POSTGRES_DB'],
    user=os.environ['POSTGRES_USER'],
    password=os.environ['POSTGRES_PASSWORD'],
    host=os.environ.get('POSTGRES_HOST', 'postgres'),
    port=os.environ.get('POSTGRES_PORT', '5432'),
    connect_timeout=3,
).close()
"

wait_for Redis "
import redis, os
redis.from_url(os.environ.get('REDIS_URL', 'redis://redis:6379/0'), socket_connect_timeout=3).ping()
"

echo 'Recopilando archivos estáticos...'
python manage.py collectstatic --noinput
chmod -R o+rX /app/staticfiles

echo 'Ejecutando migraciones...'
python manage.py migrate --noinput

echo 'Iniciando Gunicorn (ASGI, worker uvicorn: HTTP + WebSocket)...'
exec gunicorn core.asgi:application \
    -k uvicorn_worker.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout 60 \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --access-logfile - \
    --error-logfile -
