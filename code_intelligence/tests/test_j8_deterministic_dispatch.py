"""
miro-rag/code_intelligence/tests/test_j8_deterministic_dispatch.py

Unit tests for J8/J9 deterministic pre-dispatch triggers and helper functions.
Tested independently from LLM bounded interpretation to ensure no accidental regressions.
"""

import networkx as nx
from code_intelligence.ci_agent_node.agent_tools import find_server_action_nodes
from core.graph import (
    _question_mentions_amount,
    _question_is_approval_related,
    _question_suggests_automation_bypass,
)


def test_find_server_action_nodes_helper():
    """Verify standalone helper correctly finds ServerAction nodes targeting a model."""
    G = nx.DiGraph()
    G.add_node("model:account.move", node_type="Model", name="account.move")
    G.add_node(
        "server_action:custom_automation_traps.action_auto_validate",
        node_type="ServerAction",
        xml_id="custom_automation_traps.action_auto_validate",
        model_id="account.move",
        code="record.sudo().action_valider_avoir()",
    )
    G.add_edge(
        "server_action:custom_automation_traps.action_auto_validate",
        "model:account.move",
        edge_type="TARGETS_MODEL",
    )

    sa_nodes = find_server_action_nodes(G, "account.move")
    assert len(sa_nodes) == 1
    assert sa_nodes[0][0] == "server_action:custom_automation_traps.action_auto_validate"

    # Model without server actions returns empty list
    assert find_server_action_nodes(G, "purchase.order") == []


def test_automation_pattern_trigger():
    """Verify _AUTOMATION_PATTERN triggers ONLY on automation/bypass wording (Q5.1) and NOT on standard approval/visibility questions."""
    q51 = "Est-ce que tous les avoirs fournisseurs passent par les mêmes règles d'approbation ?"
    assert _question_suggests_automation_bypass(q51) is True

    q11 = "Qui a le permission d'approuver un avoir de 25 000€ pour un client normal (pas VIP) ?"
    assert _question_suggests_automation_bypass(q11) is False

    q31 = "Qui a le permission d'approuver une demande d'achat de 15 000€ ?"
    assert _question_suggests_automation_bypass(q31) is False

    q62 = "Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?"
    assert _question_suggests_automation_bypass(q62) is False


def test_amount_and_approval_triggers():
    """Verify _AMOUNT_PATTERN and _APPROVAL_PATTERN correctly scope security lock pre-dispatch."""
    q31 = "Qui a le permission d'approuver une demande d'achat de 15 000€ ?"
    assert _question_mentions_amount(q31) is True
    assert _question_is_approval_related(q31) is True

    q62 = "Un utilisateur qui n'appartient à AUCUN des deux groupes (ni régional, ni national) peut-il voir ce même avoir de 80 000€ ?"
    assert _question_mentions_amount(q62) is True
    assert _question_is_approval_related(q62) is False  # 'voir' is visibility, not approval
