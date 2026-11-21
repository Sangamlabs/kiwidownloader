import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "KiwiDownloaderBot").strip().lstrip("@")
API_BASE = os.getenv("API_BASE", "https://api.kiwiapi.net").strip().rstrip("/")
API_KEY = os.getenv("API_KEY", "").strip()
TEMP_DIR = Path(os.getenv("TEMP_DIR", str(BASE_DIR / "tmp")))

TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Headers for KiwiAPI
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KiwiTelegramBot/1.0",
    "Content-Type": "application/json",
}
if API_KEY:
    HEADERS["X-API-Key"] = API_KEY
