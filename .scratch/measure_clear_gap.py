import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from run_bloc_n1_benchmark import build_agent_state, load_questions
from code_intelligence.graph import get_code_intelligence_graph
from code_intelligence.agent.resolution import resolver, fuzzy_lookup
from code_intelligence.agent.resolution.dense_lookup import DenseResolution
from code_intelligence.agent.resolution.matching import _fuzzy_match_graph
from code_intelligence.agent.text_normalization import normalize_query_text
from core.evaluation.expected_models import load_expected_models, classify_resolution

questions, _ = load_questions()
expected, tolerated = load_expected_models()
graphs = {}
def graph(lang):
    if lang not in graphs:
        graphs[lang] = get_code_intelligence_graph(translation_languages=[lang] if lang else None, request_language=lang)
    return graphs[lang]
# dense retrieval unavailable offline: lexical-only comparison, no LLM
resolver.resolve_dense_retrieval = lambda *a, **k: DenseResolution(None, ())
GAP = fuzzy_lookup.AMBIGUITY_GAP_THRESHOLD
rows = []
for q in questions:
    st = build_agent_state(q, False); lang = st.get("language"); G = graph(lang)
    text = st["question"]
    clean = normalize_query_text(text.lower().strip())
    lex = _fuzzy_match_graph(clean, G)
    out = {}
    for name, thr in (("sans", 1e9), ("avec", GAP)):
        fuzzy_lookup.AMBIGUITY_GAP_THRESHOLD = thr
        r = resolver.resolve_business_term(text, G, llm=None, language=lang)
        out[name] = (r.source_step, list(r.resolved_models))
    fuzzy_lookup.AMBIGUITY_GAP_THRESHOLD = GAP
    gap = (lex[0][1] - lex[1][1]) if len(lex) > 1 else (None if not lex else 999)
    rows.append({"id": q["id"], "bank": q["bank"], "lex_top3": [(m, round(s, 1)) for m, s in lex[:3]], "gap": gap,
                 "sans": out["sans"], "avec": out["avec"]})
json.dump(rows, open(ROOT / ".scratch/clear_gap_measure.json", "w"), ensure_ascii=False, indent=1)
tot = len(rows)
chg = [r for r in rows if r["sans"] != r["avec"]]
print("questions:", tot, "| resultat different avec clear_gap (llm=None, sans dense):", len(chg))
for r in chg:
    exp = expected.get(r["id"]); tol = tolerated.get(r["id"], frozenset())
    note = ""
    if exp: note = "avec=" + classify_resolution(r["avec"][1], exp, tol)
    print(r["id"], r["bank"], "gap=", r["gap"], "| sans:", r["sans"][0], r["sans"][1][:3], "| avec:", r["avec"][0], r["avec"][1][:3], note)
