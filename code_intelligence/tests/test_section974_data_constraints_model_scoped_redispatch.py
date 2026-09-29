"""
Section 974 (todo/contexte.txt): PUR-Q5's SQL-constraint volet stayed wrong
across two rejeu -- root cause is NOT the extraction (analyze_data_constraints
('purchase.order.line') already returns the 2 real _sql_constraints when
called directly) but the deterministic pre-dispatch instruction: once
analyze_data_constraints had run for the resolver's (incomplete) model list,
the LLM was told, unconditionally, "Do not call analyze_data_constraints
again" -- even for purchase.order.line, a distinct model the question asks
about but the resolver never added to resolved_models. The LLM itself had
already shown (via a second analyze_security_locks call, a tool with no such
blanket instruction) that it recognised the gap; this instruction alone
stopped it from doing the same for constraints.

Fix: name the already-covered model(s) explicitly and forbid repeating only
those, not the tool as a whole.
"""

from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.predispatch_actions import dispatch_analyze_data_constraints
from code_intelligence.agent.tools import ALL_CI_TOOLS
from code_intelligence.graph.loader import get_code_intelligence_graph
from code_intelligence.rules.data_constraints import DataConstraintsAnalysis


class _FakeConcept:
    def __init__(self, resolved_models):
        self.resolved_models = resolved_models
        self.resolved_modules = []
        self.is_resolved = True


class _FakeTraceLogger:
    def log_hop(self, *a, **k):
        pass


def _make_ctx(G, resolved_models, question, seen_call_models):
    ctx = DispatchContext(
        G=G, concept=_FakeConcept(resolved_models), question=question,
        tool_map={t.name: t for t in ALL_CI_TOOLS}, resolved_user_group_xmlids=[],
        trace_logger=_FakeTraceLogger(), trace_id="test", hop_cap=6,
    )
    for m in seen_call_models:
        ctx.seen_calls.add(("analyze_data_constraints", (("model_name", m),)))
    return ctx


def G():
    graph = get_code_intelligence_graph()
    return graph


def test_instruction_names_the_covered_models_instead_of_banning_the_tool_outright():
    graph = G()
    ctx = _make_ctx(
        graph, resolved_models=["purchase.order"],
        question="Quelles regles empechent de supprimer une commande d'achat ou une de "
                  "ses lignes selon leur etat, et quelle contrainte SQL distincte "
                  "s'applique sur les lignes elles-memes ?",
        seen_call_models=["purchase.order"],
    )
    dispatch_analyze_data_constraints(ctx)
    assert "purchase.order" in ctx.system_prompt_suffix
    assert "Do not call analyze_data_constraints again" not in ctx.system_prompt_suffix
    assert "do not call it again for any of them" in ctx.system_prompt_suffix
    assert "you may call analyze_data_constraints once for that other model" in ctx.system_prompt_suffix


def test_dispatcher_records_constraints_for_related_line_model(monkeypatch):
    graph = G()
    ctx = _make_ctx(
        graph,
        resolved_models=["purchase.order"],
        question=(
            "Quelles regles empechent de supprimer une commande d'achat ou une de ses "
            "lignes selon leur etat, et quelle contrainte SQL distincte s'applique "
            "sur les lignes elles-memes ?"
        ),
        seen_call_models=[],
    )

    monkeypatch.setattr(
        "code_intelligence.agent.predispatch_actions.find_model_source_filepaths",
        lambda _graph, _model: {"/tmp/model.py"},
    )
    monkeypatch.setattr(
        "code_intelligence.agent.predispatch_actions.analyze_data_constraints_from_filepaths",
        lambda model, _filepaths: DataConstraintsAnalysis(
            model_name=model,
            summary_text=f"constraints for {model}",
        ),
    )
    monkeypatch.setattr(
        "code_intelligence.agent.predispatch_actions.record_evidence",
        lambda _evidence: None,
    )
    monkeypatch.setattr(
        "code_intelligence.agent.predispatch_actions._resolve_model_param",
        lambda model: model,
    )

    dispatch_analyze_data_constraints(ctx)

    assert ctx.tool_observation_models == ["purchase.order", "purchase.order.line"]
    assert ctx.tool_observations == [
        "constraints for purchase.order",
        "constraints for purchase.order.line",
    ]


def test_no_suffix_at_all_when_the_question_is_not_constraint_related():
    # A guard-mismatch case (the dispatcher's own predicate rejects the
    # question, an early return): the tool is never invoked at all, so
    # seen_calls stays empty and the suffix block is never reached. Passing
    # seen_call_models=["purchase.order"] here proves the suffix depends on
    # the guard, not merely on seen_calls already holding an entry -- an
    # earlier version of this test instead used a constraint-related
    # question with no pre-seeded seen_calls, which is not a reachable
    # "never called" state: dispatch_analyze_data_constraints calls the real
    # tool itself on its first pass whenever the guard passes, populating
    # seen_calls before the suffix check runs a few lines later -- so that
    # assertion depended on the real tool call failing silently, which
    # happened to hold in isolation but not inside the full suite (a shared
    # graph/cache side effect across many prior tests), a flaky premise
    # rather than a real behavioural difference.
    graph = G()
    ctx = _make_ctx(
        graph, resolved_models=["purchase.order"],
        question="Qui peut voir les commandes de vente ?",
        seen_call_models=["purchase.order"],
    )
    dispatch_analyze_data_constraints(ctx)
    assert "[DETERMINISTIC PRE-DISPATCH]" not in ctx.system_prompt_suffix
