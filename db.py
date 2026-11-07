import sqlite3
from config import DB_PATH

def connect():
    return sqlite3.connect(DB_PATH)

def init_db():
    con = connect()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_banned INTEGER DEFAULT 0,
        vip_until TIMESTAMP,
        language TEXT DEFAULT 'uz',
        role TEXT DEFAULT 'user'
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS media(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        type TEXT,
        title TEXT,
        description TEXT,
        views INTEGER DEFAULT 0,
        file_id TEXT,
        genres TEXT DEFAULT '',
        is_vip INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seasons(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        media_id INTEGER,
        season_number INTEGER,
        FOREIGN KEY(media_id) REFERENCES media(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS episodes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_id INTEGER,
        episode_number INTEGER,
        file_id TEXT,
        FOREIGN KEY(season_id) REFERENCES seasons(id)
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS force_sub_channels(
        chat_id TEXT PRIMARY KEY,
        invite_link TEXT,
        title TEXT
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS vouchers(
        code TEXT PRIMARY KEY,
        duration_days INTEGER,
        is_used INTEGER DEFAULT 0
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS favorites(
        user_id INTEGER,
        media_id INTEGER,
        PRIMARY KEY (user_id, media_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notifications(
        user_id INTEGER
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ads(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT,
        image_id TEXT,
        button_text TEXT,
        button_url TEXT,
        is_active INTEGER DEFAULT 1,
        views INTEGER DEFAULT 0
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_checkins(
        user_id INTEGER PRIMARY KEY,
        last_checkin TIMESTAMP,
        streak INTEGER DEFAULT 0,
        points INTEGER DEFAULT 0
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sys_settings(
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS watch_history(
        user_id INTEGER,
        media_id INTEGER,
        episode_id INTEGER,
        watched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, episode_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ratings(
        user_id INTEGER,
        media_id INTEGER,
        score INTEGER,
        PRIMARY KEY (user_id, media_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS search_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        query TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        action TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        provider_payment_charge_id TEXT,
        amount INTEGER,
        currency TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins(
        user_id INTEGER PRIMARY KEY,
        role TEXT
    )
    """)

    # Run Migrations for V2 explicitly because IF NOT EXISTS doesn't add columns
    try:
        cur.execute("ALTER TABLE users ADD COLUMN vip_until TIMESTAMP")
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'uz'")
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
    except sqlite3.OperationalError: pass
        
    try:
        cur.execute("ALTER TABLE media ADD COLUMN genres TEXT DEFAULT ''")
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE media ADD COLUMN is_vip INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    
    # Run Migrations for V3
    try:
        cur.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN referred_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass

    # Roll-based admin system
    try:
        cur.execute("ALTER TABLE admins ADD COLUMN role TEXT DEFAULT 'admin'")
    except sqlite3.OperationalError: pass

    # Monetization migrations
    try:
        cur.execute("ALTER TABLE media ADD COLUMN access_level TEXT DEFAULT 'free'")
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE force_sub_channels ADD COLUMN expires_at TIMESTAMP")
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE force_sub_channels ADD COLUMN price INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN vip_reminder_sent INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE vouchers ADD COLUMN discount_percent INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE vouchers ADD COLUMN max_uses INTEGER DEFAULT 1")
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE vouchers ADD COLUMN used_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass

    con.commit()
    con.close()
    
    # Run legacy migration if needed
    try:
        migrate_db()
    except Exception as e:
        print("Legacy migration error:", e)

def migrate_db():
    con = connect()
    cur = con.cursor()
    
    cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='movies'")
    if cur.fetchone()[0] == 1:
        cur.execute("SELECT code, file_id, title, views FROM movies")
        old_movies = cur.fetchall()
        for m in old_movies:
            try:
                cur.execute("INSERT INTO media (code, type, title, views, file_id) VALUES (?, ?, ?, ?, ?)",
                            (m[0], 'movie', m[2], m[3], m[1]))
            except sqlite3.IntegrityError:
                pass
        cur.execute("ALTER TABLE movies RENAME TO movies_backup_old")
        
    con.commit()
    con.close()
