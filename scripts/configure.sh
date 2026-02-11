#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env.example ]]; then
  echo "[!] .env.example not found"
  exit 1
fi

if [[ -f .env ]]; then
  read -r -p ".env exists. Overwrite? [y/N]: " OVERWRITE
  OVERWRITE=${OVERWRITE:-N}
  if [[ ! "$OVERWRITE" =~ ^[Yy]$ ]]; then
    echo "Abort."
    exit 0
  fi
fi

read -r -p "TG_BOT_TOKEN: " TG_BOT_TOKEN
read -r -p "ALLOWED_TG_IDS (e.g. 123456789): " ALLOWED_TG_IDS
read -r -p "DB_HOST [127.0.0.1]: " DB_HOST
DB_HOST=${DB_HOST:-127.0.0.1}
read -r -p "DB_PORT [5432]: " DB_PORT
DB_PORT=${DB_PORT:-5432}
read -r -p "DB_NAME [postgres]: " DB_NAME
DB_NAME=${DB_NAME:-postgres}
read -r -p "DB_USERNAME [postgres]: " DB_USERNAME
DB_USERNAME=${DB_USERNAME:-postgres}
read -r -s -p "DB_PASSWORD: " DB_PASSWORD
echo
read -r -p "WHISPER_MODEL [small]: " WHISPER_MODEL
WHISPER_MODEL=${WHISPER_MODEL:-small}
read -r -p "WHISPER_LANGUAGE [ru]: " WHISPER_LANGUAGE
WHISPER_LANGUAGE=${WHISPER_LANGUAGE:-ru}

cat > .env <<EOF
TG_BOT_TOKEN="$TG_BOT_TOKEN"
ALLOWED_TG_IDS=$ALLOWED_TG_IDS

DB_USERNAME=$DB_USERNAME
DB_PASSWORD=$DB_PASSWORD
DB_HOST=$DB_HOST
DB_PORT=$DB_PORT
DB_NAME=$DB_NAME

SERVICE_ACCOUNTS=
WEBHOOK_URL=
WEBHOOK_SECRET_TOKEN=

WHISPER_MODEL=$WHISPER_MODEL
WHISPER_LANGUAGE=$WHISPER_LANGUAGE

MAX_BOT_TOKEN=
MAX_API_BASE=https://platform-api.max.ru
MAX_POLL_TIMEOUT=30
WEBHOOK_MAX_URL=
WEBHOOK_MAX_SECRET=
MAX_WEBHOOK_PORT=18003
EOF

echo "[+] .env configured"
