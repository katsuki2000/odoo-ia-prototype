"""Rejeu jetable (section 1522) : 5 questions, code courant, une trace lue par question."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.graph.graph import query_graph

TRACE = ROOT / "captures" / "reasoning_trace.jsonl"
QUESTIONS = [
    "comment voir les ventes réalisées ?",
    "c'est quoi le protocole pour les ventes ?",
    "comment une demande d'achat ?",
    "qui approuve les congés dans l'ERP ?",
    "comment je fais pour créer une facture ?",
]


def newRecords(offset):
    with open(TRACE, encoding="utf-8") as f:
        f.seek(offset)
        return [json.loads(line) for line in f if line.strip()], f.tell()


def describe(records):
    hops = [r for r in records if r.get("record_type") == "HOP"]
    summary = next((r for r in records if r.get("record_type") == "SUMMARY"), {})
    tools = [f"{h['tool_name']}(model={h['tool_args'].get('model') or h['tool_args'].get('model_name') or ''})" for h in hops]
    return tools, summary


offset = TRACE.stat().st_size if TRACE.exists() else 0
rows = []
for question in QUESTIONS:
    started = time.perf_counter()
    response = query_graph(question=question, chat_history=[], user_groups=[], language="fr")
    elapsed = time.perf_counter() - started
    records, offset = newRecords(offset)
    tools, summary = describe(records)
    rows.append((question, elapsed, tools, summary.get("fallback_reason"), summary.get("final_message_preview")))
    print(f"\n{'=' * 78}\n{question} ({elapsed:.0f}s)\n{'=' * 78}\n{response.answer}\n", flush=True)
    print(f"[OUTILS] {tools}\n[REPLI] {summary.get('fallback_reason')}", flush=True)

print(f"\n{'#' * 78}\nBILAN\n{'#' * 78}", flush=True)
for question, elapsed, tools, fallback, _ in rows:
    print(f"{question} | {elapsed:.0f}s | repli={fallback} | {tools}", flush=True)
