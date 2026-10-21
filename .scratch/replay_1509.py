"""Rejeu jetable (section 1509) : les deux questions du chat MIRO AI, nouveau processus = code courant."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage, HumanMessage

from core.graph.graph import query_graph

QUESTIONS = [
    "quelles sont les etapes à suivre pour faire une demande d'achat?",
    "et qui peut approuver les demandes de mise à disposition?",
]

history = []
for index, question in enumerate(QUESTIONS, 1):
    started = time.perf_counter()
    response = query_graph(question=question, chat_history=history, user_groups=[], language="fr")
    elapsed = time.perf_counter() - started
    answer = response.answer
    print(f"\n{'=' * 78}\nQUESTION {index} ({elapsed:.0f}s) : {question}\n{'=' * 78}\n{answer}\n")
    print(f"[CONTROLE] bloc FAIT DETERMINISTIQUE present : {'FAIT DÉTERMINISTIQUE' in answer or 'FAIT DETERMINISTIQUE' in answer}")
    print(f"[CONTROLE] 'Precision d'heritage' present    : {'Précision d' in answer}")
    print(f"[CONTROLE] route={getattr(response, 'route', None)} ; sources={len(getattr(response, 'sources', []) or [])}", flush=True)
    history = history + [HumanMessage(content=question), AIMessage(content=answer)]
