#!/usr/bin/env bash
# Inspired by oh-my-zsh update mechanism:
# - timestamp file controls check frequency (MTU_UPDATE_DAYS, default 7)
# - shows version diff on update
# - FORCE=1 bypasses interval check (used by `make update`)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LAST_CHECK_FILE="$ROOT_DIR/.last-update-check"
LOG_FILE="$ROOT_DIR/auto-update.log"
UPDATE_DAYS="${MTU_UPDATE_DAYS:-7}"
FORCE="${FORCE:-0}"
MAX_LOG_LINES=500

cd "$ROOT_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

trim_log() {
    if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt "$MAX_LOG_LINES" ]; then
        tail -n "$MAX_LOG_LINES" "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
    fi
}

# ── Skip if recently checked (omz-style interval) ────────────────────────────
if [ "$FORCE" != "1" ] && [ -f "$LAST_CHECK_FILE" ]; then
    LAST_CHECK=$(cat "$LAST_CHECK_FILE")
    NOW=$(date +%s)
    INTERVAL=$((UPDATE_DAYS * 86400))
    if [ $((NOW - LAST_CHECK)) -lt "$INTERVAL" ]; then
        exit 0
    fi
fi

date +%s > "$LAST_CHECK_FILE"
trim_log

# ── Fetch remote ──────────────────────────────────────────────────────────────
if ! git fetch --tags --quiet 2>/dev/null; then
    log "WARN: git fetch failed — skipping"
    exit 0
fi

REMOTE=$(git rev-parse "@{u}" 2>/dev/null || true)
if [ -z "$REMOTE" ]; then
    log "WARN: no upstream branch configured"
    exit 0
fi

LOCAL=$(git rev-parse HEAD)
if [ "$LOCAL" = "$REMOTE" ]; then
    log "Already up to date ($(git describe --tags --always))"
    exit 0
fi

# ── Show diff ─────────────────────────────────────────────────────────────────
OLD_VERSION=$(git describe --tags --always)
NEW_VERSION=$(git describe --tags --always "$REMOTE" 2>/dev/null || git rev-parse --short "$REMOTE")

log "Update available: $OLD_VERSION → $NEW_VERSION"
echo ""
echo "MTU update: $OLD_VERSION → $NEW_VERSION"
echo ""
echo "Changes:"
git log "${LOCAL}..${REMOTE}" --pretty=format:"  · %s" --no-merges | head -10
echo ""

# ── Pull + rebuild + redeploy ─────────────────────────────────────────────────
git pull --ff-only

log "Rebuilding..."
docker compose build --quiet

log "Restarting..."
docker compose up -d

FINAL=$(git describe --tags --always)
log "Done: $OLD_VERSION → $FINAL"
echo "Updated to $FINAL"
echo ""
