import sys
import subprocess
print("=== INICIANDO PRUEBA DE DIAGNOSTICO ===", flush=True)

try:
    print("Probando importar libraries...", flush=True)
    import telethon
    import requests
    import flask
    import waitress
    print("✅ Todas las librerias importaron OK", flush=True)
except Exception as e:
    print(f"❌ Error importando librerias: {e}", flush=True)

try:
    print("Probando arrancar server.py por 5 segundos...", flush=True)
    p = subprocess.Popen([sys.executable, "server.py"])
    p.wait(timeout=5)
except subprocess.TimeoutExpired:
    print("✅ server.py arrancó y no crasheó en 5 segundos.", flush=True)
    p.kill()
except Exception as e:
    print(f"❌ Error arrancando server.py: {e}", flush=True)

print("=== FIN DE PRUEBA ===", flush=True)
