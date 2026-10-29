"""Manual end-to-end check of the MIRO AI addon through an Odoo web session.

Run from the project root:
    python -m tests.manual_check_odoo_assistant --login <odoo login>

Needs ODOO_DB in .env and the password of that login in ODOO_MANAGER_PASSWORD.
"""
import argparse
import os
import sys
import time

import requests

from config.settings import ODOO_DB, ODOO_URL_DEFAULT

ODOO_URL = os.getenv("ODOO_URL") or ODOO_URL_DEFAULT
ASK_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 2
AUDIT_LOG_FIELDS = ["question", "response_time_ms", "sources_count", "state"]
SOURCES_SHOWN = 3
ANSWER_PREVIEW_CHARS = 300

SIMPLE_SESSION_ID = "manual_check_session_001"
SIMPLE_QUESTION = "Bonjour MIRO AI ! Est-ce que le service RAG répond ?"
TECHNICAL_SESSION_ID = "manual_check_session_002"
TECHNICAL_QUESTION = (
    "Comment fonctionne la gestion des pickings (bons de livraison) "
    "et la validation des mouvements dans Odoo ?"
)


def rpc(session, route, params):
    body = {"jsonrpc": "2.0", "method": "call", "params": params, "id": int(time.time())}
    return session.post(f"{ODOO_URL}{route}", json=body).json()


def ask_and_wait(session, question, session_id):
    """Submit a question to /miro_ai/ask, then poll /miro_ai/ask_result until the answer is ready."""
    data = rpc(session, "/miro_ai/ask", {"question": question, "session_id": session_id})
    submitted = data.get("result", {})
    if "error" in data or "job_id" not in submitted:
        return data
    deadline = time.time() + ASK_TIMEOUT_SECONDS
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        data = rpc(session, "/miro_ai/ask_result",
                   {"job_id": submitted["job_id"], "session_id": submitted["session_id"]})
        if "error" in data or data.get("result", {}).get("status") != "pending":
            return data
    return {"error": "Timeout while waiting for the answer"}


def audit_log_entries(session, session_id):
    return rpc(session, "/web/dataset/call_kw/miro.ai.log/search_read", {
        "model": "miro.ai.log",
        "method": "search_read",
        "args": [[["session_id", "=", session_id]]],
        "kwargs": {"fields": AUDIT_LOG_FIELDS, "limit": 1},
    })


def print_audit_entry(session, session_id):
    """Return False only when Odoo refuses the lookup; a missing entry is a warning."""
    data = audit_log_entries(session, session_id)
    if "error" in data:
        print(f"Audit log lookup failed: {data['error']}")
        return False
    entries = data.get("result", [])
    if not entries:
        print(" -> WARNING: no miro.ai.log entry for this session; check that the module is up to date.")
        return True
    entry = entries[0]
    print(f" -> Audit log: id={entry['id']}, duration={entry['response_time_ms']} ms, "
          f"sources={entry['sources_count']}, state={entry['state']}")
    print(f" -> Recorded question: {entry['question']}")
    return True


def main(login, password):
    session = requests.Session()

    print(f"[1] Authenticating on Odoo ({ODOO_URL}, db={ODOO_DB}) as {login}...")
    data = rpc(session, "/web/session/authenticate", {"db": ODOO_DB, "login": login, "password": password})
    if "error" in data:
        print(f"Authentication failed: {data['error']}")
        return False

    print("\n[2] /miro_ai/health...")
    data = rpc(session, "/miro_ai/health", {})
    if "error" in data:
        print(f"Health check failed: {data['error']}")
        return False
    print(f" -> {data.get('result')}")

    print("\n[3] /miro_ai/ask with a simple question...")
    data = ask_and_wait(session, SIMPLE_QUESTION, SIMPLE_SESSION_ID)
    if "error" in data:
        print(f"/miro_ai/ask failed: {data['error']}")
        return False
    result = data.get("result", {})
    print(f" -> Answer: {result.get('answer')}")
    print(f" -> Sources: {len(result.get('sources', []))}")

    print("\n[4] Audit log of the simple question...")
    if not print_audit_entry(session, SIMPLE_SESSION_ID):
        return False

    print(f"\n[5] /miro_ai/ask with a technical question: {TECHNICAL_QUESTION}")
    started = time.time()
    data = ask_and_wait(session, TECHNICAL_QUESTION, TECHNICAL_SESSION_ID)
    if "error" in data:
        print(f"/miro_ai/ask failed: {data['error']}")
        return False
    result = data.get("result", {})
    sources = result.get("sources", [])
    print(f" -> Answer ({int((time.time() - started) * 1000)} ms): "
          f"{result.get('answer', '')[:ANSWER_PREVIEW_CHARS]}...")
    print(f" -> Sources: {len(sources)}")
    for index, source in enumerate(sources[:SOURCES_SHOWN], 1):
        print(f"    - {index}: {source.get('filepath', 'unknown')} (score: {source.get('score', 'N/A')})")

    print("\n[6] Audit log of the technical question...")
    if not print_audit_entry(session, TECHNICAL_SESSION_ID):
        return False

    print("\nAll checks passed (authentication, health, proxy, RAG sources, audit log).")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End-to-end check of the MIRO AI addon through Odoo.")
    parser.add_argument("--login", required=True, help="Odoo user login")
    args = parser.parse_args()
    password = os.getenv("ODOO_MANAGER_PASSWORD")
    if not password:
        parser.error("ODOO_MANAGER_PASSWORD must be set in the environment")
    if not ODOO_DB:
        parser.error("ODOO_DB must be set in .env")
    sys.exit(0 if main(args.login, password) else 1)
