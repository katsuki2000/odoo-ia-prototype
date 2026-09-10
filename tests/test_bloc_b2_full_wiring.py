"""
tests/test_bloc_b2_full_wiring.py

Bloc B2 (todo/contexte.txt section 622-625), etape 3/4: extends the
wiring already confirmed for the 2 pilots (who_has_access_to/CI,
get_total_sales/ORM, see tests/test_bloc_b2_pilot_wiring.py) to the 20
remaining CI/ORM @tool wrappers. Each test monkeypatches the wrapper's
underlying data-producing function/object (never core.evidence_collector
itself) and checks the wrapper's own record_evidence() call actually
reaches the turn accumulator -- same technique as
test_ci_agent_tools_resolution.py's monkeypatch of a deferred-import
target and test_bloc_b2_pilot_wiring.py's existing pilot tests.
"""

from unittest.mock import patch, MagicMock

import networkx as nx
import pytest

from core.evidence import Evidence, EvidenceSourceType, make_evidence
from core.evidence_collector import (
    _turn_evidence_ctx,
    start_evidence_collection,
    collect_and_clear_evidence,
)


@pytest.fixture(autouse=True)
def _reset_turn_evidence_ctx():
    _turn_evidence_ctx.set(None)
    yield
    _turn_evidence_ctx.set(None)


def _one_evidence(claim="fake fact"):
    return make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=claim, source="test:fixture", value=True, scope={},
    )


# ── CI: 5 Composites (who_has_access_to already covered by the pilot) ────

class TestFieldChangeImpactWrapperRecordsEvidence:
    def test_records_evidence(self, monkeypatch):
        from code_intelligence.ci_agent_node import agent_tools as ci_agent_tools

        G = nx.DiGraph()
        G.add_node("model:sale.order", node_type="Model", name="sale.order")
        ci_agent_tools.set_graph_ref(G)

        fake_evidence = [_one_evidence()]

        class _FakeResult:
            summary_text = "OK"
            upstream_triggers = []
            downstream_computed_fields = []
            evidence = fake_evidence

        monkeypatch.setattr(
            "code_intelligence.deterministic.field_impact.field_change_impact",
            lambda G, field_name, model_name: _FakeResult(),
        )

        start_evidence_collection()
        ci_agent_tools.field_change_impact.invoke(
            {"field_name": "amount_total", "model_name": "sale.order"}
        )
        assert collect_and_clear_evidence() == fake_evidence


class TestButtonExecutionPathWrapperRecordsEvidence:
    def test_records_evidence(self, monkeypatch):
        from code_intelligence.ci_agent_node import agent_tools as ci_agent_tools

        G = nx.DiGraph()
        G.add_node("model:sale.order", node_type="Model", name="sale.order")
        ci_agent_tools.set_graph_ref(G)

        fake_evidence = [_one_evidence()]

        class _FakeResult:
            summary_text = "OK"
            execution_steps = []
            evidence = fake_evidence

        monkeypatch.setattr(
            "code_intelligence.deterministic.button_path.button_execution_path",
            lambda G, button_name, model_name, user_groups=None: _FakeResult(),
        )

        start_evidence_collection()
        ci_agent_tools.button_execution_path.invoke(
            {"button_name": "action_confirm", "model_name": "sale.order"}
        )
        assert collect_and_clear_evidence() == fake_evidence


class TestTraceFullInheritanceWrapperRecordsEvidence:
    def test_records_evidence(self, monkeypatch):
        from code_intelligence.ci_agent_node import agent_tools as ci_agent_tools

        G = nx.DiGraph()
        G.add_node("model:sale.order", node_type="Model", name="sale.order")
        ci_agent_tools.set_graph_ref(G)

        fake_evidence = [_one_evidence()]

        class _FakeResult:
            summary_text = "OK"
            evidence = fake_evidence

        monkeypatch.setattr(
            "code_intelligence.deterministic.inheritance_chain.trace_full_inheritance",
            lambda G, model_name: _FakeResult(),
        )

        start_evidence_collection()
        ci_agent_tools.trace_full_inheritance.invoke({"model_name": "sale.order"})
        assert collect_and_clear_evidence() == fake_evidence


class TestDescribeWorkflowWrapperRecordsEvidence:
    def test_records_evidence(self, monkeypatch):
        from code_intelligence.ci_agent_node import agent_tools as ci_agent_tools

        G = nx.DiGraph()
        G.add_node("model:sale.order", node_type="Model", name="sale.order")
        ci_agent_tools.set_graph_ref(G)

        fake_evidence = [_one_evidence()]

        class _FakeResult:
            summary_text = "OK"
            evidence = fake_evidence

        monkeypatch.setattr(
            "code_intelligence.deterministic.workflow_process.describe_workflow",
            lambda G, model_name: _FakeResult(),
        )

        start_evidence_collection()
        ci_agent_tools.describe_workflow.invoke({"model_name": "sale.order"})
        assert collect_and_clear_evidence() == fake_evidence


class TestEvaluateRecordRulesWrapperRecordsEvidence:
    def test_records_evidence(self, monkeypatch):
        from code_intelligence.ci_agent_node import agent_tools as ci_agent_tools

        G = nx.DiGraph()
        G.add_node("model:sale.order", node_type="Model", name="sale.order")
        ci_agent_tools.set_graph_ref(G)

        fake_evidence = [_one_evidence()]

        class _FakeResult:
            summary_text = "OK"
            evidence = fake_evidence

        monkeypatch.setattr(
            "code_intelligence.deterministic.record_rules.evaluate_record_rules",
            lambda G, model_name, permission="read", user_groups=None: _FakeResult(),
        )

        start_evidence_collection()
        ci_agent_tools.evaluate_record_rules.invoke({"model_name": "sale.order"})
        assert collect_and_clear_evidence() == fake_evidence


# ── CI: Auxiliary (list_involved_modules) ─────────────────────────────────

class TestListInvolvedModulesWrapperRecordsEvidence:
    def test_records_evidence(self, monkeypatch):
        from code_intelligence.ci_agent_node import agent_tools as ci_agent_tools

        G = nx.DiGraph()
        G.add_node("model:sale.order", node_type="Model", name="sale.order")
        ci_agent_tools.set_graph_ref(G)

        fake_evidence = [_one_evidence()]

        class _FakeResult:
            modules = [("sale", "declares")]
            evidence = fake_evidence

        monkeypatch.setattr(
            "code_intelligence.ci_agent_node.auxiliary_tools.list_involved_modules_with_evidence",
            lambda G, model_name: _FakeResult(),
        )

        start_evidence_collection()
        ci_agent_tools.list_involved_modules.invoke({"model_name": "sale.order"})
        assert collect_and_clear_evidence() == fake_evidence


# ── CI: 4 Analyse ──────────────────────────────────────────────────────────

class TestAnalyzeServerActionsWrapperRecordsEvidence:
    def test_records_evidence(self, monkeypatch):
        from code_intelligence.ci_agent_node import agent_tools as ci_agent_tools

        G = nx.DiGraph()
        G.add_node("model:sale.order", node_type="Model", name="sale.order")
        ci_agent_tools.set_graph_ref(G)

        fake_evidence = [_one_evidence("sudo() detected")]

        class _FakeAnalysis:
            summary_text = "OK"
            evidence = fake_evidence

        monkeypatch.setattr(
            ci_agent_tools, "find_server_action_nodes",
            lambda G, model_name: [("server_action:x.y", {"xml_id": "x.y", "code": "pass"})],
        )
        monkeypatch.setattr(
            ci_agent_tools, "_trace_invoked_methods", lambda G, model_name, code: ""
        )
        monkeypatch.setattr(
            "code_intelligence.server_actions.analyze_server_action_code",
            lambda **kwargs: _FakeAnalysis(),
        )
        monkeypatch.setattr(
            "code_intelligence.server_actions.interpret_server_action_with_llm",
            lambda analysis, code, llm: analysis,
        )

        start_evidence_collection()
        ci_agent_tools.analyze_server_actions.invoke({"model_name": "sale.order"})
        assert collect_and_clear_evidence() == fake_evidence


class TestAnalyzeSecurityLocksWrapperRecordsEvidence:
    def test_records_evidence(self, monkeypatch, tmp_path):
        from code_intelligence.ci_agent_node import agent_tools as ci_agent_tools

        G = nx.DiGraph()
        G.add_node("model:sale.order", node_type="Model", name="sale.order")
        ci_agent_tools.set_graph_ref(G)

        src_file = tmp_path / "sale_order.py"
        src_file.write_text("class SaleOrder: pass", encoding="utf-8")

        fake_evidence = [_one_evidence("no sudo() call")]

        class _FakeAnalysis:
            summary_text = "OK"
            evidence = fake_evidence

        monkeypatch.setattr(
            ci_agent_tools, "find_model_source_filepaths",
            lambda G, model_name: [str(src_file)],
        )
        monkeypatch.setattr(
            "code_intelligence.security.analyze_python_security_locks",
            lambda code, filepath: _FakeAnalysis(),
        )

        start_evidence_collection()
        ci_agent_tools.analyze_security_locks.invoke({"model_name": "sale.order"})
        assert collect_and_clear_evidence() == fake_evidence


class TestAnalyzeMethodOverrideChainWrapperRecordsEvidence:
    def test_records_evidence(self, monkeypatch):
        from code_intelligence.ci_agent_node import agent_tools as ci_agent_tools

        G = nx.DiGraph()
        G.add_node("model:sale.order", node_type="Model", name="sale.order")
        ci_agent_tools.set_graph_ref(G)

        fake_evidence = [_one_evidence()]

        class _FakeResult:
            summary_text = "OK"
            evidence = fake_evidence

        monkeypatch.setattr(
            "code_intelligence.overrides.analyze_method_override_chain_with_evidence",
            lambda G, model_name, method_name, llm=None: _FakeResult(),
        )

        start_evidence_collection()
        ci_agent_tools.analyze_method_override_chain.invoke(
            {"model_name": "sale.order", "method_name": "action_confirm"}
        )
        assert collect_and_clear_evidence() == fake_evidence


class TestAnalyzeDataConstraintsWrapperRecordsEvidence:
    def test_records_evidence(self, monkeypatch):
        from code_intelligence.ci_agent_node import agent_tools as ci_agent_tools

        G = nx.DiGraph()
        G.add_node("model:sale.order", node_type="Model", name="sale.order")
        ci_agent_tools.set_graph_ref(G)

        fake_evidence = [_one_evidence()]

        class _FakeResult:
            summary_text = "OK"
            evidence = fake_evidence

        monkeypatch.setattr(
            ci_agent_tools, "find_model_source_filepaths",
            lambda G, model_name: ["fake/path/sale_order.py"],
        )
        monkeypatch.setattr(
            "code_intelligence.data_constraints.analyzer.analyze_data_constraints_from_filepaths",
            lambda model_name, filepaths: _FakeResult(),
        )

        start_evidence_collection()
        ci_agent_tools.analyze_data_constraints.invoke({"model_name": "sale.order"})
        assert collect_and_clear_evidence() == fake_evidence


# ── ORM: sales.py (get_total_sales already covered by the pilot) ─────────

def _with_uid(fn):
    from erp_data._odoo_helpers import odoo_uid_ctx
    token = odoo_uid_ctx.set(1)
    try:
        return fn()
    finally:
        odoo_uid_ctx.reset(token)


class TestGetOrderCountWrapperRecordsEvidence:
    def test_records_evidence(self):
        from erp_data.tools.sales import get_order_count

        start_evidence_collection()
        with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
            mock_read_group.return_value = [{"__count": 3}]
            result = _with_uid(lambda: get_order_count.invoke(
                {"client": "", "periode": "", "statut": "toutes"}
            ))
        assert isinstance(result, str)
        dossier = collect_and_clear_evidence()
        assert len(dossier) == 1
        assert dossier[0].source_type == EvidenceSourceType.ORM


class TestGetAverageSalesWrapperRecordsEvidence:
    def test_records_evidence(self):
        from erp_data.tools.sales import get_average_sales

        start_evidence_collection()
        with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
            mock_read_group.return_value = [{"amount_total": 1000.0, "__count": 2}]
            result = _with_uid(lambda: get_average_sales.invoke(
                {"client": "", "periode": "toutes", "statut": "toutes"}
            ))
        assert isinstance(result, str)
        dossier = collect_and_clear_evidence()
        assert len(dossier) == 1
        assert dossier[0].source_type == EvidenceSourceType.ORM


class TestGetSaleDetailsWrapperRecordsEvidence:
    def test_records_evidence(self):
        from erp_data.tools.sales import get_sale_details

        start_evidence_collection()
        with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
            mock_search_read.return_value = []
            result = _with_uid(lambda: get_sale_details.invoke(
                {"client": "Dupont", "statut": "toutes", "limite": 0}
            ))
        assert isinstance(result, str)
        dossier = collect_and_clear_evidence()
        assert len(dossier) == 1  # empty-result branch: single negative Evidence
        assert dossier[0].source_type == EvidenceSourceType.ORM


# ── ORM: accounting.py ────────────────────────────────────────────────────

class TestGetTotalInvoicesWrapperRecordsEvidence:
    def test_records_evidence(self):
        from erp_data.tools.accounting import get_total_invoices

        start_evidence_collection()
        with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
            mock_read_group.return_value = [{"amount_total": 500.0, "partner_id": [1, "Dupont"]}]
            result = _with_uid(lambda: get_total_invoices.invoke(
                {"client": "Dupont", "statut": "toutes"}
            ))
        assert isinstance(result, str)
        dossier = collect_and_clear_evidence()
        assert len(dossier) == 1
        assert dossier[0].source_type == EvidenceSourceType.ORM


class TestGetPeriodRevenueWrapperRecordsEvidence:
    def test_records_evidence(self):
        from erp_data.tools.accounting import get_period_revenue

        start_evidence_collection()
        with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
            mock_read_group.return_value = [{"amount_total": 700.0}]
            result = _with_uid(lambda: get_period_revenue.invoke({"periode": "toutes"}))
        assert isinstance(result, str)
        dossier = collect_and_clear_evidence()
        assert len(dossier) == 1
        assert dossier[0].source_type == EvidenceSourceType.ORM


# ── ORM: crm.py ─────────────────────────────────────────────────────────

class TestSearchPartnerWrapperRecordsEvidence:
    def test_records_evidence(self):
        from erp_data.tools.crm import search_partner

        start_evidence_collection()
        with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
            mock_search_read.side_effect = [
                [],  # res.company lookup
                [{"name": "Dupont", "email": "d@x.com", "phone": "0102", "city": "Paris"}],
            ]
            result = _with_uid(lambda: search_partner.invoke({"nom": "Dupont", "limite": 0}))
        assert isinstance(result, str)
        dossier = collect_and_clear_evidence()
        assert len(dossier) == 1
        assert dossier[0].source_type == EvidenceSourceType.ORM


class TestGetRecentTicketsWrapperRecordsEvidence:
    def test_records_evidence(self):
        from erp_data.tools.crm import get_recent_tickets

        start_evidence_collection()
        with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
            mock_search_read.return_value = []
            result = _with_uid(lambda: get_recent_tickets.invoke(
                {"client": "", "limite": 0, "statut": None}
            ))
        assert isinstance(result, str)
        dossier = collect_and_clear_evidence()
        assert len(dossier) == 1  # empty-result branch: single negative Evidence
        assert dossier[0].source_type == EvidenceSourceType.ORM


# ── ORM: inventory.py ──────────────────────────────────────────────────

class TestGetProductStockWrapperRecordsEvidence:
    def test_records_evidence(self):
        from erp_data.tools.inventory import get_product_stock

        start_evidence_collection()
        with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
            mock_read_group.return_value = [{"quantity": 10.0, "reserved_quantity": 2.0}]
            result = _with_uid(lambda: get_product_stock.invoke({"produit": "Chaise"}))
        assert isinstance(result, str)
        dossier = collect_and_clear_evidence()
        assert len(dossier) == 2  # qty + reserved
        assert all(e.source_type == EvidenceSourceType.ORM for e in dossier)


class TestGetOrderStatusWrapperRecordsEvidence:
    def test_records_evidence(self):
        from erp_data.tools.inventory import get_order_status

        start_evidence_collection()
        with patch("erp_data._odoo_helpers.connector.search_read") as mock_search_read:
            mock_search_read.return_value = [
                {"state": "sale", "amount_total": 100.0, "partner_id": [1, "Dupont"]}
            ]
            result = _with_uid(lambda: get_order_status.invoke({"reference": "S00042"}))
        assert isinstance(result, str)
        dossier = collect_and_clear_evidence()
        assert len(dossier) == 2  # state + partner
        assert all(e.source_type == EvidenceSourceType.ORM for e in dossier)


class TestListOutOfStockProductsWrapperRecordsEvidence:
    def test_records_evidence(self):
        from erp_data.tools.inventory import list_out_of_stock_products

        start_evidence_collection()
        with patch("erp_data._odoo_helpers.connector.read_group") as mock_read_group:
            mock_read_group.return_value = [
                {"product_id": [1, "Chaise"], "quantity": 0.0},
            ]
            result = _with_uid(lambda: list_out_of_stock_products.invoke({}))
        assert isinstance(result, str)
        dossier = collect_and_clear_evidence()
        assert len(dossier) == 1
        assert dossier[0].source_type == EvidenceSourceType.ORM
