import os, json, requests
from dotenv import load_dotenv
load_dotenv("/home/user/odoo-ia-prototype/.env")

ODOO_URL = os.getenv("ODOO_URL", "http://localhost:8069")
ODOO_DB = os.getenv("ODOO_DB", "odoo-dev")
ODOO_PW = os.getenv("ODOO_ADMIN_PASSWORD")

s = requests.Session()

auth_resp = s.post(
    f"{ODOO_URL}/web/session/authenticate",
    json={
        "jsonrpc": "2.0",
        "method": "call",
        "params": {"db": ODOO_DB, "login": "admin", "password": ODOO_PW},
    },
    timeout=15,
)
auth_data = auth_resp.json()
uid = auth_data.get("result", {}).get("uid")
print("Odoo session authenticated, uid =", uid)
assert uid, f"auth failed: {auth_data}"

payload = {
    "jsonrpc": "2.0",
    "method": "call",
    "params": {
        "question": "Qui a le droit de voir ceci ?",
        "session_id": "e2e_h2b_test_session",
        "active_model": "sale.order",
        "active_id": 20,
    },
}
r = s.post(f"{ODOO_URL}/miro_ai/ask", json=payload, timeout=90)
print("HTTP status:", r.status_code)
data = r.json()
if "error" in data:
    print("JSON-RPC ERROR:", json.dumps(data["error"], indent=2)[:2000])
else:
    result = data["result"]
    print("route:", result.get("route"))
    print("confidence:", result.get("confidence"))
    print("resolved_concept:", result.get("resolved_concept"))
    print("investigation_plan:", json.dumps(result.get("investigation_plan"), indent=2)[:1500] if result.get("investigation_plan") else None)
    print("--- answer (first 1200 chars) ---")
    print((result.get("answer") or "")[:1200])

with open("/tmp/h2b_e2e_result.json", "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
