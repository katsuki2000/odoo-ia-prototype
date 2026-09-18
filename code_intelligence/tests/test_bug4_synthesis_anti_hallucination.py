"""
code_intelligence/tests/test_bug4_synthesis_anti_hallucination.py

Point 4 (todo/contexte.txt sections 809/811/812/813/814): two independent
regression tests for the two concrete failure cases confirmed by direct
execution on the Bloc N1 rejeu of 16/09/2026.

1. ACC-Q5: the synthesis LLM invented a complete, plausible `_check_name`
   Python method (no citation of its own) to fill a gap left by a real
   Semgrep extraction blind spot. dispatch_guards.verify_citations now
   flags any fenced code block containing Python syntax markers that has
   no scoped file:// citation nearby (uncited_code_blocks).

2. ACC-Q2: the synthesis LLM concluded "no restriction exists" from an
   investigation that only ever ran access/permission-layer tools, missing
   a real workflow/date-lock check none of those tools surface.
   build_synthesis_prompt now appends an explicit coverage caveat whenever
   dispatch_guards.tools_lack_deeper_coverage() is true for the tools
   actually invoked this turn.

Both tested as pure functions (no LLM/graph/tool mocking), matching this
project's convention for extracted pure helpers (see test_bug2/test_bug3).
"""

from code_intelligence.agent.dispatch_guards import (
    verify_citations,
    annotate_unverifiable_citations,
    tools_lack_deeper_coverage,
)
from code_intelligence.agent.prompts import build_synthesis_prompt


# -- 1. Uncited code block detection (ACC-Q5 pattern) --------------------

def test_uncited_python_code_block_is_flagged():
    raw = "no code in the real tool output"
    answer = (
        "Le vrai mecanisme est le suivant :\n\n"
        "```python\n"
        "@api.constrains('name')\n"
        "def _check_name(self):\n"
        "    raise ValidationError('x')\n"
        "```\n"
    )
    result = verify_citations(answer, raw)
    assert not result.is_fully_verified
    assert len(result.uncited_code_blocks) == 1

    annotated = annotate_unverifiable_citations(answer, result)
    assert " SOURCING NON VÉRIFIÉ " in annotated
    assert "possible invention" in annotated


def test_code_block_with_nearby_scoped_citation_is_not_flagged():
    raw = "voir [x.py:L10-L20](file:///a/x.py#L10-L20)"
    answer = (
        "Voici le code reel, voir [x.py:L10-L20](file:///a/x.py#L10-L20) :\n\n"
        "```python\n"
        "def _check_name(self):\n"
        "    raise ValidationError('x')\n"
        "```\n"
    )
    result = verify_citations(answer, raw)
    assert result.is_fully_verified
    assert result.uncited_code_blocks == []


def test_code_fence_without_python_markers_is_not_flagged():
    """A fenced block of plain text/SQL/whatever, with no def/@api./raise,
    is ordinary formatting -- not every fenced block is a claim about
    Python source, so this must not become a blanket "always cite fences" rule."""
    raw = "no citations anywhere"
    answer = "```\nSELECT * FROM account_move;\n```\n"
    result = verify_citations(answer, raw)
    assert result.is_fully_verified
    assert result.uncited_code_blocks == []


def test_prose_mentioning_a_method_name_without_a_fence_is_not_flagged():
    """Inline prose like 'the action_confirm method does X' is ordinary
    vocabulary, not a fabricated code block -- only fenced blocks with
    Python syntax markers are in scope for this check."""
    raw = "no citations anywhere"
    answer = "La methode action_confirm() met a jour l'etat de la commande."
    result = verify_citations(answer, raw)
    assert result.is_fully_verified
    assert result.uncited_code_blocks == []


# -- 2. Tool-coverage caveat (ACC-Q2 pattern) -----------------------------

def test_tools_lack_deeper_coverage_true_for_access_layer_only():
    assert tools_lack_deeper_coverage(
        ["who_has_access_to", "evaluate_record_rules", "analyze_security_locks", "button_execution_path"]
    ) is True


def test_tools_lack_deeper_coverage_false_when_read_source_code_present():
    assert tools_lack_deeper_coverage(
        ["who_has_access_to", "analyze_security_locks", "read_source_code"]
    ) is False


def test_tools_lack_deeper_coverage_false_when_describe_workflow_present():
    assert tools_lack_deeper_coverage(
        ["evaluate_record_rules", "describe_workflow"]
    ) is False


def test_tools_lack_deeper_coverage_false_when_no_access_layer_tool_at_all():
    """Guard only applies when access-layer tools were actually used --
    a turn that never touched ACL/security tools at all is a different
    situation (e.g. pure structural/inheritance question), not the pattern
    behind ACC-Q2."""
    assert tools_lack_deeper_coverage(["trace_full_inheritance"]) is False


def test_tools_lack_deeper_coverage_false_for_empty_or_none():
    assert tools_lack_deeper_coverage([]) is False
    assert tools_lack_deeper_coverage(None) is False


def test_synthesis_prompt_includes_coverage_caveat_on_partial_coverage():
    prompt = build_synthesis_prompt(
        "Peut-il poster une ecriture ?", ["obs"],
        ["who_has_access_to", "evaluate_record_rules", "analyze_security_locks"],
    )
    assert "COVERAGE CAVEAT" in prompt


def test_synthesis_prompt_omits_coverage_caveat_when_deeper_tool_used():
    prompt = build_synthesis_prompt(
        "Peut-il poster une ecriture ?", ["obs"],
        ["who_has_access_to", "read_source_code"],
    )
    assert "COVERAGE CAVEAT" not in prompt


def test_synthesis_prompt_omits_coverage_caveat_when_tools_arg_omitted():
    """Backward-compatible default: callers that do not pass
    tool_observation_tools (the parameter is optional) get the prompt
    exactly as before this change, no caveat injected."""
    prompt = build_synthesis_prompt("q", ["obs"])
    assert "COVERAGE CAVEAT" not in prompt


def test_synthesis_prompt_always_includes_anti_fabrication_rule():
    prompt = build_synthesis_prompt("q", ["obs"])
    assert "NEVER write out a Python code block" in prompt
