import base64
import os
import sys

print("==========================================================================")
print("🔑 GENERADOR DE SESIÓN INMORTAL PARA TELEGRAM (RENDER)")
print("==========================================================================\n")

print("Este script leerá tu archivo 'polar_bot.session' local (que ya autorizaste con tu número)")
print("y lo convertirá en un mega-texto que puedes poner en Render para que el bot nunca se desconecte.\n")

session_file = "polar_bot.session"

if not os.path.exists(session_file):
    print(f"❌ ¡ERROR! No encuentro el archivo '{session_file}'.")
    print("👉 Asegúrate de haber ejecutado 'python3 telethon_listener.py' localmente y haber")
    print("   iniciado sesión con tu número de teléfono y código SMS al menos una vez para")
    print("   que se cree este archivo.\n")
    sys.exit(1)

try:
    with open(session_file, "rb") as f:
        sess_data = f.read()
    
    # Prefix it so it looks clean
    b64_str = base64.b64encode(sess_data).decode('utf-8')
    
    print("✅ ¡Éxito! Copia EXACTAMENTE el texto largo de abajo (sin espacios en blanco ni comillas)")
    print("y ponlo en tu servidor de Render como una Environment Variable:\n")
    print("  Key:   SESSION_B64")
    print("  Value: (pega el código de abajo)\n")
    print("👇👇👇👇👇👇👇👇👇👇👇👇👇 CÓPIA A PARTIR DE ABAJO 👇👇👇👇👇👇👇👇👇👇👇👇👇")
    print(b64_str)
    print("👆👆👆👆👆👆👆👆👆👆👆👆👆 HASTA LA LÍNEA DE ARRIBA 👆👆👆👆👆👆👆👆👆👆👆👆👆\n")
    
except Exception as e:
    print(f"Error procesando la sesión: {e}")
