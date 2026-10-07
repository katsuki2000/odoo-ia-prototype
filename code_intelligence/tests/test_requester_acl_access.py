import networkx as nx

from code_intelligence.agent.predispatch_access import (
    _question_asks_requester_access,
    build_requester_acl_answer,
)
from code_intelligence.rules.access_evaluator import requester_acl_summary


def access_graph():
    graph = nx.DiGraph()
    graph.add_node("model:account.move", node_type="Model")
    graph.add_node("acl:account.move", node_type="AccessEntry", perm_create=True, perm_read=True)
    graph.add_edge("model:account.move", "acl:account.move", edge_type="GRANTED_BY")
    graph.add_node("group:account.group_account_invoice", node_type="Group")
    graph.add_edge("acl:account.move", "group:account.group_account_invoice", edge_type="APPLIES_TO_GROUP")
    graph.add_node("group:account.group_account_manager", node_type="Group")
    graph.add_edge(
        "group:account.group_account_manager",
        "group:account.group_account_invoice",
        edge_type="IMPLIES",
    )
    return graph


def test_requester_acl_verdict_uses_effective_implied_groups():
    summary, evidence, verdicts = requester_acl_summary(
        access_graph(), "account.move", ["account.group_account_manager"], True,
    )

    assert "CREATE: GRANTED" in summary
    assert "READ: GRANTED" in summary
    assert "WRITE: DENIED" in summary
    assert "model-level ACL decision only" in summary
    create_evidence = next(item for item in evidence if item.source.endswith(":create"))
    assert create_evidence.value["granted"] is True
    assert create_evidence.scope["requester_groups"] == [
        "account.group_account_invoice", "account.group_account_manager",
    ]
    assert verdicts["create"] is True and verdicts["write"] is False


def test_requester_acl_verdict_does_not_guess_when_groups_are_unresolved():
    summary, evidence, verdicts = requester_acl_summary(access_graph(), "account.move", [], False)

    assert "could not be fully resolved" in summary
    assert "do not infer" in summary
    assert evidence == []
    assert verdicts is None


def test_requester_acl_verdict_does_not_guess_when_model_is_missing():
    summary, evidence, verdicts = requester_acl_summary(access_graph(), "missing.model", [], True)

    assert "model 'missing.model' is not present" in summary
    assert evidence == []
    assert verdicts is None


def test_personal_access_question_detection_is_narrow():
    assert _question_asks_requester_access("Puis-je créer une pièce comptable ?")
    assert _question_asks_requester_access("Can I read account.move?")
    assert not _question_asks_requester_access("Quels groupes peuvent lire account.move ?")


def test_personal_acl_answer_uses_deterministic_requester_verdict():
    answer = build_requester_acl_answer(
        "Puis-je créer les enregistrements du modèle « Pièce comptable » ?",
        "fr_FR",
        {"account.move": {"create": False, "read": True}},
    )

    assert answer == "Non. Vous ne pouvez pas créer les enregistrements du modèle « Pièce comptable » d'après les ACL de votre compte."


def test_personal_acl_answer_abstains_when_identity_is_unknown():
    answer = build_requester_acl_answer(
        "Puis-je consulter les enregistrements ?",
        "fr_FR",
        {"account.move": None},
    )

    assert "Je ne peux pas déterminer" in answer
