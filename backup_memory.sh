#!/bin/bash
# Backs up the mcpo memory-server's persistent memory.json (stored only in the
# mcpo-memory Docker volume) so it survives `docker compose down -v`.
set -euo pipefail

cd "$(dirname "$0")"

BACKUP_DIR="./memory_backups"
KEEP_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

docker cp mcpo:/data/memory.json "$BACKUP_DIR/memory_${TIMESTAMP}.json"
echo "Backed up memory.json -> $BACKUP_DIR/memory_${TIMESTAMP}.json"

find "$BACKUP_DIR" -name 'memory_*.json' -mtime +"$KEEP_DAYS" -delete
