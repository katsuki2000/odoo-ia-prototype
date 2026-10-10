"""
code_intelligence/tests/test_section917_read_source_code_citation.py

todo/contexte.txt sections 915/916/917: read_precise_source_code() never
produced its own file:// citation, so verify_citations() (dispatch_guards.py)
could never confirm a citation whose SOLE source is a raw read_source_code
call -- structurally, even when perfectly exact (sections 911/914/915).

Fix: an opt-in include_citation flag. The LLM-facing read_source_code
@tool sets it True (introspection.py) so its own observation is now
self-grounding. substitute_or_strip_code_blocks (dispatch_guards.py,
sections 870/872/873) reuses the base function internally to rebuild a
fenced code block's CONTENT from a citation given elsewhere -- it must
keep the default (False), or the citation line would be injected inside
the code fence it rebuilds.
"""

import pytest

from code_intelligence.graph.loader import get_code_intelligence_graph
from code_intelligence.agent.tool_helpers import set_graph_ref
from code_intelligence.agent.tools.introspection import read_precise_source_code, read_source_code
from code_intelligence.agent.dispatch_guards import verify_citations, substitute_or_strip_code_blocks


from pathlib import Path
from config.settings import CORE_ADDONS_PATH

_PO_PATH = (Path(CORE_ADDONS_PATH) / "purchase" / "models" / "purchase_order.py") if CORE_ADDONS_PATH else None
PURCHASE_ORDER_FP = str(_PO_PATH.resolve()) if (_PO_PATH and _PO_PATH.exists()) else ""


@pytest.fixture(scope="module", autouse=True)
def _graph():
    if not PURCHASE_ORDER_FP:
        pytest.skip("CORE_ADDONS_PATH purchase_order.py non disponible -- skip propre selon regle 2")
    G = get_code_intelligence_graph()
    set_graph_ref(G)
    return G


class TestIncludeCitationFlag:
    def test_default_is_no_citation_unchanged(self):
        """The base function's default behaviour (no flag passed) must be
        byte-identical to before this section -- internal callers
        (substitute_or_strip_code_blocks) rely on this."""
        out = read_precise_source_code(PURCHASE_ORDER_FP, 960, 968)
        assert not out.startswith("Source:")
        assert out.startswith(" 960 |") or out.lstrip().startswith("960 |")

    def test_include_citation_true_prepends_source_line(self):
        out = read_precise_source_code(PURCHASE_ORDER_FP, 960, 968, include_citation=True)
        assert out.startswith("Source: [purchase_order.py:L960-L968]")
        assert f"(file://{PURCHASE_ORDER_FP}#L960-L968)" in out
        assert "960 |" in out

    def test_llm_facing_tool_sets_the_flag(self):
        out = read_source_code.invoke({"filepath": PURCHASE_ORDER_FP, "line_start": 960, "line_end": 968})
        assert out.startswith("Source: ")


class TestCitationIsMechanicallyVerifiable:
    def test_verify_citations_confirms_a_read_source_code_only_citation(self):
        """Section 915's whole point: before this fix, this exact scenario
        (citation's ONLY grounding is a raw read_source_code call) could
        never be confirmed, even when perfectly accurate."""
        raw_tool_output = read_source_code.invoke(
            {"filepath": PURCHASE_ORDER_FP, "line_start": 960, "line_end": 968}
        )
        final_answer = (
            "La méthode _approval_allowed détermine si la commande peut être "
            "approuvée ([purchase_order.py:L960-L968]"
            f"(file://{PURCHASE_ORDER_FP}#L960-L968))."
        )
        result = verify_citations(final_answer, raw_tool_output)
        assert result.is_fully_verified
        assert result.unverified_scoped_citations == []

    def test_narrower_citation_within_the_read_range_still_verified(self):
        """_scoped_covered is a subset check -- a citation narrower than
        the full read range must still verify."""
        raw_tool_output = read_source_code.invoke(
            {"filepath": PURCHASE_ORDER_FP, "line_start": 955, "line_end": 970}
        )
        final_answer = (
            f"Voir [purchase_order.py:L960-L961](file://{PURCHASE_ORDER_FP}#L960-L961)."
        )
        result = verify_citations(final_answer, raw_tool_output)
        assert result.is_fully_verified

    def test_unrelated_citation_still_flagged(self):
        """A citation pointing somewhere never actually read must still be
        rejected -- the fix must not make verification vacuously permissive."""
        raw_tool_output = read_source_code.invoke(
            {"filepath": PURCHASE_ORDER_FP, "line_start": 960, "line_end": 968}
        )
        final_answer = f"Voir [x.py:L1-L5](file:///nonexistent/path/x.py#L1-L5)."
        result = verify_citations(final_answer, raw_tool_output)
        assert not result.is_fully_verified
        assert result.unverified_scoped_citations


class TestSubstituteOrStripCodeBlocksUnaffected:
    def test_substitution_does_not_embed_a_citation_line_in_the_fence(self):
        """Regression guard: substitute_or_strip_code_blocks calls
        read_precise_source_code internally to rebuild a code fence's
        content from a citation given nearby -- that content must stay pure
        code, never gain a 'Source: ...' line at its head."""
        answer = (
            "Voici la méthode:\n"
            f"[purchase_order.py:L960-L968](file://{PURCHASE_ORDER_FP}#L960-L968)\n"
            "```python\n"
            "def _approval_allowed(self):\n"
            "    return True\n"
            "```\n"
        )
        fixed = substitute_or_strip_code_blocks(answer)
        assert "Source:" not in fixed
        assert "_approval_allowed" in fixed
