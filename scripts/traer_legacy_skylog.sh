#!/usr/bin/env bash
# Trae de producción (skylog.redlinegs.com) un dump de texto actualizado y lo deja donde lo espera
# `manage.py importar_jor <slug>`: backups/legacy/skylog.sql.gz. Solo LEE del servidor (pg_dump dentro del contenedor).
#
#   scripts/traer_legacy_skylog.sh
#
# Variables (valores por defecto: servidor de skylog):
#   SKYLOG_SSH=magoreal@5.189.180.185   SKYLOG_PORT=38   SKYLOG_DB_CONTAINER=skylog_db
#   SKYLOG_DUMP=backups/legacy/skylog.sql.gz
set -euo pipefail
cd "$(dirname "$0")/.."

SSH_DEST="${SKYLOG_SSH:-magoreal@5.189.180.185}"
PORT="${SKYLOG_PORT:-38}"
CONT="${SKYLOG_DB_CONTAINER:-skylog_db}"
DUMP="${SKYLOG_DUMP:-backups/legacy/skylog.sql.gz}"

mkdir -p "$(dirname "$DUMP")"
# Conserva el dump anterior por si el nuevo falla o trae menos datos.
if [ -f "$DUMP" ]; then
  cp -p "$DUMP" "$DUMP.$(date +%Y%m%d-%H%M%S).bak"
fi

echo "→ pg_dump (texto) desde $SSH_DEST ($CONT)…"
# Usuario y base se leen del propio contenedor, no se escriben aquí.
ssh -p "$PORT" -o BatchMode=yes "$SSH_DEST" \
  "docker exec $CONT sh -c 'pg_dump -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" --no-owner --no-acl'" \
  | gzip > "$DUMP.part"
mv "$DUMP.part" "$DUMP"
chmod 600 "$DUMP"
echo "  $(du -h "$DUMP" | cut -f1) en $DUMP"
echo "Siguiente: python manage.py importar_jor <slug> --dry-run   (y luego sin --dry-run)"
