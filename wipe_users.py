import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

import server

print("--- BORRADO FORZADO DE BASE DE DATOS ---")
try:
    conn = server.get_db_conn()
    c = conn.cursor()
    c.execute("DELETE FROM users")
    conn.commit()
    print("✅ Todos los usuarios han sido eliminados del sistema Render satisfactoriamente.")
    conn.close()
except Exception as e:
    print(f"❌ Error borrando BD: {e}")
