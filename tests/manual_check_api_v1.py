import os
import time
import requests
import jwt

# Generate a valid JWT token
secret = os.getenv("JWT_SECRET", "default_insecure_secret_for_dev")
token = jwt.encode({"uid": 2, "groups": ["base.group_user"], "company_id": 1}, secret, algorithm="HS256")
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
        requests.get("http://127.0.0.1:8000/api/v1/health")
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
        "user_uid": 2,
        "company_id": 1,
        "skills": {}
    }
    try:
        t0 = time.time()
        resp = requests.post("http://127.0.0.1:8000/api/v1/ask", json=payload, headers=headers)
        dt = time.time() - t0
        if resp.status_code == 200:
            print(f"[OK] {dt:.2f}s | {q[:30]}... -> {resp.json()['answer'][:30]}...")
            successes += 1
        else:
            print(f"[ERROR] {resp.status_code} | {q[:30]}... -> {resp.text}")
    except Exception as e:
        print(f"[FAILED] {q[:30]}... -> {e}")

print(f"Test completed. {successes}/{len(questions)} passed.")
