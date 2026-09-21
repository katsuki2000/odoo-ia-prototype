"""Section 879 -- la fusion alias/mention exacte ne doit pas reintroduire un alias
INCLUS dans un alias plus long deja apparie.

PUR-Q1 : "purchase.order" cite litteralement + alias "commande d'achat" (-> purchase.order)
ET "commande" (-> sale.order, inclus dans le precedent). La branche de fusion de la
section 801-802 (STK-Q5) n'appliquait pas le filtre de sous-chaine du chemin alias, donc
sale.order etait ajoute -> analyze_method_override_chain(sale.order) + faits
deterministes hors sujet dans une reponse sur purchase.order.

Graphe synthetique hermetique (pas de dependance a active_graph.json).
"""
import json
from pathlib import Path

import networkx as nx
import pytest

import code_intelligence.agent.loop  # noqa: F401  (ordre d'import : cycle signale en 876)
from code_intelligence.agent.resolver import resolve_business_term

_BANK = Path(__file__).resolve().parents[2] / "tests" / "native_n1_question_bank.json"


@pytest.fixture(scope="module")
def graph():
    G = nx.DiGraph()
    for name in ("purchase.order", "sale.order", "stock.quant", "stock.lot",
                 "cleanup.purge.wizard", "cleanup.purge.wizard.model"):
        G.add_node(f"model:{name}", node_type="Model", name=name)
    return G


def _bank_question(qid: str) -> str:
    bank = json.loads(_BANK.read_text(encoding="utf-8"))
    bank = bank if isinstance(bank, list) else bank.get("questions", bank)
    return next(x["question"] for x in bank if x["id"] == qid)


def test_pur_q1_does_not_pull_sale_order(graph):
    c = resolve_business_term(_bank_question("PUR-Q1"), graph, llm=None)
    assert c.resolved_models == ["purchase.order"], c.resolved_models


def test_subsumed_bare_commande_not_merged_when_longer_alias_matches(graph):
    c = resolve_business_term(
        "Qui peut confirmer une commande d'achat dans purchase.order ?", graph, llm=None)
    assert "sale.order" not in c.resolved_models, c.resolved_models
    assert "purchase.order" in c.resolved_models


def test_merge_of_distinct_alias_still_works_stk_q5_style(graph):
    """Non-regression 801-802 : un terme metier DISTINCT (non inclus dans un autre
    alias apparie) est toujours fusionne avec la mention exacte."""
    c = resolve_business_term(
        "Peut-on voir le numero de serie dans stock.quant ?", graph, llm=None)
    assert "stock.quant" in c.resolved_models
    assert "stock.lot" in c.resolved_models, c.resolved_models


def test_parent_family_alias_is_kept_dc_q1_style(graph):
    """DC-Q1 (OCA) : "purge" (-> cleanup.purge.wizard, parent abstrait) est inclus dans
    "purge de modeles" mais reste de la MEME FAMILLE que la mention exacte
    cleanup.purge.wizard.model : il ne doit pas etre ecarte (la vraie garde est dans
    create() des classes abstraites parentes)."""
    q = ("Un utilisateur simple (base.group_user) peut-il reellement declencher une purge "
         "de modeles orphelins via l'assistant cleanup.purge.wizard.model ?")
    c = resolve_business_term(q, graph, llm=None)
    assert c.resolved_models == ["cleanup.purge.wizard.model", "cleanup.purge.wizard"], c.resolved_models
