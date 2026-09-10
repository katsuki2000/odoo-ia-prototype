from code_intelligence.tests._corpus_paths import CORE_ADDONS_PATH
"""
code_intelligence/tests/test_method_override_chain.py

 gap, found 2026-08-06 while investigating an evasive answer to
adversarial Q1.2 ("avoir VIP") in the  benchmark. Locks the fix:
  - graph_builder.py accumulating one Method node's override_sites per
    real declaration site instead of silently overwriting filepath/lineno
    on every module that overrides the same method name (same failure
    shape as the F-08 rule double-indexing bug from J7).
  - method_override_resolver.resolve_method_override_chain() composing
    the REAL execution order (reverse of manifest-dependency load order,
    matching Odoo's actual MRO construction).
  - method_override_resolver.detect_unguarded_super() flagging the exact
    bug shape found in custom_credit_note_approval_vip: a conditional
    branch that sets state without an early `return`, followed later in
    the same method by an unconditional `super()` call.

Includes both a fast synthetic unit test and an integration test reading
the REAL corpus files (no mocks) to confirm the actual VIP bug is caught
end-to-end, per project convention for security/governance-relevant
mechanisms (see J5's live_client fixture / test_j34_35's MODULE_PATH use
of the real addons tree).
"""

from pathlib import Path

import pytest

from code_intelligence.knowledge_rules.graph import ParsedModule, build_module_symbol_registry
from code_intelligence.knowledge_rules.graph import OdooGraphBuilder
from code_intelligence.knowledge_rules.extractor.manifest_parser import parse_manifest
from code_intelligence.knowledge_rules.overrides import (
    analyze_method_override_chain,
    detect_unguarded_super,
    find_methods_with_unguarded_super,
    resolve_method_override_chain,
)
from code_intelligence.knowledge_rules.extractor.python_extractor import extract_odoo_models_from_file


# ---------------------------------------------------------------------
# Synthetic unit tests (fast, no filesystem dependency on the real corpus)
# ---------------------------------------------------------------------

VIP_SHAPE_SOURCE = '''
class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_valider_avoir(self):
        for rec in self:
            if rec.partner_id.avoir_vip_exempt:
                rec.avoir_valide_par_id = self.env.user
                rec.avoir_niveau_appro = 'n1'
                continue
        return super().action_valider_avoir()
'''

REGIONAL_SHAPE_SOURCE = '''
class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_valider_avoir(self):
        res = super().action_valider_avoir()
        for rec in self:
            if rec.amount_total > 20000:
                rec.avoir_directeur_regional_id = self._get_directeur_regional()
                rec.avoir_niveau_appro = 'n3'
        return res
'''

GUARDED_SHAPE_SOURCE = '''
class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_valider_avoir(self):
        for rec in self:
            if rec.partner_id.avoir_vip_exempt:
                rec.avoir_valide_par_id = self.env.user
                rec.avoir_niveau_appro = 'n1'
                return True
        return super().action_valider_avoir()
'''

# Real shape found replaying custom_hr_leave_workflow.action_approve
# (sections 139-141): the outer `if` body only computes a LOCAL variable
# (`n2`) and conditionally `raise`s from a NESTED `if` with no `else` --
# the last statement of the OUTER branch is that nested `if`, not a bare
# Return/Raise, so the old last-statement-only check considered it
# 'non-returning'. But the branch never writes any record field: either
# it raises, or it silently does nothing, so an unconditional super() call
# afterwards has no state to clobber. Must NOT be flagged.
HR_LEAVE_SHAPE_SOURCE = '''
class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def action_approve(self):
        for rec in self:
            if rec.conge_urgence and rec.number_of_days > rec.employee_id.remaining_leaves:
                n2 = rec.employee_id.parent_id.parent_id.user_id
                if self.env.user != n2 and not self.env.user.has_group('hr_holidays.group_hr_holidays_manager'):
                    raise ValidationError("blocked")
        return super().action_approve()
'''


def test_detect_unguarded_super_flags_vip_shape():
    """The exact real-world bug shape: conditional branch falls through
    (ends in `continue`, not `return`), unconditional super() call after."""
    warning = detect_unguarded_super(
        VIP_SHAPE_SOURCE, "vip.py", "action_valider_avoir", target_lineno=5, module="vip_mod"
    )
    assert warning is not None
    assert "SUPER() NON GARD" in warning
    assert "[Confiance: FAIBLE" in warning


def test_detect_unguarded_super_no_false_positive_when_super_precedes_condition():
    """Regional shape: super() is called FIRST, the non-returning
    conditional comes AFTER -- no clobbering is possible, must not flag."""
    warning = detect_unguarded_super(
        REGIONAL_SHAPE_SOURCE, "regional.py", "action_valider_avoir", target_lineno=5, module="regional_mod"
    )
    assert warning is None


def test_detect_unguarded_super_no_false_positive_when_branch_returns():
    """A conditional branch that DOES exit early (return) before any
    super() call is a legitimate guard -- must not flag."""
    warning = detect_unguarded_super(
        GUARDED_SHAPE_SOURCE, "guarded.py", "action_valider_avoir", target_lineno=5, module="guarded_mod"
    )
    assert warning is None


def test_detect_unguarded_super_no_false_positive_when_branch_only_raises_no_mutation():
    """Real hr.leave.action_approve shape (sections 139-141): the outer
    branch's last statement is a nested `if ... raise` with no `else`, not
    a bare Return/Raise -- but the branch never writes any record field on
    either path (raise, or fall through doing nothing), so it is not at
    risk of being silently clobbered by the unconditional super() call
    afterwards. Must not flag."""
    warning = detect_unguarded_super(
        HR_LEAVE_SHAPE_SOURCE, "hr_leave.py", "action_approve", target_lineno=5, module="custom_hr_leave_workflow"
    )
    assert warning is None


# Real shape found replaying module 06 (custom_automation_traps) E2E
# (section 151): a conditional inside `for x in own_expense_moves:`
# mutates a record field (an ast.Attribute target, same shape as the real
# VIP bug), but the super() call afterwards is NOT zero-arg -- it is the
# explicit 2-arg form `super(Class, self - own_expense_moves)`, which
# excludes the exact records the branch just mutated. This IS a valid
# guard, just expressed as recordset subtraction instead of return/raise.
# Must NOT be flagged.
RECORDSET_SUBTRACTION_GUARD_SHAPE_SOURCE = '''
class AccountMove(models.Model):
    _inherit = "account.move"

    def _compute_commercial_partner_id(self):
        own_expense_moves = self.filtered(lambda move: move.sudo().expense_sheet_id.payment_mode == 'own_account')
        for move in own_expense_moves:
            if move.expense_sheet_id.payment_mode == 'own_account':
                move.commercial_partner_id = move.partner_id
        super(AccountMove, self - own_expense_moves)._compute_commercial_partner_id()
'''


def test_detect_unguarded_super_no_false_positive_when_super_excludes_mutated_recordset():
    """Real hr_expense.AccountMove._compute_commercial_partner_id shape
    (section 151): the branch mutates a record field with no return/raise
    (same risky shape as VIP on its own), but the later super() call is
    `super(Class, self - own_expense_moves)` -- explicitly excluding the
    exact records the branch just mutated from what super() re-processes.
    Must not flag."""
    warning = detect_unguarded_super(
        RECORDSET_SUBTRACTION_GUARD_SHAPE_SOURCE,
        "account_move.py",
        "_compute_commercial_partner_id",
        target_lineno=5,
        module="hr_expense",
    )
    assert warning is None


# Same recordset-subtraction shape, but with a SECOND, genuinely unguarded
# conditional elsewhere in the method (different loop variable, no
# matching exclusion) -- confirms the guard is tracked per (conditional,
# super-call) pairing, not globally: recognizing one guarded pairing must
# not silently suppress a real, distinct bug in the same method.
RECORDSET_SUBTRACTION_GUARD_WITH_UNRELATED_BUG_SOURCE = '''
class AccountMove(models.Model):
    _inherit = "account.move"

    def _compute_commercial_partner_id(self):
        own_expense_moves = self.filtered(lambda move: move.sudo().expense_sheet_id.payment_mode == 'own_account')
        for move in own_expense_moves:
            if move.expense_sheet_id.payment_mode == 'own_account':
                move.commercial_partner_id = move.partner_id
        for rec in self:
            if rec.partner_id.avoir_vip_exempt:
                rec.avoir_niveau_appro = 'n1'
        super(AccountMove, self - own_expense_moves)._compute_commercial_partner_id()
'''


def test_detect_unguarded_super_still_flags_genuinely_unrelated_conditional():
    """The recordset-subtraction guard must only suppress the ONE
    conditional/super pairing it actually covers -- a second, unrelated
    conditional (different loop var, `self` not excluded for it) in the
    same method must still be flagged."""
    warning = detect_unguarded_super(
        RECORDSET_SUBTRACTION_GUARD_WITH_UNRELATED_BUG_SOURCE,
        "account_move.py",
        "_compute_commercial_partner_id",
        target_lineno=5,
        module="hr_expense",
    )
    assert warning is not None
    assert "avoir_vip_exempt" in warning
    assert "own_account" not in warning


def test_execution_order_is_reverse_of_load_order():
    """resolve_method_override_chain: override_sites is stored on the
    graph in manifest-dependency load order (base first); execution order
    must be the reverse (last-loaded/most-dependent module runs first,
    matching how Odoo actually composes the MRO)."""
    import networkx as nx

    G = nx.DiGraph()
    G.add_node(
        "method:account.move.action_valider_avoir",
        node_type="Method",
        override_sites=[
            {"module": "base_mod", "filepath": "/c/base.py", "lineno": 5, "end_lineno": 10},
            {"module": "regional_mod", "filepath": "/c/regional.py", "lineno": 5, "end_lineno": 10},
            {"module": "vip_mod", "filepath": "/c/vip.py", "lineno": 5, "end_lineno": 10},
        ],
    )

    sites = resolve_method_override_chain(G, "account.move", "action_valider_avoir")

    assert [s.module for s in sites] == ["vip_mod", "regional_mod", "base_mod"]


def test_no_sites_returns_empty_list():
    """A method not present in the graph, or with no override_sites,
    must return an empty list -- never crash."""
    import networkx as nx

    G = nx.DiGraph()
    assert resolve_method_override_chain(G, "account.move", "does_not_exist") == []


# ---------------------------------------------------------------------
# Real-corpus integration test (no mocks): confirms the actual VIP bug
# found in the benchmark is caught end-to-end through the real
# extraction -> resolution -> graph -> resolver pipeline.
# ---------------------------------------------------------------------

ADDONS_PATH = CORE_ADDONS_PATH
REAL_MODULES = [
    "custom_credit_note_approval",
    "custom_credit_note_approval_regional",
    "custom_credit_note_approval_vip",
]


def _build_real_registry_and_graph():
    modules_dict = {}
    for mod_name in REAL_MODULES:
        mod_dir = ADDONS_PATH / mod_name
        manifest = parse_manifest(mod_dir / "__manifest__.py")
        if manifest is None:
            pytest.skip(f"Real module {mod_name} not found at {mod_dir} -- skipping live corpus test.")
        models = []
        for py_file in (mod_dir / "models").glob("*.py"):
            models.extend(extract_odoo_models_from_file(py_file))
        modules_dict[mod_name] = ParsedModule(manifest=manifest, models=models)

    registry = build_module_symbol_registry(modules_dict)
    builder = OdooGraphBuilder(registry, modules_dict)
    G = builder.build_graph()
    return G


def test_real_corpus_execution_order_matches_odoo_mro():
    """Against the real 3-module cascade: vip (most dependent) must run
    first, base (holds _name) must run last."""
    G = _build_real_registry_and_graph()
    sites = resolve_method_override_chain(G, "account.move", "action_valider_avoir")

    assert [s.module for s in sites] == [
        "custom_credit_note_approval_vip",
        "custom_credit_note_approval_regional",
        "custom_credit_note_approval",
    ]


def test_real_corpus_detects_actual_vip_exemption_bug():
    """The real bug this whole  found from: the VIP module's
    override must be flagged, the regional/base ones must not."""
    G = _build_real_registry_and_graph()
    report = analyze_method_override_chain(G, "account.move", "action_valider_avoir")

    assert "custom_credit_note_approval_vip" in report
    assert "SUPER() NON GARD" in report
    # exactly one warning: the base module has no super() call at all, the
    # regional module's super() call precedes its own conditional -- both
    # must stay unflagged (no false positives on the two correct modules).
    assert report.count("SUPER() NON GARD") == 1


def test_real_corpus_hr_expense_commercial_partner_id_not_flagged():
    """Real corpus, not just the synthetic shape above (section 151):
    hr_expense.AccountMove._compute_commercial_partner_id mutates state
    inside `for move in own_expense_moves:` with no return/raise, then
    calls `super(AccountMove, self - own_expense_moves)`, excluding the
    exact records just mutated -- a valid recordset-subtraction guard.
    Must not be flagged against the actual native-Odoo file on disk."""
    filepath = CORE_ADDONS_PATH / "hr_expense" / "models" / "account_move.py"
    if not filepath.exists():
        pytest.skip(f"Real file not found at {filepath} -- skipping live corpus test.")
    source = filepath.read_text(encoding="utf-8")
    warning = detect_unguarded_super(
        source,
        str(filepath),
        "_compute_commercial_partner_id",
        target_lineno=16,
        module="hr_expense",
    )
    assert warning is None


# ---------------------------------------------------------------------
# find_methods_with_unguarded_super: the pre-dispatch noise-reduction
# filter, added 2026-08-06 after the cascade-only guard alone was found
# to fire on every ordinary multiply-overridden method (write, create,
# action_post...) and blow past CI_MAX_HOPS on the real corpus
# (17 hops on Q1.1/Q1.2/Q5.1 in the benchmark rerun).
# ---------------------------------------------------------------------

def test_find_methods_with_unguarded_super_keeps_only_flagged_methods(tmp_path):
    """Two candidate methods share a real >1-site override cascade: one
    has the unguarded-super shape (must be kept), the other is a clean
    cascade with no issue (must be dropped) -- mirrors the real
    account.move situation (many ordinary overridden methods, one real bug)."""
    import networkx as nx

    vip_file = tmp_path / "vip.py"
    vip_file.write_text(VIP_SHAPE_SOURCE)
    clean_base_file = tmp_path / "clean_base.py"
    clean_base_file.write_text("class X:\n    def write(self, vals):\n        return super().write(vals)\n")
    clean_ext_file = tmp_path / "clean_ext.py"
    clean_ext_file.write_text(
        "class X:\n    def write(self, vals):\n        res = super().write(vals)\n        return res\n"
    )

    G = nx.DiGraph()
    G.add_node(
        "method:account.move.action_valider_avoir",
        node_type="Method",
        override_sites=[
            {"module": "base_mod", "filepath": str(vip_file), "lineno": 5, "end_lineno": 11},
            {"module": "vip_mod", "filepath": str(vip_file), "lineno": 5, "end_lineno": 11},
        ],
    )
    G.add_node(
        "method:account.move.write",
        node_type="Method",
        override_sites=[
            {"module": "base_mod", "filepath": str(clean_base_file), "lineno": 2, "end_lineno": 3},
            {"module": "ext_mod", "filepath": str(clean_ext_file), "lineno": 2, "end_lineno": 4},
        ],
    )

    flagged = find_methods_with_unguarded_super(
        G, "account.move", ["action_valider_avoir", "write"]
    )

    assert flagged == ["action_valider_avoir"]


def test_real_corpus_unguarded_super_filter_matches_full_report():
    """On the real 3-module VIP corpus, the cheap filter must agree with
    the full composite tool's own finding: action_valider_avoir flagged,
    nothing else invented."""
    G = _build_real_registry_and_graph()
    from code_intelligence.agent.ci_agent_node.context.agent_tools import find_methods_with_override_cascade

    candidates = find_methods_with_override_cascade(G, "account.move")
    flagged = find_methods_with_unguarded_super(G, "account.move", candidates)

    assert "action_valider_avoir" in flagged
