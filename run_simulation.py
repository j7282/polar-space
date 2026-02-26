import os
import sys
import time
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

import telethon_listener as tl
import server

# 1. Configurar un archivo falso de ASTERA
dummy_path = os.path.join(BASE_DIR, "incoming_targets", "SIMULACION_ASTERA_RENDER.txt")
os.makedirs(os.path.dirname(dummy_path), exist_ok=True)
with open(dummy_path, "w", encoding="utf-8") as f:
    f.write("target1@simulation.com:Pass123\ntarget2@simulation.com:Pass456")

# 2. Obtener TODOS los usuarios registrados en la base de datos de Render
usuarios = []
try:
    conn = server.get_db_conn()
    c = conn.cursor()
    c.execute(server.q("SELECT id, telegram_chat_id, saved_senders FROM users WHERE telegram_chat_id IS NOT NULL AND telegram_chat_id != '' AND saved_senders IS NOT NULL AND saved_senders != ''"))
    usuarios = c.fetchall()
    conn.close()
    print(f"✅ Se encontraron {len(usuarios)} usuarios configurados en la BD.")
except Exception as e:
    print(f"❌ Error leyendo DB: {e}")

def mock_run_audit(q, email, password, multi_user=False, hit_buffer=None, target_user_filter=None):
    if multi_user and hit_buffer is not None:
        print(f"   [DAEMON SIMULADO] Escaneando {email}...")
        
        # Generar un HIT falso para cada usuario de la BD usando su propia configuración
        for idx, usr in enumerate(usuarios):
            chat_id = usr[1]
            # Sacar la primera palabra clave del usuario para que se vea real
            senders = [s.strip() for s in usr[2].split(',')]
            target_match = senders[0] if senders else "Objetivo Especial"
            
            print(f"   🎯 ¡HIT ENCONTRADO! Para usuario {chat_id} -> {target_match}")
            hit_buffer.append({
                'email': email,
                'pass': password,
                'match': target_match + " (Simulación Render)",
                'total': 10 + (idx * 5),
                'country': 'US',
                'chat_id': chat_id
            })

print("=====================================================")
print("🔥 INICIANDO SIMULACIÓN DE FUEGO EN RENDER 🔥")
print("=====================================================")

with patch('server.run_audit', side_effect=mock_run_audit):
    original_run_audit = server.run_audit
    server.run_audit = mock_run_audit
    try:
        tl.process_file_and_scan(dummy_path)
    finally:
        server.run_audit = original_run_audit

print("=====================================================")
print("✅ SIMULACIÓN RENDER COMPLETADA.")
