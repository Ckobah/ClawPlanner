# Инструкция по запуску tg_bot_clawd (с нуля)

Вот инструкция для стороннего человека, чтобы поднять всё как у меня.

## 1) Что нужно заранее

- Linux-сервер (Ubuntu/Debian подходит)
- `python3`, `python3-venv`, `git`, `ffmpeg`
- PostgreSQL (локально или удалённо)
- Telegram Bot Token от @BotFather
- Свой `tg_id` (кому бот будет отвечать)

---

## 2) Установка системных зависимостей

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg postgresql-client
```

Если PostgreSQL на этом же сервере — ставим и сервер:

```bash
sudo apt install -y postgresql
```

Если PostgreSQL установлен локально, лучше создать отдельного пользователя и базу под бота, и этот пароль положить в `DB_PASSWORD`.

Сделай так:

```bash
sudo -u postgres psql
```

Внутри `psql`:

```sql
CREATE USER clawd_bot WITH PASSWORD 'Passssswooorrddd1111';
CREATE DATABASE clawd_bot OWNER clawd_bot;
GRANT ALL PRIVILEGES ON DATABASE clawd_bot TO clawd_bot;
\q
```

Потом в `.env`:

```env
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=clawd_bot
DB_USERNAME=clawd_bot
DB_PASSWORD=Passssswooorrddd1111
```

---

## 3) Клонирование проекта

```bash
git clone https://github.com/Ckobah/ClawPlanner ~/tg_bot_clawd
cd ~/tg_bot_clawd
```

---

## 4) Настройка `.env` (интерактивно)

```bash
./scripts/configure.sh
```

Скрипт спросит:

- `TG_BOT_TOKEN`
- `ALLOWED_TG_IDS` (только твой `tg_id`)
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USERNAME`, `DB_PASSWORD`
- параметры Whisper (можно оставить по умолчанию)

---

## 5) Установка и запуск

```bash
./scripts/install.sh
```

Скрипт:

- создаст `.venv`
- поставит зависимости
- применит миграции
- создаст user systemd-сервис `tg-bot-clawd.service`
- запустит его

---

## 6) Проверка

```bash
./scripts/check.sh
systemctl --user status tg-bot-clawd.service --no-pager -n 30
journalctl --user -u tg-bot-clawd.service -n 50 --no-pager
```

---

## 7) Проверка в Telegram

В `@ваш_бот`:

1. `/start`
2. `📅 Показать календарь`
3. отправить фото афиши / PDF / голосовое

---

## 8) Автозапуск после ребута (важно)

Чтобы user-service стартовал без входа в shell:

```bash
sudo loginctl enable-linger $USER
```

---

## 9) Перезапустить бота

```bash
systemctl --user restart tg-bot-clawd.service
```
