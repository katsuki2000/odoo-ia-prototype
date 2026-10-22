"""Rejeu jetable (section 1526) : une question, avertissements des outils captures dans un fichier."""
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
logging.basicConfig(filename=str(ROOT / ".scratch" / "replay_1526.warnings.log"), level=logging.WARNING,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

from core.graph.graph import query_graph

TRACE = ROOT / "captures" / "reasoning_trace.jsonl"
QUESTION = "comment faire une demande d'achat ?"

offset = TRACE.stat().st_size
started = time.perf_counter()
response = query_graph(question=QUESTION, chat_history=[], user_groups=[], language="fr")
print(f"{QUESTION} ({time.perf_counter() - started:.0f}s)\n{response.answer}\n", flush=True)
with open(TRACE, encoding="utf-8") as f:
    f.seek(offset)
    for line in f:
        record = json.loads(line)
        if record.get("record_type") == "HOP":
            print("HOP", record["hop_index"], record["tool_name"], json.dumps(record["tool_args"], ensure_ascii=False)[:120], flush=True)
        elif record.get("record_type") == "SUMMARY":
            print("SUMMARY hops", record["hop_count"], "llm", record["llm_call_count"], "repli", record.get("fallback_reason"), flush=True)
            print("APERCU", repr(record.get("final_message_preview")), flush=True)
