#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[!] python3 not found"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[!] ffmpeg is required for voice processing"
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

./.venv/bin/pip install --upgrade pip wheel setuptools
./.venv/bin/pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[i] .env created from template. Run scripts/configure.sh"
fi

# DB migrations (requires filled .env)
if grep -q "^DB_PASSWORD=.*[^[:space:]]" .env; then
  ./.venv/bin/alembic upgrade heads || echo "[!] alembic failed. Check DB credentials in .env"
  ./.venv/bin/python ./scripts/sync_user_md.py || echo "[!] USER.md sync skipped"
else
  echo "[i] Skip alembic: DB credentials not configured yet"
fi

mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/tg-bot-clawd.service" <<EOF
[Unit]
Description=Telegram planner bot (OpenClaw package)
After=network.target

[Service]
WorkingDirectory=$ROOT_DIR
Environment=PATH=/home/$USER/.npm-global/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$ROOT_DIR/.venv/bin/python $ROOT_DIR/main.py
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now tg-bot-clawd.service

./scripts/setup_reminder_cron.sh || echo "[!] Failed to setup reminder cron jobs"

echo "[+] Installed and started tg-bot-clawd.service"
echo "[i] Check status: systemctl --user status tg-bot-clawd.service"
