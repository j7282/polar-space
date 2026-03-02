import os
import sys

try:
    import psycopg2
except ImportError:
    print("❌ Por favor instala psycopg2 primero: pip install psycopg2-binary")
    sys.exit(1)

# Prompt for DATABASE_URL if not in env
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    print("⚠️ No se detectó DATABASE_URL en el entorno.")
    db_url = input("Ingresa la URL de la base de datos de Render (Ej. postgresql://...): ").strip()
    if not db_url:
        print("Operación cancelada.")
        sys.exit(1)

username = input("\n👤 Ingresa el username exacto en la web al que deseas dar poder de Super Administrador (Ej. jerry7822): ").strip()

try:
    print("\n🔄 Conectando a la base de datos principal en Render...")
    conn = psycopg2.connect(db_url, connect_timeout=15)
    cur = conn.cursor()
    
    # 1. Check if user exists
    cur.execute("SELECT id, telegram_chat_id FROM users WHERE username = %s", (username,))
    user = cur.fetchone()
    
    if not user:
        print(f"❌ Error: El usuario '{username}' no existe en la base de datos.")
    else:
        if not user[1]:
            print(f"⚠️ Advertencia: El usuario '{username}' existe, pero no ha vinculado su cuenta de Telegram en la web.")
            print("   Los reportes de Groq podrían no llegar si no hay un Chat ID registrado.")
            
        # 2. Update privileges
        cur.execute("UPDATE users SET is_superadmin = 1 WHERE username = %s", (username,))
        conn.commit()
        print(f"✅ ¡ÉXITO! El usuario '{username}' ha sido ascendido a Súper Administrador.")
        
    conn.close()
except psycopg2.Error as e:
    print(f"\n❌ Falló la actualización en la BD. Detalles: {e}")
except Exception as e:
    print(f"\n❌ Error catastrófico: {e}")
