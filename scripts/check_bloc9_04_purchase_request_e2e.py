#!/usr/bin/env python3
"""
E2E verification for custom_purchase_request authorization bypass.
"""

import re
import sys
import unicodedata
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import code_intelligence_agent, get_code_intelligence_graph, query_graph
from code_intelligence.agent.tools import ALL_CI_TOOLS
from code_intelligence.agent.tool_helpers import set_graph_ref
from code_intelligence.utils import SENSITIVE_BYPASS_MARKER

TARGET_MODEL = "custom.purchase.request"

# Amount threshold in the ground truth is written "10 000 euros" (French
# space thousands separator) in the raw exception message but may be
# re-rendered "10 000€"/"10000€" by the synthesis LLM -- match on a
# whitespace-tolerant "10 000" / "10000" pattern rather than a fixed
# substring, same defensive stance as _AMOUNT_PATTERN in rag/graph.py.
_THRESHOLD_RE = re.compile(r"10\s?000")

# gap (2026-08-26, section 183/186): the previous version of this
# script only ever checked for the PRESENCE of the group xmlid and the
# threshold marker, never that the answer correctly states the group is
# INSUFFICIENT above that threshold -- so it would have passed even on
# the exact wrong answer diagnosed in section 178 ("l'autorite requise
# est donc les utilisateurs appartenant au groupe
# purchase.group_purchase_manager"), which directly contradicts the
# ground truth ("Le groupe purchase_manager ne suffit pas >10000E. Seuls
# logins dans _VALIDATEURS_EXCEPTIONNELS peuvent valider"). This marker
# closes that blind spot: any ONE of these phrases signals the answer
# correctly conveys insufficiency, without requiring an exact wording
# match (the synthesis LLM paraphrases this governance point in several
# equivalent ways across runs).
# gap 2 (2026-09-07, rejeu benchmark adversarial reserve 573a) : les 6
# alternatives ci-dessus supposent toutes une formulation "le groupe est
# insuffisant" -- mais la synthese peut tout aussi legitimement exprimer
# la meme conclusion depuis le point de vue de l'utilisateur ("vous/il
# NE PEUT PAS valider... au-dela de ce seuil", "doit etre dans la liste
# pour les montants superieurs"), confirme live 2x (direct + full
# pipeline) sur la question 04c ("un membre de purchase_manager peut-il
# a lui seul valider... quel que soit son montant") -- le contenu etait
# correct dans les deux runs, seul le choix de formulation du marker
# etait trop etroit. Meme classe de dette que les fixes 1/8/2/8, cette
# fois sur la voix (sujet=le groupe vs sujet=l'utilisateur) plutot que
# l'espacement ou la convention xml_id. Pas d'alternative accentuee
# necessaire ici : le texte compare est toujours passe par _fold_accents
# avant le match (voir _marker_present), donc 'etre'/'a' suffisent.
_GROUP_INSUFFICIENT_RE = re.compile(
    r"(ne suffit pas|insuffisant|pas suffisant|liste restreinte|"
    r"seule la direction|ne suffisent pas|"
    r"ne peut pas.{0,80}(valider|approuver)|"
    r"doit etre dans la liste)",
    re.IGNORECASE,
)

HARDCODED_EMAILS = ["direction@societe.com", "daf@societe.com"]


def _fold_accents(s: str) -> str:
    """Same technique as modules 2/8 and 3/8's _fold_accents -- the raw
    exception message here ('Au-dela de 10 000 euros') also drops French
    accents, while the small synthesis LLM may re-accent when
    paraphrasing ('Au-delà')."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _marker_present(marker: str, text: str) -> bool:
    if marker == "__THRESHOLD__":
        return bool(_THRESHOLD_RE.search(text))
    if marker == "__GROUP_INSUFFICIENT__":
        return bool(_GROUP_INSUFFICIENT_RE.search(_fold_accents(text)))
    return _fold_accents(marker.lower()) in _fold_accents(text.lower())


QUESTIONS = [
    {
        "id": "",
        "question": "Qui a le droit d'approuver une demande d'achat de 15 000€ ?",
        "expected_markers": [
            "purchase.group_purchase_manager",
            "__THRESHOLD__",
            "__GROUP_INSUFFICIENT__",
        ],
        "forbidden_markers": HARDCODED_EMAILS,
    },
    {
        "id": "",
        "question": (
            "Dans le modèle custom.purchase.request, quelles sont toutes "
            "les conditions vérifiées par action_valider ?"
        ),
        "expected_markers": [
            "purchase.group_purchase_manager",
            "__THRESHOLD__",
            "__GROUP_INSUFFICIENT__",
        ],
        "forbidden_markers": HARDCODED_EMAILS,
    },
    {
        "id": "",
        "question": (
            "Un utilisateur membre du groupe purchase_manager peut-il, à "
            "lui seul, valider n'importe quelle demande d'achat quel que "
            "soit son montant ?"
        ),
        "expected_markers": [
            "purchase.group_purchase_manager",
            "__THRESHOLD__",
            "__GROUP_INSUFFICIENT__",
        ],
        "forbidden_markers": HARDCODED_EMAILS,
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(f" RAW analyze_security_locks OUTPUT ({TARGET_MODEL})")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    tool = tool_map.get("analyze_security_locks")
    if tool is None:
        print("[FAIL] Tool 'analyze_security_locks' not found in ALL_CI_TOOLS.")
        return False
    result = str(tool.invoke({"model_name": TARGET_MODEL}))
    print(result)
    print("-" * 80)

    # Raw tool call bypasses security/gate.py entirely (that gating
    # happens in rag/graph.py's forced-dispatch/ReAct wiring, not inside
    # the tool itself) -- so at THIS layer the hardcoded emails and the
    # SENSITIVE_BYPASS_MARKER tag MUST be present, confirming the
    # extraction/detection layer itself works, before checking (in
    # check_e2e below) that the gate gets applied downstream.
    checks = {
        "exception message (no rights)": "vous n'avez pas le droit de valider",
        "exception message (10k threshold)": "__THRESHOLD__",
        "required group (has_group extraction)": "purchase.group_purchase_manager",
        "hardcoded email 1 (raw, pre-gating)": "direction@societe.com",
        "hardcoded email 2 (raw, pre-gating)": "daf@societe.com",
        # gap (2026-08-10, module 4/8): this used to check for a
        # literal 'LOGINS/EMAILS EN DUR' substring, which never matched --
        # the analyzer's actual line reads "Logins/Emails privilégies en
        # dur" (note "privilégies"), and the real source-of-truth tag
        # gating downstream depends on is the shared
        # code_intelligence.utils.SENSITIVE_BYPASS_MARKER constant
        # ('[CONTOURNEMENT SENSIBLE]', see security/gate.py), not this
        # ad hoc substring. Check the actual constant instead of a
        # hand-copied string that had already drifted from it.
        "SENSITIVE_BYPASS_MARKER tag present": SENSITIVE_BYPASS_MARKER,
    }
    all_ok = True
    for label, marker in checks.items():
        present = _marker_present(marker, result)
        print(f"[{'OK ' if present else 'MISSING'}] raw tool mentions {label}: {marker!r}")
        if not present:
            all_ok = False
    return all_ok


def check_e2e():
    all_ok = True
    for item in QUESTIONS:
        print("=" * 80)
        print(f" {item['id']}")
        print("=" * 80)
        print(f"Question: {item['question']}\n")
        state = {"question": item["question"], "chat_history": []}
        result = code_intelligence_agent(state)
        response = result.get("response")
        if response is None:
            print("[FAIL] No response object returned.")
            all_ok = False
            continue
        answer = response.answer
        timing = result.get("timing", {})
        print(f"Answer (hops={timing.get('ci_hop_count', '?')}):\n{answer}\n")
        print("-" * 80)

        expected_markers = item.get("expected_markers", [])
        forbidden_markers = item.get("forbidden_markers", [])

        missing = [m for m in expected_markers if not _marker_present(m, answer)]
        present_forbidden = [m for m in forbidden_markers if _marker_present(m, answer)]

        for marker in expected_markers:
            print(f"[{'OK ' if marker not in missing else 'MISSING'}] expected marker: {marker}")
        for marker in forbidden_markers:
            print(f"[{'FAIL -- LEAKED' if marker in present_forbidden else 'OK (masked)'}] forbidden marker: {marker}")

        if missing or present_forbidden:
            if missing:
                print(f"[RESULT] {item['id']}: INCOMPLETE -- missing {missing}")
            if present_forbidden:
                print(f"[RESULT] {item['id']}: GATING LEAK -- forbidden marker(s) present {present_forbidden}")
            all_ok = False
        else:
            print(f"[RESULT] {item['id']}: all expected markers present, no forbidden markers.")
        print()
    return all_ok


def check_e2e_full_pipeline():
    """Same questions as check_e2e(), but through query_graph() (the real
    route() dispatch) instead of calling code_intelligence_agent()
    directly -- catches routing bugs check_e2e() alone cannot see (see
    check_bloc9_01_credit_note_cascade_e2e.py::check_e2e_full_pipeline for
    the full rationale,  section 78). Generalized to all 8
    modules 2026-08-20."""
    print("=" * 80)
    print(" FULL PIPELINE (query_graph -> route())")
    print("=" * 80)
    all_ok = True
    for item in QUESTIONS:
        print(f"\n--- {item['id']} (full pipeline) ---")
        print(f"Question : {item['question']}")
        response = query_graph(question=item["question"], user_groups=[])
        answer = response.answer if response else ""
        print(f"R\u00e9ponse brute :\n{answer}\n")

        expected_markers = item.get("expected_markers", [])
        forbidden_markers = item.get("forbidden_markers", [])
        missing = [m for m in expected_markers if not _marker_present(m, answer)]
        present_forbidden = [m for m in forbidden_markers if _marker_present(m, answer)]
        for m in expected_markers:
            print(f"[{'OK ' if m not in missing else 'MISSING'}] expected marker: {m}")
        for m in forbidden_markers:
            print(f"[{'FAIL -- LEAKED' if m in present_forbidden else 'OK (masked)'}] forbidden marker: {m}")

        if missing or present_forbidden:
            print(f"[RESULT] {item['id']} (full pipeline): FAIL -- missing {missing}, leaked {present_forbidden}")
            all_ok = False
        else:
            print(f"[RESULT] {item['id']} (full pipeline): OK")
    return all_ok


def main():
    raw_ok = check_raw_tool_output()
    print()
    e2e_ok = check_e2e()
    print()
    full_pipeline_ok = check_e2e_full_pipeline()
    print("=" * 80)
    if raw_ok and e2e_ok and full_pipeline_ok:
        print("[ - 4/8] custom_purchase_request: E2E confirmed.")
        sys.exit(0)
    else:
        print("[ - 4/8] custom_purchase_request: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
