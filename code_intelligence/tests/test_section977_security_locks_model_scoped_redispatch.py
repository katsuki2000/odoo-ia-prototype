"""
Section 977 (todo/contexte.txt), cause A: PUR-Q5's line-level security-lock
volet is denied outright ("Il n'existe pas de regle Python specifique
empechant la suppression d'une ligne") even though
analyze_security_locks('purchase.order.line') returns the real guard
(_unlink_except_purchase_or_done) when called directly -- root cause is not
extraction, it is that reasoning_trace.jsonl shows analyze_security_locks
was never invoked at all for purchase.order.line this turn (only for
purchase.order, then analyze_data_constraints twice). Exact same family as
974 (analyze_data_constraints): dispatch_security_locks's own instruction,
once the tool had run for the resolver's (incomplete) model list, told the
LLM unconditionally "Do not call it again" -- even for a distinct, related
model (an order's line model) the resolver never added to resolved_models.

Fix: name the already-covered model(s) explicitly (read back from
ctx.seen_calls, not ctx.concept.resolved_models -- dispatch_security_locks
only ever dispatches security_locks_targets(...)[:1], a single model, which
can differ from the full resolved_models list) and forbid repeating only
those, not the tool as a whole.
"""

from code_intelligence.agent.context import DispatchContext
from code_intelligence.agent.predispatch_access import dispatch_security_locks
from code_intelligence.agent.tools import ALL_CI_TOOLS
from code_intelligence.graph.loader import get_code_intelligence_graph


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
        # Real shape produced by _tool_call_key("analyze_security_locks",
        # {"model_name": m}) with no principal_id -- a plain 2-tuple, NOT
        # the (name, (("model_name", m),)) shape 974's test used (974 reads
        # covered models from ctx.concept.resolved_models directly and never
        # parses seen_calls, so that shape was never actually exercised;
        # 977's fix parses seen_calls tuples directly, so the key shape here
        # has to match what dispatch_security_locks will actually see).
        ctx.seen_calls.add(("analyze_security_locks", m))
    return ctx


def G():
    return get_code_intelligence_graph()


def test_instruction_names_the_covered_model_instead_of_banning_the_tool_outright():
    graph = G()
    ctx = _make_ctx(
        graph, resolved_models=["purchase.order"],
        question="Quelles regles de securite empechent de supprimer une commande "
                  "d'achat ou une de ses lignes selon leur etat ?",
        seen_call_models=["purchase.order"],
    )
    dispatch_security_locks(ctx)
    assert "purchase.order" in ctx.system_prompt_suffix
    assert "Do not call it again -- focus" not in ctx.system_prompt_suffix
    assert "do not call it again for any of them" in ctx.system_prompt_suffix
    assert "you may call analyze_security_locks once for that other model" in ctx.system_prompt_suffix


def test_instruction_lists_multiple_covered_models_sorted():
    graph = G()
    ctx = _make_ctx(
        graph, resolved_models=["purchase.order"],
        question="Quelles regles de securite empechent de supprimer une commande "
                  "d'achat ou une de ses lignes selon leur etat ?",
        seen_call_models=["sale.order", "purchase.order"],
    )
    dispatch_security_locks(ctx)
    idx_purchase = ctx.system_prompt_suffix.index("purchase.order")
    idx_sale = ctx.system_prompt_suffix.index("sale.order")
    # sorted(['sale.order', 'purchase.order']) == ['purchase.order', 'sale.order']
    # ('p' < 's') -- seen_call_models was seeded in the OPPOSITE order on
    # purpose, precisely to catch a test that would pass merely by
    # insertion order instead of actually verifying the sort.
    assert idx_purchase < idx_sale, "covered_models must be sorted, not insertion order"


def test_no_suffix_at_all_when_analyze_security_locks_was_never_actually_called():
    # dispatch_security_locks's own predicate passes (resolved concept, not
    # inheritance-related) but the model has no real security-lock source
    # files, so security_locks_targets(...) returns empty and the tool is
    # never invoked -- seen_calls stays empty (no pre-seeding here, unlike
    # the two tests above) and the suffix block must not fire on a tool
    # that was never actually run.
    graph = G()
    ctx = _make_ctx(
        graph, resolved_models=["res.currency"],
        question="Quelles regles de securite empechent de modifier un taux de change ?",
        seen_call_models=[],
    )
    dispatch_security_locks(ctx)
    assert "[DETERMINISTIC PRE-DISPATCH]" not in ctx.system_prompt_suffix
