import os
import requests
import jwt

secret = os.getenv("JWT_SECRET", "default_insecure_secret_for_dev")
token = jwt.encode({"uid": 2, "groups": ["base.group_user"], "company_id": 1}, secret, algorithm="HS256")
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

QUESTIONS = [
    {
        "id": "automation_traps (custom, Bloc9)",
        "question": "Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?",
    },
    {
        "id": "PR-Q1 (OCA purchase_request)",
        "question": "Qui a le droit de modifier une demande d'achat (purchase.request), et sous quelles conditions ?",
    },
    {
        "id": "AN-Q1 (OCA animal)",
        "question": "Existe-t-il des ir.rule (Record Rules) sur le modele animal, ou seulement des ACL ?",
    },
    {
        "id": "BTV-Q1 (OCA base_tier_validation)",
        "question": "Qui peut valider (approve) un enregistrement soumis a tier.validation, et ou est-ce configure ?",
    },
]

for q in QUESTIONS:
    payload = {
        "question": q["question"],
        "session_id": "replay_section730",
        "user_uid": 2,
        "company_id": 1,
        "skills": {},
    }
    print("=" * 100)
    print(q["id"], "|", q["question"])
    try:
        resp = requests.post("http://127.0.0.1:8000/api/v1/ask", json=payload, headers=headers, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            print("route:", data.get("route"), "| confidence:", data.get("confidence"))
            print("answer:", data.get("answer"))
        else:
            print(f"[HTTP {resp.status_code}]", resp.text[:2000])
    except Exception as e:
        print("[FAILED]", e)
