"""
todo/contexte.txt sections 934/935, point J: analyze_security_locks only reads
the queried model's own source. ACC-Q2 (account.move) answered "bloque pour
tous" because the real group-based exemption lives in
res.company._get_user_fiscal_lock_date(), reached from
account.move._check_fiscalyear_lock_date() through the company_id field --
a related-model call never followed by the same-model-only mechanism of
section 934.
"""

import pytest

from code_intelligence.rules.relational_callees import (
    extract_relational_lock_callees,
    get_relational_fields,
    source_is_security_relevant,
)

_CHECK_FISCALYEAR_LOCK_DATE = '''
    def _check_fiscalyear_lock_date(self):
        for move in self:
            lock_date = move.company_id._get_user_fiscal_lock_date()
            if move.date <= lock_date:
                if self.user_has_groups('account.group_account_manager'):
                    message = "locked, adviser"
                else:
                    message = "locked"
                raise UserError(message)
        return True
'''

_UNRELATED_METHOD = '''
    def _compute_amount(self):
        for move in self:
            move.amount_total = move.company_id.currency_id.round(move.amount_untaxed)
'''


def test_relational_callee_found_inside_security_relevant_method():
    fields = {"company_id": "res.company"}
    result = extract_relational_lock_callees(_CHECK_FISCALYEAR_LOCK_DATE, fields)
    assert result == [
        ("_check_fiscalyear_lock_date", "company_id", "_get_user_fiscal_lock_date", "res.company"),
    ]


def test_relational_callee_ignored_outside_security_relevant_method():
    fields = {"company_id": "res.company"}
    assert extract_relational_lock_callees(_UNRELATED_METHOD, fields) == []


def test_callee_source_relevance_requires_group_check_or_security_raise():
    assert source_is_security_relevant(_CHECK_FISCALYEAR_LOCK_DATE)
    assert not source_is_security_relevant(_UNRELATED_METHOD)
    assert not source_is_security_relevant("def broken(:")


def test_unknown_field_is_not_followed():
    result = extract_relational_lock_callees(_CHECK_FISCALYEAR_LOCK_DATE, {"other_field": "res.other"})
    assert result == []


def test_unparsable_source_yields_nothing():
    assert extract_relational_lock_callees("def broken(:", {"company_id": "res.company"}) == []


def test_get_relational_fields_from_graph():
    import networkx as nx
    G = nx.DiGraph()
    G.add_node("model:account.move")
    G.add_node("field:account.move.company_id", name="company_id", field_type="many2one", comodel_name="res.company")
    G.add_node("field:account.move.partner_ids", name="partner_ids", field_type="many2many", comodel_name="res.partner")
    G.add_edge("model:account.move", "field:account.move.company_id", edge_type="HAS_FIELD")
    G.add_edge("model:account.move", "field:account.move.partner_ids", edge_type="HAS_FIELD")
    assert get_relational_fields(G, "account.move") == {"company_id": "res.company"}


@pytest.fixture(scope="module")
def real_graph():
    from code_intelligence.graph.loader import get_code_intelligence_graph
    return get_code_intelligence_graph()


def test_acc_q2_reads_user_fiscal_lock_date_on_related_model(real_graph):
    from types import SimpleNamespace
    from code_intelligence.agent.context import DispatchContext
    from code_intelligence.agent.predispatch_access import dispatch_security_locks
    from code_intelligence.agent.tool_helpers import set_graph_ref
    from code_intelligence.agent.tools import ALL_CI_TOOLS

    class FakeTraceLogger:
        def log_hop(self, *args, **kwargs):
            pass

    set_graph_ref(real_graph)
    ctx = DispatchContext(
        G=real_graph,
        concept=SimpleNamespace(is_resolved=True, resolved_models=["account.move"], resolved_modules=[]),
        question=(
            "Un Billing Administrator (group_account_manager) est-il bloque par le "
            "period_lock_date de la societe, ou seulement par le fiscalyear_lock_date ?"
        ),
        tool_map={t.name: t for t in ALL_CI_TOOLS},
        resolved_user_group_xmlids=[],
        trace_logger=FakeTraceLogger(),
        trace_id="test",
        hop_cap=20,
    )
    dispatch_security_locks(ctx)

    related_obs = next(
        o for o in ctx.tool_observations if "_get_user_fiscal_lock_date" in o and "def " in o
    )
    assert "period_lock_date" in related_obs
    assert "fiscalyear_lock_date" in related_obs
    assert "MODÈLE RELIÉ" in related_obs
    assert "RELATED MODEL" in ctx.system_prompt_suffix
    assert not any("def compare_amounts" in o for o in ctx.tool_observations)
