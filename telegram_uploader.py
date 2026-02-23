#!/usr/bin/env python3
import requests
import time
import os
import sys

# ══════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN = "8741495811:AAEOFBaW9QfFOpVWfW6kyogJskS7y4wVTIs"

def send_telegram_message(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200, res.text
    except Exception as e:
        return False, str(e)

def chunk_list(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def main():
    print("══════════════════════════════════════════════════")
    print("  🤖 TELEGRAM BULK UPLOADER")
    print("══════════════════════════════════════════════════")
    
    # 1. Get Target Chat ID
    chat_id = os.environ.get("TARGET_CHAT_ID", "").strip()
    if not chat_id:
        print("[!] Error: TARGET_CHAT_ID env var no configurada")
        return

    # 2. Get File Path
    file_path = os.environ.get("TARGET_FILE", "hits.txt").strip()
    if not os.path.isfile(file_path):
        print(f"[!] Error: No se encontró el archivo '{file_path}'.")
        return

    # 3. Read and Parse List
    print("\nLeyendo archivo...")
    valid_items = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            item = line.strip()
            if item and not item.startswith("#"):
                valid_items.append(item)

    if not valid_items:
        print("[!] Error: El archivo está vacío o no tiene texto válido.")
        sys.exit(1)

    print(f"✅ Se encontraron {len(valid_items)} correos/registros.")
    print("Iniciando subida en bloques de 30 para evitar Rate Limiting...\n")

    # 4. Process Chunks
    # Max length of Telegram msg is 4096. 30 emails fits comfortably.
    chunks = list(chunk_list(valid_items, 30))
    
    total_chunks = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        # Format the message
        message = f"📦 *Lote {i}/{total_chunks}*\n"
        message += "```text\n"
        for item in chunk:
            message += f"{item}\n"
        message += "```"
        
        print(f"⏳ Subiendo lote {i}/{total_chunks} ({len(chunk)} registros)... ", end="", flush=True)
        
        success, response = send_telegram_message(chat_id, message)
        
        if success:
            print("✅ OK")
        else:
            print(f"❌ FALLÓ: {response}")
            
        # Sleep to avoid "429 Too Many Requests"
        if i < total_chunks:
            time.sleep(2.5)

    print("\n══════════════════════════════════════════════════")
    print(" 🎉 PROCESO COMPLETADO")
    print("══════════════════════════════════════════════════")

if __name__ == "__main__":
    main()
