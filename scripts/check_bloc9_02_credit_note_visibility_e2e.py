#!/usr/bin/env python3
"""
scripts/check_bloc9_02_credit_note_visibility_e2e.py

Bloc 9 generalization check, 2/8 -- same method as
check_bloc9_01_credit_note_cascade_e2e.py (raw composite-tool output
isolated from synthesis, then live end-to-end through
code_intelligence_agent()), applied to the second mechanism:
custom_credit_note_visibility_rules, an ir.rule AND/OR combination
puzzle on account.move (Q6.1/Q6.2 of scripts/run_adversarial_benchmark.py).

Ground truth (security/ir_rule_layered.xml + security_groups.xml):
  - Global rule (no group, AND for everyone): company scoping only
    ("Avoirs - cantonnement societe") -- no amount restriction.
  - Group rule "Avoirs - plafond visibilite regionale (50000e)", attached
    to group_avoir_regional: amount_total <= 50000.
  - Group rule "Avoirs - visibilite nationale (illimitee)", attached to
    group_avoir_national: domain_force [(1, '=', 1)] -- unconditional.
  - Group rules combine in OR across the groups the requester belongs to;
    a group rule the requester does NOT belong to is simply ignored, not
    counted as a restriction.

Q6.1 (member of BOTH groups) on an 80 000e avoir: the unconditional
national rule alone already grants access via OR, regardless of the
regional 50k cap -- access is allowed (RuleEvaluationResult.can_view_amount
must return True).

Q6.2 (member of NEITHER group) on the same 80 000e avoir: no group rule
applies at all (both are ignored, not violated), so only the global
company-scoping rule remains -- which carries no amount condition. Access
is allowed too, for a structurally different reason than Q6.1 (absence of
restriction, not an OR win) -- this is the trap: it is easy to wrongly
conclude "no group -> more restricted" when the real Odoo semantics are
the opposite (no group rule is simply not evaluated at all).

Unlike script 1/8, this mechanism needs a real requester identity (real
Odoo group ids from a live instance, not just a question in French) --
group_map resolution mirrors scripts/run_adversarial_benchmark.py's
_resolve_bloc7_test_group_ids() exactly, reusing rag.graph's lazy admin
RPC singleton rather than opening a second admin connection.
"""

import json
import sys
import unicodedata
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "miro-rag"))

from rag.graph import (
    code_intelligence_agent, get_code_intelligence_graph, query_graph,
    _get_admin_rpc_client, _resolve_user_group_xmlids,
)
from code_intelligence.ci_agent_tools import ALL_CI_TOOLS, set_graph_ref, evaluer_regles_raw

TEST_AMOUNT = 80000


def _fold_accents(s: str) -> str:
    """Same rationale as deterministic_tools.py::_fold_accents -- the raw
    tool text spells rule names without accents ('visibilite nationale'),
    but the small synthesis LLM re-accents them properly in prose
    ('visibilité nationale') when paraphrasing. A plain substring marker
    check against the unaccented form then reports a false MISSING even
    when the answer is substantively correct -- confirmed live 2026-08-10
    on bloc9-02a-both-groups (LLM wrote 'Avoirs - plafond visibilité
    régionale' / 'Avoirs - visibilité nationale', both accented)."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _marker_present(marker: str, text: str) -> bool:
    return _fold_accents(marker.lower()) in _fold_accents(text.lower())

# Bug B2(a), todo/contexte.txt section 99 (2026-08-21): both questions
# reformulated to state explicitly that the requester is in the SAME
# company as the record. Before this change, neither question said
# anything about company at all, so _extract_company_context(question)
# returned {} (rag/ci_helpers.py) -- absence of signal, per rules.md
# Regle 5 -- and the mandatory GLOBAL rule's domain_force
# (['|', (move_type != out_refund), (company_id == user.company_id.id)])
# stayed structurally indeterminate for both 02a and 02b: Faux/Inconnu OR
# Inconnu(company_id) = Inconnu in Kleene logic, since company_id is never
# resolved. This is not a routing or synthesis bug (see section 99's full
# Kleene recomputation) -- it is these two questions never supplying a
# piece of context their own ground-truth rule structurally requires.
# Adding "même société" lets _COMPANY_SAME_PATTERN resolve company_id, so
# the global rule's second OR-leaf becomes True -- True OR anything = True
# in Kleene logic, so the mandatory rule now resolves definitively
# regardless of move_type, restoring the same expected/forbidden marker
# contract this script already asserted before Bug B2(a) (section
# 96/97/98) made the engine honest enough to expose the gap. The oracle
# (evaluer_regles_raw/can_view_amount(), still the pre-_v2 method, see
# check_raw_tool_output) is unaffected by this change: it already ignored
# company_id silently and returned True regardless.
QUESTIONS = [
    {
        "id": "bloc9-02a-both-groups",
        "question": (
            "Un utilisateur de la même société, membre à la fois du groupe "
            "régional et du groupe national, peut-il voir un avoir de "
            "80 000€ ?"
        ),
        "user_groups_key": "BOTH",
        "expected_markers": [
            "Avoirs - visibilite nationale",
        ],
        "forbidden_markers": [
            "NE PEUT PAS",
            "ne peut pas voir",
        ],
    },
    {
        "id": "bloc9-02b-no-groups",
        "question": (
            "Un utilisateur de la même société, qui n'appartient à AUCUN des "
            "deux groupes (ni régional, ni national), peut-il voir ce même "
            "avoir de 80 000€ ?"
        ),
        "user_groups_key": "NONE",
        "expected_markers": [
            "cantonnement societe",
        ],
        "forbidden_markers": [
            "NE PEUT PAS",
            "ne peut pas voir",
        ],
    },
]


def _resolve_group_ids():
    """Mirrors scripts/run_adversarial_benchmark.py::_resolve_bloc7_test_group_ids
    exactly -- same lookup, same rationale (reuse the lazy admin RPC
    singleton, group xml_id -> DB id is a pure static-metadata lookup that
    never depends on who's asking)."""
    client, admin_uid = _get_admin_rpc_client()
    records = client.execute_kw(
        admin_uid, "ir.model.data", "search_read",
        [[("module", "=", "custom_credit_note_visibility_rules"),
          ("name", "in", ["group_avoir_regional", "group_avoir_national"])]],
        {"fields": ["name", "res_id"]},
    )
    by_name = {r["name"]: r["res_id"] for r in records}
    return by_name.get("group_avoir_regional"), by_name.get("group_avoir_national")


def check_raw_tool_output(group_map):
    print("=" * 80)
    print(" RAW evaluer_regles_enregistrement OUTPUT (account.move, droit=read)")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)

    all_ok = True
    for label, ids in group_map.items():
        # evaluer_regles_enregistrement matches against group XML-IDs (e.g.
        # 'custom_credit_note_visibility_rules.group_avoir_national'), not
        # raw Odoo DB ids -- code_intelligence_agent() normally does this
        # translation itself (rag/graph.py::_resolve_user_group_xmlids)
        # before any tool call. This raw check bypasses that agent layer on
        # purpose (to isolate the rule engine from synthesis), so it must
        # do the same translation explicitly here, or the DB ids are passed
        # straight into a function that only knows how to compare xml_id
        # strings -- confirmed live 2026-08-10 (AttributeError: 'int' object
        # has no attribute 'rsplit' inside _group_short_name).
        xmlids = _resolve_user_group_xmlids(ids)
        result = evaluer_regles_raw("account.move", "read", json.dumps(xmlids))
        print(f"--- requester groups = {label} (ids={ids} -> xmlids={xmlids}) ---")
        print(result.summary_text)
        can_view = result.can_view_amount(TEST_AMOUNT)
        print(f"can_view_amount({TEST_AMOUNT}) = {can_view}")
        print("-" * 80)
        if not can_view:
            print(f"[FAIL] Ground truth says access should be ALLOWED for {label}, "
                  f"but can_view_amount({TEST_AMOUNT}) returned False.")
            all_ok = False
        else:
            print(f"[OK ] can_view_amount({TEST_AMOUNT}) is True, as expected for {label}.")
        print()
    return all_ok


def check_e2e(group_map):
    all_ok = True
    for item in QUESTIONS:
        print("=" * 80)
        print(f" {item['id']}")
        print("=" * 80)
        print(f"Question: {item['question']}\n")

        user_groups = group_map.get(item["user_groups_key"], [])
        print(f"Requester groups: {item['user_groups_key']} -> DB ids {user_groups}\n")

        state = {
            "question": item["question"],
            "chat_history": [],
            "user_groups": user_groups,
        }
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


def check_e2e_full_pipeline(group_map):
    """Same questions as check_e2e(), but through query_graph() (the real
    route() dispatch) instead of calling code_intelligence_agent()
    directly -- catches routing bugs check_e2e() alone cannot see (see
    check_bloc9_01_credit_note_cascade_e2e.py::check_e2e_full_pipeline for
    the full rationale, contexte.txt section 78). Generalized to all 8
    modules 2026-08-20."""
    print("=" * 80)
    print(" FULL PIPELINE (query_graph -> route())")
    print("=" * 80)
    all_ok = True
    for item in QUESTIONS:
        print(f"\n--- {item['id']} (full pipeline) ---")
        user_groups = group_map.get(item["user_groups_key"], [])
        print(f"Question : {item['question']}")
        print(f"Requester groups: {item['user_groups_key']} -> DB ids {user_groups}")
        response = query_graph(question=item["question"], user_groups=user_groups)
        answer = response.answer if response else ""
        print(f"R\u00e9ponse brute :\n{answer}\n")

        expected_markers = item.get("expected_markers", [])
        forbidden_markers = item.get("forbidden_markers", [])
        missing = [m for m in expected_markers if not _marker_present(m, answer)]
        present_forbidden = [m for m in forbidden_markers if _marker_present(m, answer)]
        for m in expected_markers:
            print(f"[{'OK ' if m not in missing else 'MISSING'}] expected marker: {m}")
        for m in forbidden_markers:
            print(f"[{'FAIL' if m in present_forbidden else 'OK '}] forbidden marker absent: {m}")

        if missing or present_forbidden:
            print(f"[RESULT] {item['id']} (full pipeline): FAIL -- missing {missing}, forbidden present {present_forbidden}")
            all_ok = False
        else:
            print(f"[RESULT] {item['id']} (full pipeline): OK")
    return all_ok


def main():
    try:
        region_id, national_id = _resolve_group_ids()
    except Exception as e:
        print(f"[FAIL] Could not resolve group ids via live Odoo RPC: {e}")
        sys.exit(1)

    if region_id is None or national_id is None:
        print(f"[FAIL] Group ids not found (region={region_id}, national={national_id}). "
              f"Is custom_credit_note_visibility_rules installed on the target Odoo instance?")
        sys.exit(1)

    group_map = {
        "BOTH": [region_id, national_id],
        "NONE": [],
    }

    raw_ok = check_raw_tool_output(group_map)
    print()
    e2e_ok = check_e2e(group_map)
    print()
    full_pipeline_ok = check_e2e_full_pipeline(group_map)
    print("=" * 80)
    if raw_ok and e2e_ok and full_pipeline_ok:
        print("[BLOC 9 - 2/8] custom_credit_note_visibility_rules: E2E confirmed.")
        sys.exit(0)
    else:
        print("[BLOC 9 - 2/8] custom_credit_note_visibility_rules: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
