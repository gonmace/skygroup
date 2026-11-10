#!/usr/bin/env bash
# Refresca en PRODUCCIÓN los datos de Registros (reg → empresa PTI) y Jornadas (skylog → empresa EMBOL):
# backup → vaciar datos operativos → reimportar. NO toca usuarios ni su contraseña.
#
# Se ejecuta EN EL VPS, con los datos legacy ya copiados a ./media/_legacy (la carpeta ./media está montada
# en el contenedor como /app/media). Desde tu máquina local:
#   rsync -az --info=progress2 -e "ssh -p <puerto>" backups/legacy/ <vps>:<ruta-proyecto>/media/_legacy/
#
#   bash scripts/refrescar_datos.sh              # simulación: dry-run de todo, no cambia nada
#   bash scripts/refrescar_datos.sh --aplicar    # backup + borrado + importación reales (pide confirmación)
#
# Variables: REG_SLUG=pti  JOR_SLUG=emb
# ATENCIÓN: con la CDN/S3 activa, vaciar_datos BORRA también del bucket las fotos/mapas de esas empresas
# (señales post_delete) y la importación las vuelve a subir. Hazlo en una ventana de bajo uso.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib.sh
load_env
build_profiles

REG_SLUG="${REG_SLUG:-pti}"
JOR_SLUG="${JOR_SLUG:-emb}"
L=/app/media/_legacy
APLICAR=0; [ "${1:-}" = "--aplicar" ] && APLICAR=1
m() { dc exec -T django python manage.py "$@"; }

for f in media/_legacy/reg/core_site.jsonl media/_legacy/skylog.sql.gz; do
  [ -f "$f" ] || { echo "Falta $f (copia backups/legacy/ a media/_legacy/, ver cabecera)." >&2; exit 1; }
done

echo "━━━ Simulación (dry-run) ━━━"
m vaciar_datos "$REG_SLUG" --dry-run
m vaciar_datos "$JOR_SLUG" --dry-run
m importar_reg "$REG_SLUG" --dir "$L/reg" --media "$L/reg_media" --dry-run
m importar_jor "$JOR_SLUG" --dump "$L/skylog.sql.gz" --dry-run

if [ "$APLICAR" != 1 ]; then
  echo; echo "Simulación terminada: no se cambió nada. Para aplicar: bash scripts/refrescar_datos.sh --aplicar"
  exit 0
fi

read -r -p "Esto BORRA y reimporta los datos de '$REG_SLUG' y '$JOR_SLUG' en PRODUCCIÓN. Escribe SI para continuar: " ok
[ "$ok" = "SI" ] || { echo "Cancelado."; exit 1; }

echo "━━━ Backup ━━━"
bash scripts/backup.sh antes-refresco

echo "━━━ Aplicando ━━━"
m vaciar_datos "$REG_SLUG"
m vaciar_datos "$JOR_SLUG"
m importar_reg "$REG_SLUG" --dir "$L/reg" --media "$L/reg_media"
m importar_jor "$JOR_SLUG" --dump "$L/skylog.sql.gz"
m asignar_proyecto_a_jornadas "$JOR_SLUG" --aplicar
echo "✓ Listo. Si algo sale mal: make restore FILE=backups/<el-backup-antes-refresco>.sql.gz"
