import networkx as nx

from code_intelligence.rules import access_evaluator


def _summary(monkeypatch, granted_by_permission):
    graph = nx.DiGraph()
    graph.add_node("model:custom.request", node_type="Model")
    graph.add_node("group:base.group_user", node_type="Group")
    monkeypatch.setattr(access_evaluator, "_expand_implied_user_groups", lambda *_args: None)

    def fake_eval(_graph, _model, permission):
        return ({"base.group_user"} if granted_by_permission[permission] else set()), False, [], []

    monkeypatch.setattr(access_evaluator, "_eval_single_permission", fake_eval)
    return access_evaluator.requester_acl_summary(graph, "custom.request", ["base.group_user"], True)


def test_permissions_with_the_same_outcome_share_one_line(monkeypatch):
    text, _evidence, verdicts = _summary(
        monkeypatch, {"read": True, "write": True, "create": True, "unlink": False},
    )
    assert "READ, WRITE, CREATE: GRANTED (through base.group_user)." in text
    assert "DELETE: DENIED (no effective requester group has this ACL grant)." in text
    assert text.count("base.group_user") == 1
    assert verdicts == {"read": True, "write": True, "create": True, "unlink": False}


def test_distinct_outcomes_keep_separate_lines(monkeypatch):
    text, _evidence, _verdicts = _summary(
        monkeypatch, {"read": True, "write": False, "create": False, "unlink": False},
    )
    assert "READ: GRANTED (through base.group_user)." in text
    assert "WRITE, CREATE, DELETE: DENIED" in text
