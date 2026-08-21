"""
H1b-i (todo/plan.md, section "Preconditions a valider avant P1/P2", H1) --
verification manuelle #2 : deux appels successifs au meme session_id via
/api/v1/ask, la deuxieme question depend du contexte du premier tour.

Contrairement a manual_check_api_v1.py (10 questions independantes, meme
session_id, pense pour mesurer latence/taux de succes -- ne prouve pas que
le contexte est reellement vu), et a manual_check_multi_turn.py (gere son
propre chat_history en local, appelle query_graph() directement -- bypasse
entierement session_store.py et /api/v1/ask), ce script :

1. Envoie une premiere question autonome.
2. Envoie une deuxieme question qui n'a de sens QUE si le serveur a bien
   recharge l'historique du premier tour via get_session(session_id) --
   "Et pour cette annee ?" ne peut etre repondue correctement sans savoir
   de quoi parle "cette annee".
3. N'affirme rien tout seul sur la reussite : imprime les deux reponses et
   demande une lecture des logs serveur (niveau INFO/DEBUG) pour confirmer
   que le deuxieme appel a query_graph() recoit bien chat_history=[HumanMessage(...),
   AIMessage(...)] et non chat_history=[] -- c'est la seule preuve valable
   pour cloturer H1b-i, pas une inspection du texte de la reponse.

Pre-requis : serveur deja lance (voir manual_check_api_v1.py), meme
mecanisme de token JWT.
"""

import os
import time
import requests
import jwt

secret = os.getenv("JWT_SECRET", "default_insecure_secret_for_dev")
token = jwt.encode(
    {"uid": 2, "groups": ["base.group_user"], "company_id": 1},
    secret,
    algorithm="HS256",
)
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

BASE_URL = "http://127.0.0.1:8000"
SESSION_ID = "h1b_i_context_check"

turns = [
    "Combien de ventes la Societe Dupont a-t-elle realisees ?",
    "Et pour cette annee ?",
]

print("Waiting for server to boot...")
for _ in range(30):
    try:
        requests.get(f"{BASE_URL}/api/v1/health")
        break
    except requests.exceptions.ConnectionError:
        time.sleep(1)
else:
    print("Server failed to boot in 30s")
    raise SystemExit(1)

print(f"Using session_id={SESSION_ID!r}\n")

for i, question in enumerate(turns, 1):
    payload = {
        "question": question,
        "session_id": SESSION_ID,
        "user_uid": 2,
        "company_id": 1,
        "skills": {},
    }
    t0 = time.time()
    resp = requests.post(f"{BASE_URL}/api/v1/ask", json=payload, headers=headers)
    dt = time.time() - t0

    print(f"--- Tour {i} ({dt:.2f}s) ---")
    print(f"User : {question}")
    if resp.status_code == 200:
        print(f"Agent: {resp.json()['answer']}\n")
    else:
        print(f"[ERROR] {resp.status_code} -> {resp.text}\n")

print(
    "Verification requise cote logs serveur : confirmer que le tour 2 a "
    "recu un chat_history non vide (contenant le tour 1) dans l'appel a "
    "query_graph(). Un texte de reponse plausible au tour 2 ne suffit pas "
    "a lui seul -- le LLM peut deviner un contexte generique meme sans "
    "historique reel."
)
