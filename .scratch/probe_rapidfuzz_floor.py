"""Offline probe: what the existing RapidFuzz step (_fuzzy_match_graph) decides alone, with a margin rule.

No server, no LLM, no embeddings. Read-only. Scores against ground truth when the bank has expected_models.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from code_intelligence.agent.matching import _fuzzy_match_graph  # noqa: E402
from code_intelligence.agent.resolution.candidates import AMBIGUITY_GAP_THRESHOLD  # noqa: E402
from code_intelligence.graph import get_code_intelligence_graph  # noqa: E402

BANKS = ["tests/native_n1_question_bank.json", "tests/custom_b9_question_bank.json"]
graph = get_code_intelligence_graph(translation_languages=["fr"], request_language="fr")

rows = []
for bank in BANKS:
    data = json.load(open(ROOT / bank, encoding="utf-8"))
    items = data["questions"] if isinstance(data, dict) else data
    for item in items:
        question = item.get("business_question") or item.get("question")
        if not question:
            continue
        hits = _fuzzy_match_graph(question, graph)
        print("...", item["id"], flush=True)
        rows.append((item["id"], hits, item.get("expected_models")))

def verdict(hits):
    if not hits:
        return "aucun"
    if len(hits) == 1 or hits[0][1] - hits[1][1] >= AMBIGUITY_GAP_THRESHOLD:
        return "tranche"
    return "ambigu"

tally = {"aucun": 0, "tranche": 0, "ambigu": 0}
scored = [r for r in rows if r[2]]
good = bad = 0
for qid, hits, expected in rows:
    v = verdict(hits)
    tally[v] += 1
    if v == "tranche" and expected:
        if hits[0][0] in expected:
            good += 1
        else:
            bad += 1
print(f"{len(rows)} questions ; seuil d'ecart AMBIGUITY_GAP_THRESHOLD={AMBIGUITY_GAP_THRESHOLD}")
print("repartition :", tally)
print(f"verite terrain disponible pour {len(scored)} questions ; tranchees exactes={good} fausses={bad}")
print("top-2 par question (id, verdict, meilleur, second) :")
for qid, hits, _ in rows:
    top = [f"{m} {s:.0f}" for m, s in hits[:2]]
    print(f"  {qid:8} {verdict(hits):8} {' | '.join(top) if top else '-'}")
