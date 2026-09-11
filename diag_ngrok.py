import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")
import urllib.request, json

url = os.environ["LOCAL_LLM_BASE_URL"].rstrip("/") + "/chat/completions"
model = os.environ.get("LOCAL_LLM_MODEL", "gpt-oss:20b")

req = urllib.request.Request(
    url,
    data=json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}], "stream": False}).encode(),
    headers={"Content-Type": "application/json", "ngrok-skip-browser-warning": "true"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        print("STATUS:", resp.status)
        print("HEADERS:", dict(resp.headers))
        print("BODY (500 premiers car.):", resp.read()[:500])
except urllib.error.HTTPError as e:
    print("STATUS:", e.code)
    print("HEADERS:", dict(e.headers))
    print("BODY (500 premiers car.):", e.read()[:500])