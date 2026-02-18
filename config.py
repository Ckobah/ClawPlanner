import os

from dotenv import load_dotenv

load_dotenv(".env")


MONTH_NAMES = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
NEAREST_EVENTS_DAYS = 10


TOKEN = os.getenv("TG_BOT_TOKEN")


LOCAL = os.getenv("LOCAL")
MULTI_USER_MODE = os.getenv("MULTI_USER_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}

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

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "ru")

WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", None)
WEBHOOK_SECRET_TOKEN: str = os.getenv("WEBHOOK_SECRET_TOKEN", None)
