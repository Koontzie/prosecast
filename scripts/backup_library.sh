#!/bin/bash
# ProseCast library backup → Gideon Bolt pool
#
# Backs up the precious parts of library/ (ir.json, voice_map.json,
# corrections.jsonl) to /mnt/bolt/backups/prosecast/library/ on TrueNAS.
# renders/ and exports/ are excluded — they're disposable and reproducible.
#
# Deliberately NO --delete: a local mistake can never propagate to the backup.
# Books removed locally linger on Bolt until cleaned up by hand.
#
# Destination: an rsync target like user@host:/path/, read from (first hit wins)
#   1. $PROSECAST_BACKUP_DEST
#   2. .backup/dest   (one line; .backup/ is gitignored, so it never gets committed)
# Auth: uses .backup/prosecast_backup_ed25519 if present (key is in the NAS
# user's authorized keys), else falls back to your default SSH key.
#
# One-time setup:  mkdir -p .backup && echo 'NAS_USER@GIDEON_HOST:/mnt/bolt/backups/prosecast/library/' > .backup/dest
# Run manually:    ./scripts/backup_library.sh
# Run nightly:     see scripts/com.prosecast.backup.plist
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$PROJECT_DIR/library/"
KEY="$PROJECT_DIR/.backup/prosecast_backup_ed25519"
LOG="$PROJECT_DIR/.backup/last_backup.log"

mkdir -p "$PROJECT_DIR/.backup"

DEST="${PROSECAST_BACKUP_DEST:-}"
if [ -z "$DEST" ] && [ -f "$PROJECT_DIR/.backup/dest" ]; then
  DEST="$(head -n1 "$PROJECT_DIR/.backup/dest" | tr -d '[:space:]')"
fi
if [ -z "$DEST" ]; then
  echo "backup_library.sh: no destination. Set PROSECAST_BACKUP_DEST or write one line" >&2
  echo "  like user@host:/path/to/backups/library/ into $PROJECT_DIR/.backup/dest" >&2
  exit 2
fi

# Note: key path is quoted inside the -e string — the project path has spaces
SSH_CMD="ssh -o BatchMode=yes -o ConnectTimeout=15"
[ -f "$KEY" ] && SSH_CMD="$SSH_CMD -i \"$KEY\""

{
  echo "=== ProseCast backup $(date '+%Y-%m-%d %H:%M:%S') ==="
  rsync -av --stats \
    --exclude 'renders/' \
    --exclude 'exports/' \
    -e "$SSH_CMD" \
    "$SRC" "$DEST"
  echo "=== OK ==="
} 2>&1 | tee "$LOG"
