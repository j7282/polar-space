import os
import sys
import psycopg2
from werkzeug.security import generate_password_hash

DB_URL = "postgresql://searchgood_db_il0e_user:j0J25UROGJReJIwaijSeGgTtkKGpCphG@dpg-d6hiadsr85hc739g4l7g-a.oregon-postgres.render.com/searchgood_db_il0e"

username = "jerry7822"
pass_raw = "jerry7822"
chat_id = "6705759280"
senders = "noreply@support.whatsapp.com,identification@nespresso.com,latampass@mails.latam.com,deltaairlines@o.delta.com,aeromexico.rewards@aeromexico.com,invexcontrol@invex.com,boletin@invex.com,boletin@invextarjetas.com.mx"

print(f"🌍 Connecting to Remote Render DB: {DB_URL.split('@')[-1]}")

try:
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    c = conn.cursor()
    
    # 1. Ensure table exists (though server should have created it)
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
    
    # 2. Add or Update User
    c.execute("SELECT id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    
    hashed = generate_password_hash(pass_raw)
    
    if row:
        print("👤 User already exists. Updating data...")
        c.execute("""
            UPDATE users 
            SET password_hash = %s, telegram_chat_id = %s, saved_senders = %s
            WHERE username = %s
        """, (hashed, chat_id, senders, username))
    else:
        print("👤 User not found. Inserting new record...")
        c.execute("""
            INSERT INTO users (username, password_hash, telegram_chat_id, saved_senders)
            VALUES (%s, %s, %s, %s)
        """, (username, hashed, chat_id, senders))
        
    print(f"✅ Success! Account '{username}' seeded successfully with 8 targets mapped to {chat_id}")
    
except Exception as e:
    print(f"❌ Critical DB Error: {e}")
finally:
    if 'conn' in locals():
        conn.close()
