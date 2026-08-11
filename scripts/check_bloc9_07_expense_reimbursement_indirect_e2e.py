#!/usr/bin/env python3
"""
scripts/check_bloc9_07_expense_reimbursement_indirect_e2e.py

Bloc 9 generalization check, 7/8 -- same method as modules 1/8-6/8 (raw
composite-tool output isolated from synthesis, then live end-to-end
through code_intelligence_agent()), applied to the seventh mechanism:
custom_expense_reimbursement_indirect (Q9.1) -- structurally UNLIKE every
other Bloc 9 module: this one deliberately has NO nameable access-control
mechanism at all (no has_group(), no ir.rule, no sudo(), no hardcoded
login/ID list, no ir.actions.server). The manifest's own summary says so
verbatim: "gate de validation non-nommable, sans mecanisme Odoo standard".
The correct answer to "qui a le droit de valider" is not a group or a
threshold -- it's an honest statement that the code cannot be classified
with certainty, per the project's own design rule (stated by the user,
2026-08-10, logged in contexte.txt/etat_reel.md): when the agent cannot
answer a question, it should say so and point to how a human could find
out, rather than staying silent or fabricating a plausible-looking answer.

Ground truth (custom_expense_reimbursement_indirect/models/reimbursement.py,
read directly from disk):
    _TAB = {0: 1, 1: 0, 2: 0, 3: 1, 4: 0, 5: 1, 6: 0}

    def action_valider(self):
        for r in self:
            f = getattr(
                r,
                '_g_%s' % self.env['ir.config_parameter'].sudo().get_param(
                    'custom_reimb.mode', 'q7'
                ),
                None,
            )
            v = f() if f else False
            r.etat = 'valide' if v else 'refuse'

    def _g_q7(self):
        k = self.employe_id.id % 7
        return bool(_TAB.get(k, 0))

  - The method actually invoked is resolved at RUNTIME from a system
    parameter (`ir.config_parameter` 'custom_reimb.mode', default 'q7'),
    string-concatenated into a method name and looked up via getattr() --
    static analysis genuinely cannot know which `_g_*` method will run
    without knowing the live database's config parameter value (which
    could differ per environment/tenant and change at any time without a
    code deploy). Even the DEFAULT target, `_g_q7`, decides validation via
    `employe_id.id % 7` against an opaque lookup table with no comment
    explaining what it encodes -- not a documented business rule (not a
    group, not an amount threshold, not a workflow state), an arbitrary
    function of the requester's own database id.
  - Two independent findings the tool must surface, not just one:
    (1) the getattr() call itself (dynamic dispatch, `[Confiance: FAIBLE]`,
    "revue manuelle recommandée" per semgrep_locks_analyzer.py's existing
    generic getattr/eval/exec detection -- no code change needed here,
    this script only verifies that detection actually reaches the model);
    (2) that sudo() appears in this code TOO (`self.env[...].sudo()`) but
    for reading a config parameter, not for bypassing ir.rule/ACL on
    account.move records like module 6/8's mechanism -- a plausible
    wrong read is treating every sudo() occurrence as an approval bypass
    regardless of what it's actually applied to; this script checks the
    answer does NOT claim this sudo() grants elevated write access.
  - No group resolution needed -- nothing here is group-gated; all
    questions run as an anonymous/ungrouped requester (same convention as
    modules 1/8, 3/8, 4/8, 5/8).
"""

import re
import sys
import unicodedata
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "miro-rag"))

from rag.graph import code_intelligence_agent, get_code_intelligence_graph
from code_intelligence.ci_agent_tools import ALL_CI_TOOLS, set_graph_ref

TARGET_MODEL = "custom.reimbursement.request"


def _fold_accents(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _marker_present(marker: str, text: str) -> bool:
    return _fold_accents(marker.lower()) in _fold_accents(text.lower())


QUESTIONS = [
    {
        "id": "bloc9-07a-business",
        "question": (
            "Qui peut valider une demande de remboursement de frais dans "
            "le module custom_expense_reimbursement_indirect ?"
        ),
        "expected_markers": ["getattr"],
        # A confident, specific group/threshold claim would be a
        # hallucination -- there is no such mechanism in this model at
        # all, ground truth is explicit uncertainty. If the model name-
        # drops a plausible-sounding but nonexistent group here, that is
        # the same fabrication failure class as module 1/8's Gap 3.
        "forbidden_markers": [
            "group_account_manager",
            "group_purchase_manager",
            "group_hr_holidays_manager",
        ],
    },
    {
        "id": "bloc9-07b-technical",
        "question": (
            "Dans le modèle custom.reimbursement.request, la méthode "
            "action_valider peut-elle être analysée statiquement avec "
            "certitude ? Pourquoi ?"
        ),
        "expected_markers": ["getattr", "reimbursement.py"],
        "forbidden_markers": [],
    },
    {
        "id": "bloc9-07c-sudo-scope-trap",
        "question": (
            "Le code d'action_valider contient un appel sudo() -- est-ce "
            "que cela signifie que n'importe qui peut valider une demande "
            "de remboursement sans restriction ?"
        ),
        "expected_markers": ["getattr"],
        # The trap: sudo() here reads a config parameter, it is not an
        # approval-bypass grant on this model's own records -- an answer
        # that treats it as "sudo() = anyone can validate" would be wrong
        # in the opposite direction from module 6/8's real bypass.
        "forbidden_markers": [
            "n'importe qui peut valider",
            "sans restriction",
            "aucune restriction",
        ],
    },
]


def check_raw_tool_output():
    print("=" * 80)
    print(f" RAW analyser_verrous_securite OUTPUT ({TARGET_MODEL})")
    print("=" * 80)
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    tool_map = {t.name: t for t in ALL_CI_TOOLS}
    tool = tool_map.get("analyser_verrous_securite")
    if tool is None:
        print("[FAIL] Tool 'analyser_verrous_securite' not found in ALL_CI_TOOLS.")
        return False
    result = str(tool.invoke({"model_name": TARGET_MODEL}))
    print(result)
    print("-" * 80)

    checks_present = {
        "getattr dynamic dispatch flagged": "getattr",
        "manual review recommendation": "revue manuelle",
        "low/FAIBLE confidence tag": "FAIBLE",
    }
    all_ok = True
    for label, marker in checks_present.items():
        present = _marker_present(marker, result)
        print(f"[{'OK ' if present else 'MISSING'}] raw tool mentions {label}: {marker!r}")
        if not present:
            all_ok = False

    # Negative assertion: this model has no has_group()-derived governance
    # content to report -- a false positive here would be a real
    # extraction bug (fabricating structure that doesn't exist), same
    # rationale as module 5/8's SENSITIVE_BYPASS_MARKER absence check.
    no_group_claim = not _marker_present("groupe(s) technique(s) requis", result)
    print(
        f"[{'OK ' if no_group_claim else 'FAIL'}] raw tool does NOT report a fabricated "
        f"has_group()-derived required group for this model"
    )
    if not no_group_claim:
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
            print(f"[{'FAIL -- HALLUCINATION/WRONG CLAIM' if marker in present_forbidden else 'OK (absent)'}] forbidden marker: {marker}")

        if missing or present_forbidden:
            if missing:
                print(f"[RESULT] {item['id']}: INCOMPLETE -- missing {missing}")
            if present_forbidden:
                print(f"[RESULT] {item['id']}: WRONG CLAIM -- forbidden marker(s) present {present_forbidden}")
            all_ok = False
        else:
            print(f"[RESULT] {item['id']}: all expected markers present, no forbidden markers.")
        print()
    return all_ok


def main():
    raw_ok = check_raw_tool_output()
    print()
    e2e_ok = check_e2e()
    print("=" * 80)
    if raw_ok and e2e_ok:
        print("[BLOC 9 - 7/8] custom_expense_reimbursement_indirect: E2E confirmed.")
        sys.exit(0)
    else:
        print("[BLOC 9 - 7/8] custom_expense_reimbursement_indirect: GAP FOUND -- see [MISSING]/[FAIL] lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
