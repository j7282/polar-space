import os
import time
import json
import logging
from telethon_listener import send_consolidated_report

print("🧪 Generando reporte de prueba con el nuevo formato de columnas...")

# MOCK DATA simulating 3 hits found by the drill-down logic
mock_hits = [
    {
        "user": "jerry7822",
        "match": "NETFLIX 🎬",
        "email": "juan.perez@hotmail.com",
        "pass": "NetflixPass123!",
        "country": "MX",
        "name": "Juan Perez",
        "total": 14,
        "query": "from:info@mailer.netflix.com",
        "chat_id": 123456789  # Fake ID so it doesn't actually send to Telegram during the test, only writes the TXT
    },
    {
        "user": "jerry7822",
        "match": "PAYPAL 💰",
        "email": "maria_lopez99@outlook.com",
        "pass": "marialopez99",
        "country": "CO",
        "name": "Maria Lopez",
        "total": 3,
        "query": "from:service@intl.paypal.com",
        "chat_id": 123456789
    },
    {
        "user": "jerry7822",
        "match": "accesoads10@gmail.com",
        "email": "admin_empresa@hotmail.com",
        "pass": "AdminCorp2025*",
        "country": "US",
        "name": "Empresa Admin",
        "total": 1,
        "query": "from:accesoads10@gmail.com",
        "chat_id": 123456789
    }
]

# Ensure directory exists
os.makedirs("incoming_targets", exist_ok=True)

# Temporarily mock requests to avoid actual Telegram spam during the local test write
import requests
original_post = requests.post
requests.post = lambda url, **kwargs: print(f"📞 [MOCK] Telegram API called with summary:\n{kwargs.get('json', {}).get('text')}")

try:
    send_consolidated_report(mock_hits)
    print("\n✅ Archivo .txt generado con éxito en incoming_targets/")
finally:
    requests.post = original_post
