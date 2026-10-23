#!/usr/bin/env python3
"""
scripts/check_bloc9_05_asset_loan_e2e.py

 generalization check, 5/8 -- same method as modules 1/8-4/8
(raw composite-tool output isolated from synthesis, then live end-to-end
through code_intelligence_agent()), applied to the fifth mechanism:
asset_loan, a cross-model relational business rule (no has_group(),
no hardcoded emails -- a structurally different mechanism shape from
modules 1/8-4/8, all of which gated on group membership and/or a
privileged-login bypass list).

Ground truth (asset_loan/models/asset_loan.py, read directly from
disk, not from real / text):
  - `action_demarrer`: for each record, IF the loan is linked to a
    purchase request (`demande_achat_liee_id` set) AND that linked
    request's `montant_estime > 2000`, THEN the loan's `beneficiaire_id`
    must differ from the linked request's own `demandeur_id`, else
    UserError "Separation des roles requise : le beneficiaire d'un
    materiel de plus de 2000 euros doit etre different du demandeur
    initial.". No group check, no hardcoded login list anywhere in this
    model -- SecurityLockASTVisitor should report the exception message
    and nothing else (no `required_groups`, no `has_hardcoded_logins`),
    which this script's raw check treats as a POSITIVE assertion (a
    legitimate rule with nothing to gate), not a missing-extraction gap.
  - The trap: the condition is guarded by `rec.demande_achat_liee_id and
    ...` (guard on the relational field, correctly applied here -- no
    unguarded relational-field access). If NO purchase request is linked
    at all, the whole condition short-circuits to False and
    `action_demarrer` proceeds unconditionally regardless of the
    (unknowable, since there's no linked estimated amount) value of the
    equipment -- i.e. the separation-of-duties rule is NOT a blanket
    rule on every loan, only on loans traceable to an over-2000e
    purchase request. A plausible wrong read of the code is "beneficiary
    must always differ from someone" or "the rule applies to every loan
    regardless of amount".
  - `asset_loan` depends only on `ext_purchase_request`
    (`__manifest__.py`), itself already a custom module the
    graph loads directly (not the real-core-Odoo-dependency gap,
    which only concerned non-custom deps like `hr_expense`/
    `hr_holidays`) -- no generalization gap expected on that front here,
    unlike modules 3/8 and (implicitly) 5/8 being the second and third
    real confirmations of that fix on genuinely different dependency
    shapes.
  - No live Odoo group resolution needed (same convention as modules
    1/8, 3/8, 4/8): all three questions run as an anonymous/ungrouped
    requester, since nothing here depends on who is asking.
"""

import re
import sys
import unicodedata
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph.graph import code_intelligence_agent, get_code_intelligence_graph, query_graph
from code_intelligence.agent.tools import ALL_CI_TOOLS
from code_intelligence.agent.tools.helpers import set_graph_ref
from code_intelligence.utils import SENSITIVE_BYPASS_MARKER

TARGET_MODEL = "custom.asset.loan"

# Ground-truth amount is written "2000 euros" (no thousands separator) in
# the raw exception message but may be re-rendered "2 000€"/"2000€" by the
# synthesis LLM -- same whitespace-tolerant stance as module 4/8's
# _THRESHOLD_RE / rag/graph.py's _AMOUNT_PATTERN.
_THRESHOLD_RE = re.compile(r"2\s?000")


def _fold_accents(s: str) -> str:
    """Same technique as modules 2/8-4/8's _fold_accents -- the raw
    exception message here ('Separation des roles', 'materiel de plus',
    'differe du demandeur initial') also drops French accents, while the
    small synthesis LLM may re-accent when paraphrasing."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _marker_present(marker: str, text: str) -> bool:
    if marker == "__THRESHOLD__":
        return bool(_THRESHOLD_RE.search(text))
    return _fold_accents(marker.lower()) in _fold_accents(text.lower())


QUESTIONS = [
    {
        "id": "",
        "question": (
            "Pourquoi je n'arrive pas à démarrer une mise à disposition de "
            "matériel dont je suis à la fois le demandeur d'achat et le "
            "bénéficiaire ?"
        ),
        "expected_markers": ["__THRESHOLD__", "demandeur"],
    },
    {
        "id": "",
        "question": (
            "Dans le modèle custom.asset.loan, quelles sont toutes les "
            "conditions vérifiées par action_demarrer ?"
        ),
        "expected_markers": ["__THRESHOLD__", "demandeur"],
    },
    {
        "id": "",
        "question": (
            "Si une mise à disposition de matériel n'est reliée à aucune "
            "demande d'achat, la règle de séparation des rôles "
            "(bénéficiaire différent du demandeur) s'applique-t-elle quand "
            "même, quel que soit le montant du matériel ?"
        ),
        "expected_markers": ["__THRESHOLD__"],
        # Bug 1 (2026-08-11): this question originally had NO
        # forbidden_markers at all, and check_e2e() never checked for any
        # -- so a live run where the synthesized prose asserted the EXACT
        # inverse of ground truth ("la regle... s'applique quand meme...
        # quel que soit le montant") still reported "all expected markers
        # present" and the script's own final line said "E2E confirmed",
        # because the deterministic [FAIT DETERMINISTIQUE] backfill always
        # appends '__THRESHOLD__' (2000) regardless of what the prose
        # above it said. A marker-presence check alone cannot catch a
        # wrong CONCLUSION, only a missing fact -- this is a different
        # failure shape from every other module's gaps, which were all
        # omissions. Confirmed real phrasings from the live run this is
        # guarding against (kept in French, not paraphrased, so the
        # forbidden-marker check matches the actual failure mode rather
        # than a hypothetical one).
        "forbidden_markers": [
            "s'applique quand meme",
            "s'applique tout de meme",
        ],
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

    # Unlike modules 1/8-4/8, this model has no has_group() guard and no
    # hardcoded login list -- so the raw check asserts the exception
    # message IS present AND that nothing gets (mis)tagged as a security
    # bypass here. A SENSITIVE_BYPASS_MARKER false positive on a purely
    # relational business rule would itself be a real gating bug (it
    # would make security/gate.py redact legitimate governance
    # content for no reason), so this is a genuine negative assertion,
    # not filler.
    checks_present = {
        "exception message (separation des roles)": "separation des roles",
        "exception message (montant threshold)": "__THRESHOLD__",
    }
    all_ok = True
    for label, marker in checks_present.items():
        present = _marker_present(marker, result)
        print(f"[{'OK ' if present else 'MISSING'}] raw tool mentions {label}: {marker!r}")
        if not present:
            all_ok = False

    no_bypass_tagged = SENSITIVE_BYPASS_MARKER not in result
    print(
        f"[{'OK ' if no_bypass_tagged else 'FAIL'}] raw tool does NOT tag this model's "
        f"legitimate relational rule as a security bypass ({SENSITIVE_BYPASS_MARKER!r} absent)"
    )
    if not no_bypass_tagged:
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
            print(f"[{'FAIL -- WRONG CONCLUSION' if marker in present_forbidden else 'OK (absent)'}] forbidden marker: {marker}")

        if missing or present_forbidden:
            if missing:
                print(f"[RESULT] {item['id']}: INCOMPLETE -- missing {missing}")
            if present_forbidden:
                print(f"[RESULT] {item['id']}: WRONG CONCLUSION -- forbidden marker(s) present {present_forbidden}")
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
    the full rationale). Generalized to all 8
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
            print(f"[{'FAIL -- WRONG CONCLUSION' if m in present_forbidden else 'OK (absent)'}] forbidden marker: {m}")

        if missing or present_forbidden:
            print(f"[RESULT] {item['id']} (full pipeline): FAIL -- missing {missing}, forbidden present {present_forbidden}")
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
        print("[ - 5/8] asset_loan: E2E confirmed.")
        sys.exit(0)
    else:
        print("[ - 5/8] asset_loan: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
