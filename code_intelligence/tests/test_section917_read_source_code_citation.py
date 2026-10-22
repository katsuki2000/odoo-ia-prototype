"""
code_intelligence/tests/test_section917_read_source_code_citation.py

read_precise_source_code exposes an opt-in scoped file citation. The
LLM-facing tool enables it so returned source is mechanically verifiable.
Final code rendering uses authorized observations, not a fresh disk read.
"""

import pytest

from code_intelligence.agent.tools.introspection import read_precise_source_code, read_source_code


from pathlib import Path
from config.settings import CORE_ADDONS_PATH

_PO_PATH = (Path(CORE_ADDONS_PATH) / "purchase" / "models" / "purchase_order.py") if CORE_ADDONS_PATH else None
PURCHASE_ORDER_FP = str(_PO_PATH.resolve()) if (_PO_PATH and _PO_PATH.exists()) else ""


@pytest.fixture(scope="module", autouse=True)
def _graph(request):
    if not PURCHASE_ORDER_FP:
        pytest.skip("CORE_ADDONS_PATH purchase_order.py non disponible -- skip propre selon regle 2")
    return request.getfixturevalue("real_graph")


class TestIncludeCitationFlag:
    def test_default_is_no_citation_unchanged(self):
        """Without the opt-in flag, the reader emits only numbered source."""
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
