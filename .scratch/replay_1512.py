"""Rejeu jetable (section 1512) : « qui approuve les conges dans l'ERP ? », code courant."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.graph.graph import query_graph

QUESTION = "qui approuve les congés dans l’ERP ?"
started = time.perf_counter()
response = query_graph(question=QUESTION, chat_history=[], user_groups=[], language="fr")
elapsed = time.perf_counter() - started
print(f"\n{'=' * 78}\nQUESTION ({elapsed:.0f}s) : {QUESTION}\n{'=' * 78}\n{response.answer}\n")
print(f"[CONTROLE] route={getattr(response, 'route', None)} ; sources={len(getattr(response, 'sources', []) or [])}", flush=True)
