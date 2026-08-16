from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
DATABASE_DIR = PROJECT_ROOT / "database"
SCHEMA_PATH = DATABASE_DIR / "schema.sql"
SPENDING_DB_PATH = DATABASE_DIR / "spending.db"
BANKS_CONFIG_PATH = CONFIG_DIR / "banks.json"
LOGS_DIR = PROJECT_ROOT / "logs"
VENDOR_EXPORTER = PROJECT_ROOT / "vendor" / "imessage-exporter"
RUST_READER_DIR = PROJECT_ROOT / "collector" / "imessage_reader"
DEFAULT_CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"
