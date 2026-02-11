import os

from dotenv import load_dotenv

load_dotenv(".env")


MONTH_NAMES = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
NEAREST_EVENTS_DAYS = 10


TOKEN = os.getenv("TG_BOT_TOKEN")
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN")
MAX_API_BASE = os.getenv("MAX_API_BASE", "https://platform-api.max.ru")
MAX_WEBHOOK_URL = os.getenv("MAX_WEBHOOK_URL")
MAX_WEBHOOK_SECRET = os.getenv("MAX_WEBHOOK_SECRET")
WEBHOOK_MAX_URL = os.getenv("WEBHOOK_MAX_URL") or MAX_WEBHOOK_URL
WEBHOOK_MAX_SECRET = os.getenv("WEBHOOK_MAX_SECRET") or MAX_WEBHOOK_SECRET
MAX_WEBHOOK_PORT = int(os.getenv("MAX_WEBHOOK_PORT", "8443"))
MAX_POLL_TIMEOUT = int(os.getenv("MAX_POLL_TIMEOUT", "30"))


LOCAL = os.getenv("LOCAL")

if LOCAL:
    database_url = "sqlite+aiosqlite:///bot.db"
else:
    DB_USERNAME = os.getenv("DB_USERNAME")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = os.getenv("DB_PORT")
    DB_NAME = os.getenv("DB_NAME")
    database_url = f"postgresql+asyncpg://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

DEFAULT_TIMEZONE: int = 3  # +3 MSK
DEFAULT_TIMEZONE_NAME: str = "Europe/Moscow"  # +3 MSK

SERVICE_ACCOUNTS: str = os.getenv("SERVICE_ACCOUNTS", None)

WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", None)
WEBHOOK_SECRET_TOKEN: str = os.getenv("WEBHOOK_SECRET_TOKEN", None)
