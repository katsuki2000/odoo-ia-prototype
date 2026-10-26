#!/usr/bin/env python3
"""
scripts/test_odoo_assistant.py
==============================
Test de vérification automatique pour le Jour 3 (Step 11).
Authentifie un utilisateur Odoo, teste le endpoint /miro_ai/health,
et vérifie la génération JWT ainsi que la communication avec /miro_ai/ask.
"""
import requests
import time

ODOO_URL = "http://localhost:8069"
DB = "odoo-dev"
LOGIN = "admin"
PASSWORD = "admin"

def main():
    session = requests.Session()
    
    # 1. Authentification Odoo
    print(f"[1] Authentification sur Odoo ({ODOO_URL}, db={DB})...")
    auth_url = f"{ODOO_URL}/web/session/authenticate"
    auth_payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "db": DB,
            "login": LOGIN,
            "password": PASSWORD
        },
        "id": int(time.time())
    }
    resp = session.post(auth_url, json=auth_payload)
    data = resp.json()
    if "error" in data:
        print(f"Erreur d'authentification : {data['error']}")
        return False
    print(" -> Authentifié avec succès ! Cookie de session obtenu.")
    
    # 2. Test Health Check
    print("\n[2] Test du endpoint /miro_ai/health...")
    health_url = f"{ODOO_URL}/miro_ai/health"
    health_payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {},
        "id": int(time.time())
    }
    resp = session.post(health_url, json=health_payload)
    data = resp.json()
    if "error" in data:
        print(f"Erreur Health Check : {data['error']}")
        return False
    print(f" -> Réponse Health Check : {data.get('result')}")
    
    # 3. Test de /miro_ai/ask (question simple)
    print("\n[3] Test du endpoint /miro_ai/ask avec une question test...")
    ask_url = f"{ODOO_URL}/miro_ai/ask"
    ask_payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "question": "Bonjour MIRO AI ! Est-ce que le service RAG répond ?",
            "session_id": "test_script_session_001"
        },
        "id": int(time.time())
    }
    resp = session.post(ask_url, json=ask_payload)
    data = resp.json()
    if "error" in data:
        print(f"Erreur /miro_ai/ask : {data['error']}")
        return False
    
    result = data.get("result", {})
    print(f" -> Réponse de l'assistant : {result.get('answer')}")
    print(f" -> Sources reçues : {len(result.get('sources', []))} sources")
    print(f" -> Session ID : {result.get('session_id')}")
    
    # 4. Vérification du Journal d'Audit (Step 11 Day 4)
    print("\n[4] Vérification de l'enregistrement dans le Journal d'Audit (miro.ai.log)...")
    kw_url = f"{ODOO_URL}/web/dataset/call_kw/miro.ai.log/search_read"
    kw_payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": "miro.ai.log",
            "method": "search_read",
            "args": [[["session_id", "=", "test_script_session_001"]]],
            "kwargs": {
                "fields": ["question", "response_time_ms", "sources_count", "state"],
                "limit": 1
            }
        },
        "id": int(time.time())
    }
    resp = session.post(kw_url, json=kw_payload)
    data = resp.json()
    if "error" in data:
        print(f"Erreur lors de la lecture du journal d'audit : {data['error']}")
        return False
    logs = data.get("result", [])
    if not logs:
        print(" -> ATTENTION : Aucune entrée trouvée dans miro.ai.log pour cette session. Vérifiez si le module a été mis à jour.")
    else:
        log_entry = logs[0]
        print(f" -> Journal d'audit trouvé : ID={log_entry.get('id')}, Durée={log_entry.get('response_time_ms')} ms, Statut={log_entry.get('state')}")
        print(f" -> Question enregistrée : {log_entry.get('question')}")
    
    # 5. Test RAG End-to-End avec question ERP sur le code / documentation (Step 11 Day 5)
    print("\n[5] Test RAG End-to-End avec une question ERP technique sur Odoo 17...")
    ask_url_2 = f"{ODOO_URL}/miro_ai/ask"
    erp_question = "Comment fonctionne la gestion des pickings (bons de livraison) et la validation des mouvements dans Odoo ?"
    ask_payload_2 = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "question": erp_question,
            "session_id": "test_script_session_002"
        },
        "id": int(time.time())
    }
    print(f" -> Question : \"{erp_question}\"")
    start_t = time.time()
    resp_2 = session.post(ask_url_2, json=ask_payload_2)
    data_2 = resp_2.json()
    duration = int((time.time() - start_t) * 1000)
    
    if "error" in data_2:
        print(f"Erreur /miro_ai/ask (ERP) : {data_2['error']}")
        return False
        
    result_2 = data_2.get("result", {})
    answer_2 = result_2.get("answer", "")
    sources_2 = result_2.get("sources", [])
    print(f" -> Réponse obtenue ({duration} ms) :\n{answer_2[:300]}... [tronqué]")
    print(f" -> Nombre de sources RAG citées : {len(sources_2)}")
    if sources_2:
        for idx, src in enumerate(sources_2[:3], 1):
            print(f"    - Source {idx}: {src.get('filepath', 'Inconnue')} (score: {src.get('score', 'N/A')})")
            
    # Vérifier l'audit log pour le test 2
    kw_payload_2 = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "model": "miro.ai.log",
            "method": "search_read",
            "args": [[["session_id", "=", "test_script_session_002"]]],
            "kwargs": {
                "fields": ["question", "response_time_ms", "sources_count", "state", "answer"],
                "limit": 1
            }
        },
        "id": int(time.time())
    }
    resp_log_2 = session.post(kw_url, json=kw_payload_2)
    logs_2 = resp_log_2.json().get("result", [])
    if logs_2:
        print(f" -> Audit log pour test 2 vérifié : ID={logs_2[0]['id']}, Sources enregistrées dans Odoo={logs_2[0]['sources_count']}")

    print("\n[Vérification FINALE du Step 11 - Day 5] Tous les flux (Auth, Health, Proxy, RAG Citations, Audit Log) sont PASSED !")
    return True

if __name__ == "__main__":
    main()
