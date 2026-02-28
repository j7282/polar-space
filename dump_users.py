import os
import sys

# Agregamos la ruta local para importar server.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

import server

print("--- EXTRACCIÓN DE USUARIOS Y CONTRASEÑAS ---")
try:
    conn = server.get_db_conn()
    c = conn.cursor()
    # Obtenemos TODOS los campos sin censura
    c.execute(server.q("SELECT id, username, password_hash, telegram_chat_id FROM users"))
    usuarios = c.fetchall()
    
    if not usuarios:
        print("La base de datos está vacía. No hay usuarios.")
    else:
        for u in usuarios:
            print(f"ID: {u[0]} | Usuario: {u[1]} | Contraseña: {u[2]} | Telegram ID: {u[3]}")
    conn.close()
except Exception as e:
    print(f"Error conectando a la BD: {e}")
