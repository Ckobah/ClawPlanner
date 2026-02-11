Use this prompt in OpenClaw to install this bot from a GitHub repo on a new host.

---

Склонируй репозиторий Telegram-бота и разверни его как user-systemd сервис.

Шаги:
1) `git clone https://github.com/Ckobah/ClawPlanner ~/tg_bot_clawd && cd ~/tg_bot_clawd`
2) Запусти `./scripts/configure.sh` и запроси у меня:
   - `TG_BOT_TOKEN`
   - `ALLOWED_TG_IDS` (мой tg id)
   - `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USERNAME`, `DB_PASSWORD`
3) Запусти `./scripts/install.sh`
4) Запусти `./scripts/check.sh`
5) Покажи итог:
   - `systemctl --user status tg-bot-clawd.service --no-pager -n 30`
   - последние логи `journalctl --user -u tg-bot-clawd.service -n 50 --no-pager`

Если не хватает зависимостей ОС (например ffmpeg), установи их и повтори.

---
