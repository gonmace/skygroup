#!/usr/bin/env bash
# Trae de producción (reg.tekon-rl.cl) los datos de Registros y los deja listos para `manage.py importar_reg`.
# Solo LEE del servidor: pg_dump dentro del contenedor y rsync del media. No modifica nada allá.
#
#   scripts/traer_legacy_reg.sh [dump|media|jsonl|todo]      (por defecto: todo)
#
# Variables (con sus valores por defecto):
#   REG_SSH=pti@45.90.123.172   REG_PORT=38   REG_DB_CONTAINER=db_reg_tekon
#   REG_MEDIA_REMOTO=/home/pti/Django/reg2.tekon-rl.cl/media
#   REG_DUMP=backups/legacy/reg.dump   (si ya tienes un dump, ponlo ahí y usa `jsonl`)
set -euo pipefail
cd "$(dirname "$0")/.."

SSH_DEST="${REG_SSH:-pti@45.90.123.172}"
PORT="${REG_PORT:-38}"
CONT="${REG_DB_CONTAINER:-db_reg_tekon}"
MEDIA_REMOTO="${REG_MEDIA_REMOTO:-/home/pti/Django/reg2.tekon-rl.cl/media}"
DUMP="${REG_DUMP:-backups/legacy/reg.dump}"
OUT_JSONL="backups/legacy/reg"
OUT_MEDIA="backups/legacy/reg_media"
TMP=reg_legacy_tmp
TABLAS=(users_user core_contractor core_site django_content_type
        actividades_tipoactividad actividades_pasodefinicion actividades_configpaso actividades_pasowidget
        actividades_datopaso reg_txtss_regtxtss reg_construccion_regconstruccion
        photos_photos core_googlemapsimage)
SSH=(ssh -p "$PORT" -o BatchMode=yes "$SSH_DEST")

dump() {
  mkdir -p "$(dirname "$DUMP")"
  echo "→ pg_dump desde $SSH_DEST ($CONT)…"
  # Usuario y base se leen del propio contenedor, no se escriben aquí.
  "${SSH[@]}" "docker exec $CONT sh -c 'pg_dump -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Fc --no-owner --no-acl'" > "$DUMP.part"
  mv "$DUMP.part" "$DUMP"
  chmod 600 "$DUMP"
  echo "  $(du -h "$DUMP" | cut -f1) en $DUMP"
}

media() {
  mkdir -p "$OUT_MEDIA"
  for d in photos google_maps; do
    echo "→ rsync media/$d…"
    rsync -az --info=progress2 -e "ssh -p $PORT -o BatchMode=yes" "$SSH_DEST:$MEDIA_REMOTO/$d/" "$OUT_MEDIA/$d/"
  done
}

jsonl() {
  [ -f "$DUMP" ] || { echo "No existe $DUMP (corre «dump» o déjalo ahí)." >&2; exit 1; }
  mkdir -p "$OUT_JSONL"
  trap 'docker rm -f $TMP >/dev/null 2>&1 || true' EXIT
  docker rm -f $TMP >/dev/null 2>&1 || true
  docker run -d --name $TMP -e POSTGRES_PASSWORD=x -e POSTGRES_DB=reg postgres:15-alpine >/dev/null
  until docker exec $TMP pg_isready -U postgres -d reg >/dev/null 2>&1; do sleep 1; done
  sleep 2
  echo "→ pg_restore en contenedor temporal…"
  docker exec -i $TMP pg_restore -U postgres -d reg --no-owner --no-acl < "$DUMP" || true   # avisos de extensiones son normales
  for t in "${TABLAS[@]}"; do
    docker exec $TMP psql -U postgres -d reg -At -c "select row_to_json(t) from $t t" > "$OUT_JSONL/$t.jsonl"
    printf '  %-45s %s filas\n' "$t" "$(wc -l < "$OUT_JSONL/$t.jsonl")"
  done
  chmod -R go-rwx "$OUT_JSONL"
}

case "${1:-todo}" in
  dump) dump ;;
  media) media ;;
  jsonl) jsonl ;;
  todo) dump; jsonl; media ;;
  *) echo "uso: $0 [dump|media|jsonl|todo]" >&2; exit 2 ;;
esac
