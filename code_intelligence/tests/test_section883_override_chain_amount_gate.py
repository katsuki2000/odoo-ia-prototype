"""Section 883 -- la branche "approval wording" d'`override_chain_targets` ne doit
dispatcher `analyze_method_override_chain` que si un montant est cite (meme gate que
`who_has_access_targets`). PUR-Q1 ("...distingue...un acheteur d'un manager...", aucun
montant) dispatchait a tort sur une methode sans rapport (`_prepare_invoice`), privant
la garde de distinction securitaire (786-790) de son budget de hops.

`find_methods_with_override_cascade` / `find_methods_with_override_risk_findings` sont
monkeypatchees (elles lisent de vrais fichiers source) : ce test cible la logique du
GATE dans `override_chain_targets`, pas le pipeline de detection de risque lui-meme
(couvert ailleurs).
"""
import json
from pathlib import Path

import networkx as nx
import pytest

import code_intelligence.agent.loop  # noqa: F401  (ordre d'import : cycle signale en 876)
import code_intelligence.agent.tool_helpers as tool_helpers
import code_intelligence.rules.overrides as overrides_mod
from code_intelligence.agent.forced_dispatch_predicates import override_chain_targets
from code_intelligence.agent.resolver import resolve_business_term

_BANK = Path(__file__).resolve().parents[2] / "tests" / "native_n1_question_bank.json"


@pytest.fixture(scope="module")
def graph():
    G = nx.DiGraph()
    for name in ("purchase.order", "account.move"):
        G.add_node(f"model:{name}", node_type="Model", name=name)
    return G


@pytest.fixture(autouse=True)
def stub_override_pipeline(monkeypatch):
    """Toute methode candidate est consideree a risque : isole le gate testé du
    pipeline reel de lecture de fichiers/detection de risque."""
    monkeypatch.setattr(
        tool_helpers, "find_methods_with_override_cascade",
        lambda G, model: ["some_method"],
    )
    monkeypatch.setattr(
        overrides_mod, "find_methods_with_override_risk_findings",
        lambda G, model, candidates: list(candidates),
    )


def _bank_question(qid: str) -> str:
    bank = json.loads(_BANK.read_text(encoding="utf-8"))
    bank = bank if isinstance(bank, list) else bank.get("questions", bank)
    return next(x["question"] for x in bank if x["id"] == qid)


def test_pur_q1_no_longer_dispatches_override_chain(graph):
    q = _bank_question("PUR-Q1")
    concept = resolve_business_term(q, graph, llm=None)
    assert override_chain_targets(q, concept, graph) == []


def test_approval_with_amount_still_dispatches(graph):
    q = "Qui peut approuver un avoir de plus de 500 000 Ar sur account.move ?"
    concept = resolve_business_term(q, graph, llm=None)
    pairs = override_chain_targets(q, concept, graph)
    assert pairs and all(m == "account.move" for m, _ in pairs)


def test_approval_wording_alone_without_amount_no_longer_dispatches(graph):
    q = "Qui peut approuver un avoir sur account.move, sans condition de montant ?"
    concept = resolve_business_term(q, graph, llm=None)
    assert override_chain_targets(q, concept, graph) == []


def test_method_wording_still_dispatches_without_amount(graph):
    """Non-regression : une question qui nomme explicitement une methode/override
    reste dispatchee, independamment de tout montant (PUR-Q2/PR-Q3-style)."""
    q = "Quelle methode ecrase button_confirm sur purchase.order et que fait-elle ?"
    concept = resolve_business_term(q, graph, llm=None)
    assert override_chain_targets(q, concept, graph) != []


def test_gate_is_what_fixes_pur_q1(monkeypatch, graph):
    """Temoin negatif : sans le gate montant, PUR-Q1 dispatche de nouveau."""
    import code_intelligence.agent.forced_dispatch_predicates as fp
    monkeypatch.setattr(fp, "_extract_amount", lambda q: 1.0)
    q = _bank_question("PUR-Q1")
    concept = resolve_business_term(q, graph, llm=None)
    assert override_chain_targets(q, concept, graph) != []
