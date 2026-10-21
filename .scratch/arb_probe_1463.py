#!/usr/bin/env python3
"""Sonde jetable (lecture seule) : variance de l'arbitre, liste dense a 10 vs 20.
Usage (long, ~40 min pour k=5) :
  cd /media/donnee/projets/odoo-ia-prototype
  .venv/bin/python3 .scratch/arb_probe_1463.py            # k=5, 12 questions, reprenable (Ctrl-C ok)
  .venv/bin/python3 .scratch/arb_probe_1463.py --k 3
  .venv/bin/python3 .scratch/arb_probe_1463.py --dry CNA-Q1   # liste seulement, sans LLM
  .venv/bin/python3 .scratch/arb_probe_1463.py --summary      # relit le .jsonl et resume
"""
import argparse, collections, json, sys
from pathlib import Path
ROOT = Path("/media/donnee/projets/odoo-ia-prototype")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / ".scratch" / "arb_probe_1463.jsonl"
QIDS = ["CNA-Q1", "CNA-Q2", "AUT-Q1", "HRL-Q1", "HRL-Q2", "STK-Q1", "STK-Q2", "STK-Q5", "REI-Q2", "SAL-Q3", "ACC-Q2", "PUR-Q1"]
EXPECTED = {"CNA-Q1": {"account.move"}, "AUT-Q1": {"account.move"}, "HRL-Q1": {"hr.leave"}, "HRL-Q2": {"hr.leave"},
            "STK-Q1": {"stock.quant"}, "STK-Q5": {"stock.quant"}, "PUR-Q1": {"purchase.order"}, "CNA-Q2": {"account.move"}}
ap = argparse.ArgumentParser()
ap.add_argument("--k", type=int, default=5); ap.add_argument("--dry"); ap.add_argument("--summary", action="store_true")
a = ap.parse_args()

def summary():
    rows = [r for r in (json.loads(l) for l in OUT.read_text().splitlines() if l.strip())
            if r["status"] != "call_failed"] if OUT.exists() else []
    by = collections.defaultdict(list)
    for r in rows: by[(r["qid"], r["cfg"])].append(r)
    print(f"{len(rows)} appels\n{'question':<8} {'cfg':<4} {'n':>2} {'resolu':>6} {'contient_attendu':>17}  reponses (effectif)")
    for qid in QIDS:
        for cfg in (10, 20):
            rs = by.get((qid, cfg), [])
            if not rs: continue
            c = collections.Counter(" + ".join(sorted(r["choices"])) or "[]" for r in rs)
            exp = EXPECTED.get(qid)
            hit = f"{sum(1 for r in rs if exp and exp & set(r['choices']))}/{len(rs)}" if exp else "n/a"
            print(f"{qid:<8} {cfg:<4} {len(rs):>2} {sum(1 for r in rs if r['choices'])}/{len(rs):<4} {hit:>17}  "
                  + " | ".join(f"{k} x{v}" for k, v in c.most_common()))
if a.summary:
    summary(); sys.exit(0)

from code_intelligence.agent.matching import _fuzzy_match_graph
from code_intelligence.agent.text_normalization import normalize_query_text
from code_intelligence.agent.resolution.arbitration import QUOTED_LABEL_MARKER, _llm_arbitrate
from code_intelligence.agent.resolution.candidates import (
    SHORTLIST_FUZZY_LIMIT, WIDENED_CANDIDATE_THRESHOLD, WIDENED_CANDIDATE_LIMIT, _candidate_contexts)
from code_intelligence.agent.resolution.dense_lookup import resolve_dense_retrieval
from code_intelligence.agent.resolution.label_mention import quoted_model_labels
from code_intelligence.graph import get_code_intelligence_graph
from core.llm.llm_client import get_chat_llm
from core.llm.server_fingerprint import describe, get_inference_fingerprint
from run_bloc_n1_benchmark import build_agent_state, load_questions, read_installed_modules

qids = [a.dry] if a.dry else QIDS
items, _ = load_questions(qids, None, None, read_installed_modules())
cases, graphs = [], {}
for item in items:
    state = build_agent_state(item, False); lang = state.get("language"); q = state["question"]
    if lang not in graphs:
        graphs[lang] = get_code_intelligence_graph(translation_languages=[lang] if lang else None, request_language=lang)
    G = graphs[lang]; clean = normalize_query_text(q.lower().strip())
    quoted = quoted_model_labels(clean, G)
    lex = [m for m, _ in _fuzzy_match_graph(clean, G)] or [m for m, _ in _fuzzy_match_graph(
        clean, G, threshold=WIDENED_CANDIDATE_THRESHOLD, limit=WIDENED_CANDIDATE_LIMIT)]
    dense = list(resolve_dense_retrieval(q, G, lang).candidates)
    lists, ctx = {}, {}
    for lim in (10, 20):
        c = list(dict.fromkeys(list(quoted) + lex[:SHORTLIST_FUZZY_LIMIT] + dense[:lim]))
        lists[lim] = [m for m in c if G.has_node("model:" + m) and G.nodes["model:" + m].get("node_type") == "Model"]
        cx = _candidate_contexts(G, lists[lim])
        for m, label in quoted.items():
            cx[m] = "; ".join(filter(None, [f"{QUOTED_LABEL_MARKER}: {label}", cx.get(m)]))
        ctx[lim] = cx
    cases.append((item["id"], q, lists, ctx))
    e = EXPECTED.get(item["id"], set())
    print(f"{item['id']}: liste10={len(lists[10])} liste20={len(lists[20])} attendu_dans_10={bool(e & set(lists[10]))} attendu_dans_20={bool(e & set(lists[20]))}")
if a.dry:
    for m in cases[0][2][20]: print("  ", m)
    sys.exit(0)

done = collections.Counter()
if OUT.exists():
    for l in OUT.read_text().splitlines():
        if l.strip():
            r = json.loads(l)
            if r["status"] != "call_failed": done[(r["qid"], r["cfg"])] += 1
fingerprint = get_inference_fingerprint()
print(f"[SERVEUR] {describe(fingerprint)}", flush=True)
llm = get_chat_llm()
with OUT.open("a") as f:
    for rep in range(a.k):
        for qid, q, lists, ctx in cases:
            for cfg in (10, 20):
                if done[(qid, cfg)] > rep: continue
                t = _llm_arbitrate(q, lists[cfg], llm, ctx[cfg])
                if t.status == "call_failed":
                    print(f"\nSERVEUR LLM INJOIGNABLE sur {qid} L={cfg} rep{rep} : rien enregistre pour cet appel. "
                          f"Relancer la meme commande quand le serveur / tunnel repond (reprise automatique).", flush=True)
                    summary(); sys.exit(2)
                choices = list(t.choices or ((t.choice,) if t.choice else ()))
                f.write(json.dumps({"qid": qid, "cfg": cfg, "rep": rep, "status": t.status, "choices": choices,
                                    "n_cand": len(lists[cfg]), "server": fingerprint["fingerprint_id"]}, ensure_ascii=False) + "\n"); f.flush()
                print(f"rep{rep} {qid:<7} L={cfg:<2} -> {choices or '[]'} ({t.status})", flush=True)
summary()
