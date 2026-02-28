import os
import sys
import asyncio
from telethon import TelegramClient

# Ensure we can import telethon_listener
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import telethon_listener as tl

TARGET_GROUP = "ASTERA"
client = TelegramClient(tl.SESSION_NAME, tl.API_ID, tl.API_HASH)

async def main():
    print("Conectando a Telegram...")
    await client.connect()
    if not await client.is_user_authorized():
        print("❌ Sesión local expirada o no autorizada.")
        return

    print(f"Buscando el grupo '{TARGET_GROUP}' en tus chats...")
    target_chat = None
    async for dialog in client.iter_dialogs():
        if TARGET_GROUP.lower() in dialog.name.lower():
            target_chat = dialog.entity
            print(f"✅ Grupo encontrado: {dialog.name}")
            break
            
    if not target_chat:
        print(f"❌ Grupo '{TARGET_GROUP}' no encontrado.")
        return
        
    print("Buscando el último archivo enviado en el historial...")
    # Buscamos en los últimos 50 mensajes el primer documento/archivo
    async for msg in client.iter_messages(target_chat, limit=50):
        if msg.document or msg.file:
            fname = getattr(msg.file, 'name', '') or 'list.txt'
            print(f"📥 Último archivo detectado: {fname}")
            
            # Descargamos el archivo
            local_path = os.path.join(tl.DOWNLOAD_DIR, f"live_test_{fname}")
            print(f"Descargando archivo a {local_path}...")
            actual_path = await client.download_media(msg.message, file=local_path)
            
            if not actual_path:
                print("⚠️ Telethon no pudo descargar este archivo, probando el anterior...")
                continue
                
            print(f"✅ Descarga completa: {actual_path}. Enviando al motor de escaneo...")
            
            # Inject API Key for test
            os.environ["GEMINI_API_KEY"] = "AIzaSyDqns01kwTrg6pIIbD6n_S0WKaXrrvt9vk"
            
            try:
                # Ejecutar el proceso normal que usaría el bot 24/7
                tl.process_file_and_scan(actual_path)
            except Exception as e:
                print(f"Error procesando archivo: {e}")
                
            break
    else:
        print("❌ No se encontraron archivos recientes en los últimos 50 mensajes.")

if __name__ == '__main__':
    asyncio.run(main())
