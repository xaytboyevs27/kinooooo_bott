import os
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

# SUPERADMIN_ID bo'sh yoki yo'q bo'lsa xatolik bermasligi uchun tekshiruv qo'shildi
_superadmin = os.getenv("SUPERADMIN_ID")
SUPERADMIN_ID = int(_superadmin) if _superadmin and _superadmin.strip() else 0

# Always use absolute path so DB is created in project dir, not cwd
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_BASE_DIR, "database.db")
RATE_LIMIT = 2
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")