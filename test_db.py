import psycopg2

DATABASE_URL = "postgresql://searchgood_db_il0e_user:j0J25UROGJReJIwaijSeGgTtkKGpCphG@dpg-d6hiadsr85hc739g4l7g-a.oregon-postgres.render.com/searchgood_db_il0e"
try:
    print("🔌 Connecting...")
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
    c = conn.cursor()
    print("✅ Connected. Creating table...")
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            telegram_chat_id TEXT,
            saved_senders TEXT,
            allow_247 INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    print("📋 Checking for users...")
    c.execute("select id from users limit 1")
    print("Done. Success")
    conn.close()
except Exception as e:
    print(f"❌ Error: {e}")
