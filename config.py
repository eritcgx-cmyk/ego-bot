"""
Ego Discord Bot - Configuration Module
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CLIENT_ID = os.getenv("CLIENT_ID", "")
raw_db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///ego_bot.db")

# Normalize Postgres dialect for async SQLAlchemy if needed
if raw_db_url.startswith("postgres://"):
    raw_db_url = raw_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif raw_db_url.startswith("postgresql://") and not raw_db_url.startswith("postgresql+asyncpg://"):
    raw_db_url = raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

DATABASE_URL = raw_db_url

DEFAULT_PREFIX = os.getenv("DEFAULT_PREFIX", "!")
EMBED_COLOR = int(os.getenv("EMBED_COLOR", "0x5865F2"), 16)
SUCCESS_COLOR = 0x57F287
ERROR_COLOR = 0xED4245
WARNING_COLOR = 0xFEE75C
INFO_COLOR = 0x5865F2

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
BOT_VERSION = "2.0.0"
VERSION = BOT_VERSION
BOT_NAME = "Ego"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("EgoBot")
