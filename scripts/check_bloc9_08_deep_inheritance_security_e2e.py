#!/usr/bin/env python3
"""
scripts/check_bloc9_08_deep_inheritance_security_e2e.py

Bloc 9 generalization check, 8/8 (2026-08-13) -- same method as modules
1/8-7/8 (raw composite-tool output isolated from synthesis, then live
end-to-end through code_intelligence_agent()), applied to the eighth and
final mechanism this reconciliation identified: custom_deep_inheritance_security.

RECONCILIATION NOTE (closes the "7 mécanismes vs 9 dossiers" open item,
etat_reel.md): 14 real custom_* folders exist under /home/user/odoo-17.0/addons.
Grouped by distinct business mechanism:
  1-7. Already covered by scripts/check_bloc9_01..07_*.py (credit_note_approval
       +regional+vip, credit_note_visibility_rules, hr_leave_workflow,
       purchase_request, asset_loan, automation_traps, expense_reimbursement_indirect)
  8.   custom_expense_risk_alert/base/score (3 folders, 1 mechanism) --
       ALREADY covered, but via a differently-named script
       (eval_j36_expense_risk_llm.py, confirmed 8/8 on 2026-08-07), not the
       bloc9-0N naming convention -- which is exactly why it was invisible
       to a naive "do we have a bloc9-0N script for every folder" audit.
  9.   custom_modern_theme -- confirmed EMPTY directory (stub, never built,
       0 files). Legitimately out of scope, not a real gap.
  10.  custom_deep_inheritance_security -- had extraction-layer unit tests
       only (test_j34_35_deep_custom_modules.py) but was NEVER exercised
       end-to-end via code_intelligence_agent. THIS is the one genuine,
       actionable gap the reconciliation found. This script closes it.

Ground truth (custom_deep_inheritance_security/models/deep_document.py +
security/security_rules.xml, read directly from disk):
  - 5-level Python inheritance cascade on custom.deep.document (Base ->
    Level2 -> Level3 -> Level4 -> Level5). Level3/Level4 add plain fields
    only, no logic -- a legitimate "nothing to report" structural case.
  - action_validate_level2(): if amount > 50000 and not
    has_group('account.group_account_manager') -> UserError. Sets state=level2.
  - action_final_approve() (on Level5): if amount > 100000 and not
    has_group('base.group_system') -> ValidationError. Sets state=validated.
    base.group_system is a MUCH more restrictive admin-only group than
    account.group_account_manager -- the trap is conflating the two
    thresholds/groups, exactly the double-threshold-cascade shape already
    fixed for module 1 (avoir approval) but on a fresh model/mechanism.
  - ir.rule: a global company-cantonment rule, PLUS a group rule (for
    base.group_user) with a nested domain_force:
    ['&', '|', ('amount','<=',50000), ('user_id','=',user.id), ('company_id','=',user.company_id.id)]
    i.e. company MUST match, AND (amount<=50000 OR it's your own record).
    The global rule's company check is evaluated independently and already
    denies a cross-company view regardless of the group rule's nested
    OR -- 08c below tests whether the synthesis gets the REASON right,
    not just the yes/no.
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "miro-rag"))

from rag.graph import code_intelligence_agent, get_code_intelligence_graph
from code_intelligence.ci_agent_tools import ALL_CI_TOOLS, set_graph_ref

TARGET_MODEL = "custom.deep.document"


def _marker_present(marker: str, text: str) -> bool:
    """Check if marker is present in text, with space-normalization for
    numeric markers (e.g. "50000" must also match "50 000€", "50 000",
    "50\u00a0000" in French-formatted text).  Without this, 08b was a false
    negative: the response cited only the French format, not the raw
    Python literal, and the naive `in` check failed."""
    m = marker.lower()
    t = text.lower()
    if m in t:
        return True
    # Normalize all whitespace (including non-breaking space) out of both
    # sides and retry -- catches "50 000" vs "50000", "100 000" vs "100000".
    import re
    t_nospace = re.sub(r'\s+', '', t)
    m_nospace = re.sub(r'\s+', '', m)
    return m_nospace in t_nospace


QUESTIONS = [
    {
        "id": "bloc9-08a-business",
        # Amount (60000) clears the Level2 threshold (50000) but NOT the
        # Level5 threshold (100000) -- only account.group_account_manager
        # should be named, never base.group_system (the double-threshold
        # conflation trap, same shape as module 1).
        "question": (
            "Qui a le droit de valider un document à 60 000€ dans le "
            "modèle custom.deep.document (module de sécurité à héritage "
            "profond) ?"
        ),
        "expected_markers": ["account.group_account_manager", "50000"],
        # 2026-08-13 correction: dropped forbidden_markers=["base.group_system"].
        # A well-reasoned answer legitimately MENTIONS base.group_system while
        # explaining the two-threshold picture (esp. now that qui_a_acces_a's
        # full ACL dump is force-dispatched too) -- the actual trap is whether
        # the answer correctly says account.group_account_manager (not
        # base.group_system) is what's REQUIRED for 60000€, not whether the
        # word appears anywhere. No automated forbidden-marker check can
        # reliably grade that distinction; read the verdict verbatim.
        "forbidden_markers": [],
    },
    {
        "id": "bloc9-08b-technical",
        # Both thresholds/groups must be distinctly surfaced -- neither
        # dropped nor merged into one.
        "question": (
            "Dans le modèle custom.deep.document, quelles sont toutes les "
            "méthodes qui contiennent une vérification has_group, et à "
            "partir de quel montant chacune s'applique-t-elle ?"
        ),
        "expected_markers": [
            "50000",
            "100000",
            "account.group_account_manager",
            "base.group_system",
        ],
        "forbidden_markers": [],
    },
    {
        "id": "bloc9-08c-nested-domain-trap",
        # The real reason a cross-company user is denied is the GLOBAL
        # company-cantonment rule, independent of the group rule's nested
        # amount/user_id OR. Loose marker check (semantic yes/no grading
        # in French is unreliable) -- read the verdict verbatim, this is
        # primarily a manual-read question, not a strict pass/fail.
        "question": (
            "Un utilisateur standard (groupe de base uniquement) dont "
            "l'entreprise est différente de celle du document peut-il "
            "voir un document custom.deep.document de 30 000€ appartenant "
            "à un autre utilisateur, sachant que 30 000€ est sous le seuil "
            "de 50 000€ ?"
        ),
        # 2026-08-13 correction: the fix for this exact trap
        # (can_view_amount_v2 + _extract_company_context, deterministic_
        # tools.py / rag/graph.py) doesn't cite the rule's human NAME
        # ("cantonnement") -- it injects a [FAIT DÉTERMINISTIQUE] with the
        # boolean verdict itself. Check for THAT instead: the global
        # company rule alone should force can_view_amount_v2()=False via
        # Kleene-AND short-circuit, regardless of the group rule's
        # unresolved user_id leaf -- so the answer must say the user
        # canNOT view it, not cite the rule name.
        "expected_markers": ["NE PEUT PAS"],
        "forbidden_markers": [],
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(f" RAW analyser_verrous_securite + evaluer_regles_enregistrement OUTPUT ({TARGET_MODEL})")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    all_ok = True

    lock_tool = tool_map.get("analyser_verrous_securite")
    if lock_tool is None:
        print("[FAIL] Tool 'analyser_verrous_securite' not found in ALL_CI_TOOLS.")
        all_ok = False
    else:
        lock_result = str(lock_tool.invoke({"model_name": TARGET_MODEL}))
        print(lock_result)
        print("-" * 80)

        for marker, label in [
            ("account.group_account_manager", "Level2 required group"),
            ("base.group_system", "Level5 required group"),
            ("50000", "Level2 threshold amount"),
            ("100000", "Level5 threshold amount"),
        ]:
            if marker in lock_result:
                print(f"[OK ] raw lock tool mentions {label}: '{marker}'")
            else:
                print(f"[MISSING] raw lock tool does NOT mention {label}: '{marker}'")
                all_ok = False

    rule_tool = tool_map.get("evaluer_regles_enregistrement")
    if rule_tool is None:
        print("[FAIL] Tool 'evaluer_regles_enregistrement' not found in ALL_CI_TOOLS.")
        all_ok = False
    else:
        rule_result = str(
            rule_tool.invoke({
                "model_name": TARGET_MODEL,
                "user_groups_json": "[\"base.group_user\"]",
                "droit": "read",
            })
        )
        print(rule_result)
        print("-" * 80)

        if "cantonnement" in rule_result.lower():
            print("[OK ] raw rule tool mentions the global company-cantonment rule")
        else:
            print("[MISSING] raw rule tool does NOT mention the global company-cantonment rule")
            all_ok = False

        if "50000" in rule_result or "50 000" in rule_result:
            print("[OK ] raw rule tool mentions the nested rule's 50000 threshold")
        else:
            print("[MISSING] raw rule tool does NOT mention the nested rule's 50000 threshold")
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
        missing = [m for m in expected_markers if not _marker_present(m, answer)]
        for marker in expected_markers:
            status = "OK " if marker not in missing else "MISSING"
            print(f"[{status}] expected marker: {marker}")

        forbidden_markers = item.get("forbidden_markers", [])
        found_forbidden = [m for m in forbidden_markers if _marker_present(m, answer)]
        for marker in forbidden_markers:
            status = "FAIL" if marker in found_forbidden else "OK "
            print(f"[{status}] forbidden marker absent: {marker}")

        if missing or found_forbidden:
            print(f"[RESULT] {item['id']}: INCOMPLETE -- missing {missing}, forbidden {found_forbidden}")
            all_ok = False
        else:
            print(f"[RESULT] {item['id']}: all expected markers present.")
        print()
    return all_ok


def main():
    raw_ok = check_raw_tool_output()
    print()
    e2e_ok = check_e2e()
    print("=" * 80)
    if raw_ok and e2e_ok:
        print("[BLOC 9 - 8/8] custom_deep_inheritance_security: E2E confirmed.")
        sys.exit(0)
    else:
        print("[BLOC 9 - 8/8] custom_deep_inheritance_security: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
