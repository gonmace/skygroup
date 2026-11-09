#!/bin/bash
# backup.sh — volcado comprimido de PostgreSQL a backups/<fecha>-<etiqueta>.sql.gz y, aparte, copia de media/
# (backups/<fecha>-<etiqueta>-media.tar.gz; BACKUP_MEDIA=0 la omite).
# Uso: bash scripts/backup.sh [etiqueta]      (retención: últimos 10 de cada tipo)
# Imprime en stdout SOLO la ruta del volcado SQL (la usan deploy.sh y restore).

set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib.sh
load_env
build_profiles

LABEL=${1:-manual}
KEEP=${BACKUP_KEEP:-10}
mkdir -p backups
OUT="backups/$(date +%Y%m%d-%H%M%S)-${LABEL}.sql.gz"
TMP="${OUT}.partial"
trap 'rm -f "$TMP"' EXIT

if [ "${POSTGRES_MODE}" = "container" ]; then
    dc exec -T postgres pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --no-owner | gzip > "$TMP"
else
    docker run --rm --add-host host.docker.internal:host-gateway \
        -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres:17-alpine \
        pg_dump -h "${POSTGRES_HOST:-host.docker.internal}" -p "${POSTGRES_PORT:-5432}" \
        -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --no-owner | gzip > "$TMP"
fi

# gzip de un volcado vacío pesa ~20 bytes: exigir contenido real
if [ "$(stat -c %s "$TMP")" -lt 200 ]; then
    echo "Error: el backup salió vacío." >&2
    exit 1
fi
mv "$TMP" "$OUT"
chmod 600 "$OUT"

# Retención
ls -1t backups/*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

# Archivos subidos (fotos, adjuntos, plantillas .xlsx): no están en la base de datos. Mensajes a stderr.
if [ "${BACKUP_MEDIA:-1}" != "0" ] && [ -d media ] && [ -n "$(ls -A media 2>/dev/null)" ]; then
    MEDIA_OUT="${OUT%.sql.gz}-media.tar.gz"
    if tar -czf "${MEDIA_OUT}.partial" media 2>/dev/null; then
        mv "${MEDIA_OUT}.partial" "$MEDIA_OUT"
        chmod 600 "$MEDIA_OUT"
        ls -1t backups/*-media.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
        echo "media: $MEDIA_OUT" >&2
    else
        rm -f "${MEDIA_OUT}.partial"
        echo "Aviso: no se pudo respaldar media/." >&2
    fi
fi

echo "$OUT"
