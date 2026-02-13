# tg-organazer

Telegram bot for personal events and reminders with calendar UI, participants, and recurring events.

Русская версия: `README.ru.md`.

## Features
- Calendar-based event creation and browsing.
- Start/stop time picker and descriptions.
- Emoji selection for events.
- Recurrence: daily, weekly, monthly, annual.
- Participants and shared events via contacts.
- Upcoming events list.
- Background reminder sender (`cron_handler.py`).
- Inline edits of the event constructor message to reduce chat noise.
- Built-in i18n with Babel (`ru`/`en`) for Telegram bot and `max_bot`.

## Tech stack
- Python 3.12
- python-telegram-bot
- SQLAlchemy (async) + Alembic
- PostgreSQL or SQLite (local)

## Project structure
- `main.py` - bot entry point and handlers registration.
- `handlers/` - Telegram handlers (calendar, events, contacts, start).
- `database/` - async DB session and controller.
- `entities.py` - Pydantic models for event/user entities.
- `cron_handler.py` - scheduled reminders.
- `migrations/` - Alembic migrations.
- `api/` - NestJS API for the web app (PostgreSQL).
- `web/` - React SPA (calendar UI + Telegram login).

## Requirements
- Python 3.12
- Telegram bot token from @BotFather
- Database (PostgreSQL recommended for production)

## Environment variables
Create a `.env` file in the project root:

```env
TG_BOT_TOKEN=your_telegram_bot_token

# Use SQLite locally
LOCAL=1

# Or use PostgreSQL in production
# DB_USERNAME=postgres
# DB_PASSWORD=secret
# DB_HOST=localhost
# DB_PORT=5432
# DB_NAME=tg_organazer
```

Notes:
- When `LOCAL` is set, SQLite is used (`sqlite+aiosqlite:///bot.db`).
- Otherwise, PostgreSQL credentials are required.

## Installation
Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies from `pyproject.toml`:

```powershell
python -m pip install .
```

Localization assets are stored in `locales/<lang>/LC_MESSAGES/messages.po`.

## Database setup
Run migrations:

```powershell
alembic upgrade head
```

For local SQLite, the database file `bot.db` will be created automatically.

## Running the bot

```powershell
python main.py
```

## Running scheduled reminders
This script finds events for the current time and sends reminders:

```powershell
python cron_handler.py
```

Use Task Scheduler or any cron equivalent to run it periodically.

## Testing
Install test dependencies in the active environment:

```powershell
python -m pip install pytest pytest-asyncio
```

Run tests:

```powershell
python -m pytest -q
```

## Usage examples
Start the bot and create an event through the calendar:
- Open the bot in Telegram.
- Choose "Calendar" from the keyboard.
- Select a date, set time and description.
- Save and verify it appears on the selected day.

Notes:
- The constructor message is edited in place when you change time, emoji, description, recurrence, or participants.
- The description prompt appears as a separate message and is removed after you send the text (same as manual time input).

Add a participant:
- Share a contact in the chat.
- Create an event and select participants from the list.
- Participant receives a notification with a cancellation button.

## Development notes
- Default timezone offset is `DEFAULT_TIMEZONE = 3` (MSK).
- Time is stored in UTC in the database.
- For recurring events, the controller expands the occurrence list on demand.

## License
Specify your license here.

## Web app
API (NestJS):

```powershell
cd api
cp .env.example .env
npm install
npm run start:dev
```

SPA (React):

```powershell
cd web
cp .env.example .env
npm install
npm run dev
```

Web app capabilities:
- month calendar with per-day counts;
- day view for the selected date;
- create events with time, recurrence, and participants;
- delete events (including canceling a single recurrence);
- participant management with inactive status labels.

Bot-only features (not available in the web app):
- event emojis;
- event editing;
- upcoming events list;
- reschedule by +1 hour / next day from reminders;
- week navigation in the calendar.

Environment notes:
- `TG_BOT_TOKEN` is required in `api/.env` for Telegram login signature checks.
- `VITE_TG_BOT_USERNAME` must match your bot username for the login widget.
- `CLIENT_URL` should point to the SPA URL (comma-separated list allowed).

## VPS deployment (outline)
- Build API: `npm run build` in `api/`, run with pm2 or systemd on port 3000.
- Build SPA: `npm run build` in `web/`, serve `web/dist` via Nginx.
- Configure Nginx reverse proxy to `http://127.0.0.1:3000` for `/api` or a separate subdomain.
