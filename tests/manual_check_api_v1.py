"""Manual latency and success check of /api/v1/ask over ten independent questions.

Run from the project root with the API already started:
    python -m tests.manual_check_api_v1
Needs JWT_SECRET (the API's value) and ODOO_DB in .env.
"""
import sys
import time

import jwt
import requests

from config.settings import API_HOST, API_PORT, JWT_SECRET, ODOO_DB

BASE_URL = f"http://{API_HOST}:{API_PORT}"

secret = JWT_SECRET
if not secret or not ODOO_DB:
    sys.exit("JWT_SECRET and ODOO_DB must be set in .env.")
token = jwt.encode(
    {"uid": 2, "groups": ["base.group_user"], "company_id": 1, "db": ODOO_DB}, secret, algorithm="HS256")
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

questions = [
    "How to create a new user?",
    "How many sales did Société Dupont make?",
    "What is the status of command CMD-001?",
    "How many support tickets are open?",
    "What products are out of stock?",
    "Show me the sales for 2024.",
    "Can you find the client 'Rakoto'?",
    "What is the procedure for validation?",
    "Who is responsible for the stock?",
    "Total amount of invoices?"
]

# Server should already be running

# Wait for server to boot
print("Waiting for server to boot...")
for _ in range(30):
    try:
        requests.get(f"{BASE_URL}/api/v1/health")
        break
    except:
        time.sleep(1)
else:
    print("Server failed to boot in 30s")
    exit(1)

print("Starting API test...")
successes = 0

for q in questions:
    payload = {
        "question": q,
        "session_id": "test_session",
        "company_id": 1,
    }
    try:
        t0 = time.time()
        resp = requests.post(f"{BASE_URL}/api/v1/ask", json=payload, headers=headers)
        dt = time.time() - t0
        if resp.status_code == 200:
            print(f"[OK] {dt:.2f}s | {q[:30]}... -> {resp.json()['answer'][:30]}...")
            successes += 1
        else:
            print(f"[ERROR] {resp.status_code} | {q[:30]}... -> {resp.text}")
    except Exception as e:
        print(f"[FAILED] {q[:30]}... -> {e}")

print(f"Test completed. {successes}/{len(questions)} passed.")
