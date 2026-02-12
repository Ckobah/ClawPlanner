# ClawPlanner (Telegram Calendar Bot)

Telegram bot for personal events/reminders with calendar UI, AI fallback, local OCR (images/PDF), and local voice transcription.

Русская версия: `README.ru.md`.

## Install from scratch (for any OpenClaw host)

### 1) Prerequisites
- Linux server (Ubuntu/Debian)
- `python3`, `python3-venv`, `git`, `ffmpeg`
- PostgreSQL (local or remote)
- Telegram Bot Token from `@BotFather`
- Your `tg_id` (who is allowed to use the bot)

### 2) Install system dependencies
```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg postgresql-client
```

If PostgreSQL is on the same server:
```bash
sudo apt install -y postgresql
```

### 2.1) Create PostgreSQL user/database (recommended)
```bash
sudo -u postgres psql
```

Inside `psql`:
```sql
CREATE USER clawd_bot WITH PASSWORD 'YOUR_STRONG_PASSWORD_HERE';
CREATE DATABASE clawd_bot OWNER clawd_bot;
GRANT ALL PRIVILEGES ON DATABASE clawd_bot TO clawd_bot;
\q
```

Use these values in `.env`:
```env
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=clawd_bot
DB_USERNAME=clawd_bot
DB_PASSWORD=YOUR_STRONG_PASSWORD_HERE
```

### 3) Clone project
```bash
git clone https://github.com/Ckobah/ClawPlanner ~/tg_bot_clawd
cd ~/tg_bot_clawd
```

### 4) Configure `.env` (interactive)
```bash
./scripts/configure.sh
```
It will ask for:
- `TG_BOT_TOKEN`
- `ALLOWED_TG_IDS` (usually only your `tg_id`)
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USERNAME`, `DB_PASSWORD`
- `WHISPER_MODEL`, `WHISPER_LANGUAGE`

### 5) Install and start
```bash
./scripts/install.sh
```
This script will:
- create `.venv`
- install dependencies
- run Alembic migrations
- create user systemd service `tg-bot-clawd.service`
- start the service

### 6) Check
```bash
./scripts/check.sh
systemctl --user status tg-bot-clawd.service --no-pager -n 30
journalctl --user -u tg-bot-clawd.service -n 50 --no-pager
```

### 7) Telegram smoke test
In `@your_bot`:
1. `/start`
2. `📅 Show calendar`
3. send poster photo / PDF / voice message

### 8) Autostart after reboot (important)
```bash
sudo loginctl enable-linger $USER
```

## Update bot to latest version

### One command (recommended)
```bash
cd ~/tg_bot_clawd && ./scripts/update.sh
```

What it does automatically:
- pulls latest code from GitHub
- updates Python dependencies
- applies Alembic migrations
- restarts `tg-bot-clawd.service`
- prints service status and recent logs

### If update fails
```bash
cd ~/tg_bot_clawd
./scripts/check.sh
systemctl --user status tg-bot-clawd.service --no-pager -n 50
journalctl --user -u tg-bot-clawd.service -n 100 --no-pager
```

## Features
- Calendar-based event creation and browsing
- Time/description/recurrence editing
- AI fallback for non-calendar text requests
- Event extraction from image posters/tickets (local OCR)
- Event extraction from PDF (text layer + OCR fallback)
- Voice transcription (local Whisper)
- Access restriction by `ALLOWED_TG_IDS`

## Runtime notes
- Long polling by default (`WEBHOOK_URL` empty)
- Times are stored in UTC in DB, shown in user timezone
- Single-user mode: participants/team UI is disabled
