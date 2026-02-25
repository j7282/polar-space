import os
import sys
import threading
import time

def run_flask():
    print("▶ Iniciando Servidor Web (Dashboard)...")
    os.system(f"{sys.executable} server.py")

def run_telethon():
    print("▶ Iniciando Escáner 24/7 de Telegram (background)...")
    # Small delay to let Flask bind the port first
    time.sleep(3)
    os.system(f"{sys.executable} telethon_listener.py")

if __name__ == "__main__":
    print("==================================================")
    print("  🚀 ARRANCANDO SISTEMA DUAL EN RENDER")
    print("==================================================")
    
    # Run Telethon in a background thread
    t = threading.Thread(target=run_telethon, daemon=True)
    t.start()
    
    # Run Flask in the main thread so Render knows the service is up (port binding)
    run_flask()
