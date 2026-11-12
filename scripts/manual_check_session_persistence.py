"""
Manual check: two successive jobs on /api/v1/ask/jobs with the same session_id,
the second question depending on the first turn.

Unlike manual_check_multi_turn.py (local chat_history, bypasses
session_store.py and the API), this script:

1. Sends a self-contained question.
2. Sends a follow-up that only makes sense if the server reloaded the first
   turn through get_session(session_id).
3. Asserts nothing itself: it prints both answers. Confirm in the server logs
   (INFO/DEBUG) that the second query_graph() call received a non-empty
   chat_history. A plausible answer alone proves nothing: the LLM can guess a
   generic context without any real history.

Prerequisites: the API is already started and JWT_SECRET and ODOO_DB are set in .env.
Run from the project root: python -m scripts.manual_check_session_persistence
"""

import sys
import time
import uuid

import jwt
import requests

from config.settings import API_HOST, API_PORT, JWT_SECRET, ODOO_DB

secret = JWT_SECRET
if not secret or not ODOO_DB:
    sys.exit("JWT_SECRET and ODOO_DB must be set in .env.")
token = jwt.encode(
    {"uid": 2, "groups": ["base.group_user"], "company_id": 1, "db": ODOO_DB},
    secret,
    algorithm="HS256",
)
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

BASE_URL = f"http://{API_HOST}:{API_PORT}"
SESSION_ID = "session_context_check"

# The second question is meaningless without the first ("this year" refers to the sales).
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
        "company_id": 1,
        "source_mode": "system",
    }
    payload["job_id"] = uuid.uuid4().hex
    t0 = time.time()
    resp = requests.post(f"{BASE_URL}/api/v1/ask/jobs", json=payload, headers=headers)
    body = None
    if resp.status_code == 202:
        while True:
            resp = requests.get(f"{BASE_URL}/api/v1/ask/jobs/{payload['job_id']}", headers=headers)
            body = resp.json() if resp.status_code == 200 else None
            if body is None or body["status"] != "pending":
                break
            time.sleep(1)
    dt = time.time() - t0

    print(f"--- Turn {i} ({dt:.2f}s) ---")
    print(f"User : {question}")
    if body is not None and body["status"] == "done":
        print(f"Agent: {body['result']['answer']}\n")
    elif body is not None:
        print(f"[ERROR] {body['error_status']} -> {body['error_detail']}\n")
    else:
        print(f"[ERROR] {resp.status_code} -> {resp.text}\n")

print(
    "Check the server logs: turn 2 must have reached query_graph() with a "
    "non-empty chat_history containing turn 1. A plausible turn-2 answer is "
    "not enough: the LLM can guess a generic context without real history."
)
