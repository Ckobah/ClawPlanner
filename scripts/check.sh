#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== Service =="
systemctl --user is-active tg-bot-clawd.service || true

echo "== Recent logs =="
journalctl --user -u tg-bot-clawd.service -n 30 --no-pager || true

echo "== Python deps =="
./.venv/bin/python - <<'PY'
mods=['telegram','sqlalchemy','asyncpg','pypdf','fitz','rapidocr_onnxruntime','faster_whisper']
for m in mods:
    try:
        __import__(m)
        print(f"{m}: OK")
    except Exception as e:
        print(f"{m}: FAIL ({e})")
PY

echo "== OpenClaw binary =="
command -v openclaw || echo "openclaw not in PATH (service uses explicit PATH)"

echo "[+] Check complete"
