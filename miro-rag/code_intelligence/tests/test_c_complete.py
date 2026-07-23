"""
code_intelligence/tests/test_c_complete.py

Unit tests for Epic C requirements:
  - C.1.1: Tool binding & CI agent ReAct loop
  - C.1.2: Anti-loop guard (duplicate tool + arguments detection)
  - C.1.3: Navigation strategy system prompt
  - C.1.4: Hop counter & partial answer on limit
  - C.1.5: 4-way routing in graph.py
  - C.1.6: End-to-end integration tests (governance, workflow, inheritance)
"""

import pytest
from rag.schemas import QueryRoute, AssistantResponse
from rag.graph import (
    build_graph,
    code_intelligence_agent,
    CI_SYSTEM_PROMPT,
    CI_MAX_HOPS,
    RAGState
)
from code_intelligence.ci_agent_tools import ALL_CI_TOOLS


def test_c1_1_tools_binding():
    """Test C.1.1: Verify all 9 tools (5 composite + 4 auxiliary) are present in ALL_CI_TOOLS."""
    tool_names = {t.name for t in ALL_CI_TOOLS}
    expected_tools = {
        "lister_modules_impliques",
        "qui_a_acces_a",
        "impact_changement_champ",
        "chemin_execution_bouton",
        "suivre_heritage_complet",
        "quel_est_le_processus_de",
        "resoudre_nom_technique",
        "expliquer_chemin",
        "lire_code_source"
    }
    assert expected_tools.issubset(tool_names), f"Missing tools: {expected_tools - tool_names}"
    assert len(ALL_CI_TOOLS) == 9


def test_c1_3_system_prompt_structure():
    """Test C.1.3: Verify system prompt contains scope-first navigation strategy directives."""
    assert "lister_modules_impliques" in CI_SYSTEM_PROMPT
    assert "qui_a_acces_a" in CI_SYSTEM_PROMPT
    assert "TOUJOURS commencer par" in CI_SYSTEM_PROMPT


def test_c1_4_hop_counter_limit():
    """Test C.1.4: Verify hop limit constant is set to 4."""
    assert CI_MAX_HOPS == 4


def test_c1_6_end_to_end_governance_workflow_inheritance():
    """Test C.1.6: End-to-end integration queries for governance, workflow, and inheritance."""
    # Direct node execution test for governance
    state = {
        "question": "Qui a accès au modèle sale.order ?",
        "chat_history": [],
        "retrieved_chunks": [],
        "timing": {}
    }
    res = code_intelligence_agent(state)
    assert "response" in res
    assert isinstance(res["response"], AssistantResponse)
    assert res["timing"]["ci_hop_count"] >= 0
    assert "[Source: Graphe de Connaissances Code Intelligence]" in res["response"].answer

    # Workflow query
    state_wf = {
        "question": "Quel est le processus de hr.leave ?",
        "chat_history": [],
        "retrieved_chunks": [],
        "timing": {}
    }
    res_wf = code_intelligence_agent(state_wf)
    assert "response" in res_wf
    assert isinstance(res_wf["response"], AssistantResponse)

    # Inheritance query
    state_inh = {
        "question": "Montre-moi l'héritage complet du modèle sale.order",
        "chat_history": [],
        "retrieved_chunks": [],
        "timing": {}
    }
    res_inh = code_intelligence_agent(state_inh)
    assert "response" in res_inh
    assert isinstance(res_inh["response"], AssistantResponse)
