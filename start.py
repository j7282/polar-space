import os
import sys
import threading
import time
import subprocess

def run_flask():
    print("▶ Iniciando Servidor Web (Dashboard)...", flush=True)
    try:
        subprocess.run([sys.executable, "server.py"], check=True)
    except Exception as e:
        print(f"❌ CRÍTICO: server.py falló con error: {e}", flush=True)

def run_telethon():
    print("▶ Iniciando Escáner 24/7 de Telegram (background)...", flush=True)
    time.sleep(3)
    try:
        subprocess.run([sys.executable, "telethon_listener.py"], check=True)
    except Exception as e:
        print(f"❌ CRÍTICO: telethon_listener.py falló con error: {e}", flush=True)

if __name__ == "__main__":
    print("==================================================", flush=True)
    print("  🚀 ARRANCANDO SISTEMA DUAL EN RENDER", flush=True)
    print("==================================================", flush=True)
    
    t = threading.Thread(target=run_telethon, daemon=True)
    t.start()
    
    run_flask()
