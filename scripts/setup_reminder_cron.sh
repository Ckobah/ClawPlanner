#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_BIN="$ROOT_DIR/.venv/bin/python"
CRON_TAG="# clawplanner-reminders"

if [[ ! -x "$PY_BIN" ]]; then
  echo "[!] Python venv not found at $PY_BIN"
  echo "    Run ./scripts/install.sh first"
  exit 1
fi

HOUR_LINE="* * * * * (cd $ROOT_DIR && $PY_BIN $ROOT_DIR/cron_handler.py) >> /tmp/tg_cron_output.log 2>&1 $CRON_TAG"
NOW_LINE="* * * * * (cd $ROOT_DIR && $PY_BIN $ROOT_DIR/cron_handler.py --now True) >> /tmp/tg_cron_output.log 2>&1 $CRON_TAG"

CURRENT_CRON="$(crontab -l 2>/dev/null || true)"
# Remove old clawplanner lines, keep everything else.
CLEAN_CRON="$(printf "%s\n" "$CURRENT_CRON" | grep -v "$CRON_TAG" || true)"

NEW_CRON="$(printf "%s\n%s\n%s\n" "$CLEAN_CRON" "$HOUR_LINE" "$NOW_LINE" | sed '/^[[:space:]]*$/d')"

printf "%s\n" "$NEW_CRON" | crontab -

echo "[+] Reminder cron jobs installed/updated"
echo "[i] Current crontab:"
crontab -l
