from os import getenv
from pathlib import Path

from dotenv import load_dotenv

if Path("config.env").exists():
    load_dotenv("config.env")


def _csv_list(key: str, default: str = "") -> list[str]:
    raw = getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _int_list(key: str) -> list[int]:
    values: list[int] = []
    for item in _csv_list(key):
        try:
            values.append(int(item))
        except ValueError:
            continue
    return values


class Telegram:
    API_ID = int(getenv("API_ID", "0"))
    API_HASH = getenv("API_HASH", "")
    BOT_TOKEN = getenv("BOT_TOKEN", "")
    PORT = int(getenv("PORT", 8080))
    SESSION_STRING = getenv("SESSION_STRING", "")

    BASE_URL = getenv("BASE_URL", "").rstrip("/")
    MONGO_URI = getenv("MONGO_URI") or getenv("DATABASE_URL", "")
    DATABASE_URL = MONGO_URI  # backward compatibility for existing modules

    AUTH_CHANNEL = _csv_list("AUTH_CHANNEL")
    FORCE_SUB_CHANNELS = _csv_list("FORCE_SUB_CHANNELS") or AUTH_CHANNEL
    START_IMAGE_URL = getenv(
        "START_IMAGE_URL",
        "https://placehold.co/1280x720/png?text=Welcome+to+Movie+Bot",
    )
    ADMIN_IDS = _int_list("ADMIN_IDS")

    REQUIRED_BOT_USERNAME = "stream4u_bot"

    THEME = getenv("THEME", "vapor").lower()
    USERNAME = getenv("USERNAME", "admin")
    PASSWORD = getenv("PASSWORD", "admin")
    ADMIN_USERNAME = getenv("ADMIN_USERNAME", "surfTG")
    ADMIN_PASSWORD = getenv("ADMIN_PASSWORD", "surfTG")

    SLEEP_THRESHOLD = int(getenv("SLEEP_THRESHOLD", "60"))
    WORKERS = int(getenv("WORKERS", "10"))
    MULTI_CLIENT = getenv("MULTI_CLIENT", "False")
    HIDE_CHANNEL = getenv("HIDE_CHANNEL", "False")

    SEARCH_PAGE_SIZE = int(getenv("SEARCH_PAGE_SIZE", "8"))
