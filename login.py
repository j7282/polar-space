import asyncio
from telethon import TelegramClient

API_ID = 23099503
API_HASH = "5980c7a831a590bd1e3b58648ce1e1e2"
SESSION_NAME = "polar_bot"

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()
    print("\n✅ ¡Sesión interactiva iniciada y guardada correctamente en polar_bot.session!")

if __name__ == '__main__':
    asyncio.run(main())
