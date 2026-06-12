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
# Auth: uses .backup/prosecast_backup_ed25519 if present (key is in
# NAS_USER's authorized keys), else falls back to your default SSH key.
#
# Run manually:   ./scripts/backup_library.sh
# Run nightly:    see scripts/com.prosecast.backup.plist
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$PROJECT_DIR/library/"
DEST="NAS_USER@GIDEON_HOST:/mnt/bolt/backups/prosecast/library/"
KEY="$PROJECT_DIR/.backup/prosecast_backup_ed25519"
LOG="$PROJECT_DIR/.backup/last_backup.log"

mkdir -p "$PROJECT_DIR/.backup"

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
