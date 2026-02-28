import os
import sys

# Setup environment for test
os.environ["GEMINI_API_KEY"] = "AIzaSyDqns01kwTrg6pIIbD6n_S0WKaXrrvt9vk"

import telethon_listener as tl

print("Iniciando prueba local sobre el último archivo HOTMAIL HQ...")
last_file = "incoming_targets/hq_1028_HOTMAIL HQ.txt"

if not os.path.exists(last_file):
    print(f"File not found: {last_file}")
    sys.exit(1)

# Execute the pipeline
try:
    tl.process_file_and_scan(last_file, target_user_filter="admin") # Using admin to limit DB queries
    print("✅ Pipeline ejecutado.")
except Exception as e:
    print(f"❌ Pipeline falló: {e}")
