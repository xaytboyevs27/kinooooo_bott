import time
import logging
import os
import json
from config import RATE_LIMIT

# Always use project directory for logs, regardless of working directory
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_LOGS_DIR = os.path.join(_PROJECT_DIR, "logs")
os.makedirs(_LOGS_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_LOGS_DIR, "bot.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("kinooooo_bot")

_LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
_TRANSLATIONS = {}

def _load_translations():
    global _TRANSLATIONS
    for lang_code in ["uz", "ru", "en"]:
        path = os.path.join(_LOCALES_DIR, f"{lang_code}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                _TRANSLATIONS[lang_code] = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load locale {lang_code}: {e}")
            _TRANSLATIONS[lang_code] = {}

_load_translations()

def get_text(lang, key):
    data = _TRANSLATIONS.get(lang, _TRANSLATIONS.get("uz", {}))
    if key in data:
        return data[key]
    fallback = _TRANSLATIONS.get("uz", {})
    return fallback.get(key, f"[{key}]")

def check_rate(user_id):
    from db import connect
    now = int(time.time())
    try:
        con = connect()
        cur = con.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits(
            user_id INTEGER PRIMARY KEY,
            last_ts INTEGER
        )
        """)
        con.commit()
        cur.execute("SELECT last_ts FROM rate_limits WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        last = row[0] if row else 0
        if now - last < RATE_LIMIT:
            con.close()
            return False
        cur.execute(
            "INSERT INTO rate_limits(user_id, last_ts) VALUES(?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_ts=excluded.last_ts",
            (user_id, now)
        )
        con.commit()
        con.close()
        return True
    except Exception as e:
        logger.error(f"Rate-limit DB error for user {user_id}: {e}")
        now2 = time.time()
        global _MEM_RATE_FALLBACK
        try:
            _MEM_RATE_FALLBACK
        except NameError:
            _MEM_RATE_FALLBACK = {}
        last2 = _MEM_RATE_FALLBACK.get(user_id, 0)
        if now2 - last2 < RATE_LIMIT:
            return False
        _MEM_RATE_FALLBACK[user_id] = now2
        return True

def is_admin(user_id):
    from config import SUPERADMIN_ID
    from db import connect
    if str(user_id) == str(SUPERADMIN_ID):
        return True
    try:
        con = connect()
        cur = con.cursor()
        cur.execute("SELECT role FROM admins WHERE user_id=?", (user_id,))
        res = cur.fetchone()
        con.close()
        return bool(res)
    except Exception as e:
        logger.error(f"is_admin error for user {user_id}: {e}")
        return False

def log_error(context, error):
    logger.error(f"{context}: {error}", exc_info=True)
