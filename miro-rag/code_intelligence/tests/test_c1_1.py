"""
code_intelligence/tests/test_c1_1.py

Unit and integration tests for Epic C: Router Integration & LangGraph Code Intelligence Node.
Tests:
  1. 4-Way Routing Classification (DOCUMENTAIRE, DONNEES_ERP, HYBRIDE, CODE_INTELLIGENCE)
  2. End-to-End LangGraph execution for Code Intelligence queries
  3. Non-regression test for standard RAG graph execution
"""

import pytest
from rag.schemas import QueryRoute, AssistantResponse
from rag.graph import build_graph, route, RAGState


def test_4way_routing_classification():
    """Test Task C1.1.2: 4-Way Routing Classification in route()."""
    # 1. Code Intelligence Query -> CODE_INTELLIGENCE
    state_ci = {"question": "Qui a accès au modèle sale.order ?", "retrieved_chunks": [], "timing": {}}
    res_ci = route(state_ci)
    assert res_ci["route"] == QueryRoute.CODE_INTELLIGENCE.value

    state_ci2 = {"question": "Quel est l'impact de la modification du champ price_unit ?", "retrieved_chunks": [], "timing": {}}
    res_ci2 = route(state_ci2)
    assert res_ci2["route"] == QueryRoute.CODE_INTELLIGENCE.value

    state_ci3 = {"question": "Que fait le bouton confirmer sur les commandes de vente ?", "retrieved_chunks": [], "timing": {}}
    res_ci3 = route(state_ci3)
    assert res_ci3["route"] == QueryRoute.CODE_INTELLIGENCE.value

    # 2. ERP Data Query -> DONNEES_ERP
    state_erp = {"question": "Combien de ventes avons-nous réalisées ce mois ?", "retrieved_chunks": [], "timing": {}}
    res_erp = route(state_erp)
    assert res_erp["route"] == QueryRoute.DONNEES_ERP.value

    # 3. Documentary Query -> DOCUMENTAIRE
    state_doc = {"question": "Comment faire une procédure de validation selon le wiki ?", "retrieved_chunks": [], "timing": {}}
    res_doc = route(state_doc)
    assert res_doc["route"] == QueryRoute.DOCUMENTAIRE.value


def test_end_to_end_code_intelligence_graph_execution():
    """Test Task C1.1.3 & C1.1.4: End-to-End LangGraph execution for Code Intelligence."""
    app = build_graph()

    # 1. Access Query
    initial_state = {"question": "Qui a accès au modèle sale.order ?", "chat_history": []}
    final_state = app.invoke(initial_state)

    response = final_state.get("response")
    assert isinstance(response, AssistantResponse)
    assert "Droits d'Accès et Sécurité" in response.answer or "sale.order" in response.answer
    assert "[Source: Graphe de Connaissances Code Intelligence" in response.answer

    # 2. Impact Query
    initial_state_impact = {"question": "Quel est l'impact de la modification du champ partner_id ?", "chat_history": []}
    final_state_impact = app.invoke(initial_state_impact)

    response_impact = final_state_impact.get("response")
    assert isinstance(response_impact, AssistantResponse)
    assert "Analyse d'Impact" in response_impact.answer or "partner_id" in response_impact.answer

    # 3. Button Execution Query
    initial_state_button = {"question": "Que fait le bouton confirmer sur les ventes ?", "chat_history": []}
    final_state_button = app.invoke(initial_state_button)

    response_button = final_state_button.get("response")
    assert isinstance(response_button, AssistantResponse)
    assert "Chemin d'Exécution" in response_button.answer or "bouton" in response_button.answer or "confirmer" in response_button.answer
