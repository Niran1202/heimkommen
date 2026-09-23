#!/usr/bin/env bash
# Nightly Postgres backup on the VM (cron: 30 2 * * * ~/heimkommen/scripts/backup_db.sh).
# Backups contain user accounts: they stay on the VM (and optionally a private disk),
# never in the public GitHub repository.
set -euo pipefail

cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

source .env
stamp="$(date +%Y-%m-%d_%H%M)"
target="$BACKUP_DIR/heimkommen_${stamp}.sql.gz"

docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-heimkommen}" -d "${POSTGRES_DB:-heimkommen}" --no-owner \
  | gzip > "$target"
chmod 600 "$target"

# Sanity check: the dump must not be empty.
if [ "$(gzip -dc "$target" | head -c 100 | wc -c)" -lt 100 ]; then
  echo "backup $target looks empty" >&2
  exit 1
fi

find "$BACKUP_DIR" -name 'heimkommen_*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "backup written: $target ($(du -h "$target" | cut -f1))"
