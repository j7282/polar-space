import asyncio
from telethon_listener import run_historic_crawl, client

async def run_live_test():
    print(f"🚀 Iniciando Simulador de Servidor Real (Todos los usuarios + Filtro Inteligente)...")
    
    # 1 job_id dummy, enviando username=None hara que escanee para TODOS los usuarios de la DB
    try:
        await run_historic_crawl(job_id=999, username=None, last_msg_id=None, start_count=0)
    except Exception as e:
        print(f"❌ Error en Live Test: {e}")
        
    print("✅ Live Test Finalizado.")
    
if __name__ == "__main__":
    asyncio.run(run_live_test())        
    print("✅ Live Test Finalizado.")
    
if __name__ == "__main__":
    asyncio.run(run_live_test())
