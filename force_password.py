import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

import server
from werkzeug.security import generate_password_hash

print("--- RESETEANDO CONTRASEÑA ---")
try:
    conn = server.get_db_conn()
    c = conn.cursor()
    
    # El usuario se llama jerry7822jerry7822 según lo que vimos en el registro automático.
    target_user = "jerry7822jerry7822"
    new_pass = "jerry7822"
    hashed_pass = generate_password_hash(new_pass)
    
    c.execute(server.q("UPDATE users SET password_hash = ? WHERE username = ?"), (hashed_pass, target_user))
    
    # Por si también creó el usuario "jerry7822" normal
    c.execute(server.q("UPDATE users SET password_hash = ? WHERE username = ?"), (hashed_pass, "jerry7822"))
    
    conn.commit()
    print(f"✅ Contraseña cambiada exitosamente a '{new_pass}' para los usuarios que empiezan con jerry7822.")
    conn.close()
except Exception as e:
    print(f"❌ Error actualizando BD: {e}")
