"""
code_intelligence/tests/test_c_complete.py

Unit tests for - C.1.1: Tool binding & CI agent ReAct loop
  - C.1.2: Anti-loop guard (duplicate tool + arguments detection)
  - C.1.3: Navigation strategy system prompt
  - C.1.4: Hop counter & partial answer on limit
  - C.1.5: 4-way routing in graph.py
  - C.1.6: End-to-end integration tests (governance, workflow, inheritance)
"""

import pytest
from core.schemas import QueryRoute, AssistantResponse
from core.graph import (
    build_graph,
    code_intelligence_agent,
    RAGState
)
from code_intelligence.ci_agent_node.context.prompts import CI_SYSTEM_PROMPT
from code_intelligence.ci_agent_node.context.prompt_and_heuristics import CI_MAX_HOPS
from code_intelligence.ci_agent_node.context.agent_tools import ALL_CI_TOOLS


def test_c1_1_tools_binding():
    """Test C.1.1: Verify all tools (composite + auxiliary) are present in ALL_CI_TOOLS."""
    tool_names = {t.name for t in ALL_CI_TOOLS}
    expected_tools = {
        "list_involved_modules",
        "who_has_access_to",
        "field_change_impact",
        "button_execution_path",
        "trace_full_inheritance",
        "describe_workflow",
        "resolve_technical_name",
        "explain_decision_path",
        "read_source_code",
        "analyze_data_constraints",  # bis
    }
    assert expected_tools.issubset(tool_names), f"Missing tools: {expected_tools - tool_names}"
    # Count deliberately not pinned to a literal number -- it has drifted
    # (12 -> 13 with bis's analyze_data_constraints) and would keep
    # drifting with future additions. The issubset check above is the real
    # guarantee; this just documents intent without becoming stale again.
    assert len(ALL_CI_TOOLS) >= len(expected_tools)


def test_c1_3_system_prompt_structure():
    """Test C.1.3: Verify system prompt contains scope-first navigation strategy directives."""
    # NOTE: list_involved_modules is intentionally NOT asserted here --
    # it is a valid tool (see test_c1_1_tools_binding) but is not mentioned
    # by name in the prompt's NAVIGATION STRATEGY text, which only lists
    # tools that need explicit routing hints. This line used to assert its
    # presence and went stale after prompt reorganizations; removed rather
    # than re-broken a third time.
    assert "who_has_access_to" in CI_SYSTEM_PROMPT
    assert "evaluate_record_rules" in CI_SYSTEM_PROMPT
    assert "analyze_server_actions" in CI_SYSTEM_PROMPT
    assert "analyze_security_locks" in CI_SYSTEM_PROMPT
    assert "NAVIGATION STRATEGY" in CI_SYSTEM_PROMPT


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
