#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[i] Updating ClawPlanner in: $ROOT_DIR"

if [[ ! -d .git ]]; then
  echo "[!] Not a git repository: $ROOT_DIR"
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "[!] git not found"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[!] python3 not found"
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "[!] .env not found. Run ./scripts/configure.sh first"
  exit 1
fi

# Update code
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "[i] Branch: $CURRENT_BRANCH"
git fetch --all --prune

git pull --ff-only

# Ensure venv + deps
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

./.venv/bin/pip install --upgrade pip wheel setuptools
./.venv/bin/pip install -r requirements.txt

# Run migrations (safe to run repeatedly)
./.venv/bin/alembic upgrade heads

# Restart service
systemctl --user daemon-reload
systemctl --user restart tg-bot-clawd.service

# Health output
echo "\n== Service status =="
systemctl --user --no-pager -n 20 status tg-bot-clawd.service || true

echo "\n== Last logs =="
journalctl --user -u tg-bot-clawd.service -n 40 --no-pager || true

echo "\n[+] Update complete"
