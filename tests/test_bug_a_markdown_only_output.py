# -*- coding: utf-8 -*-
"""
Tests for the Markdown-only output contract imposed on the LLM to prevent
Bug A (raw HTML tags displayed literally in the widget, see
todo/contexte.txt sections 375-378, root-caused in section 382).

The frontend's formatMarkdown() (odoo_addons/miro_ai/static/src/js/miro_ai.js)
expects Markdown, not HTML, and escapes anything it doesn't recognize as
one of a small explicit whitelist of tags. The primary fix (section 382,
option (a)) is imposing this contract explicitly on every system prompt
that produces user-facing "answer" text, across all 4 routing branches.

These tests are deterministic and offline: they assert the instruction is
actually present in the prompt text sent to the LLM, on every branch. They
do NOT call a real LLM (no network/API access from this test), so they
cannot verify actual model compliance -- only that the contract is stated.
"""
import re

from core.prompts import SYSTEM_PROMPT
from core.routing import OUT_OF_SCOPE_ANSWER
from code_intelligence.ci_helpers import CI_SYSTEM_PROMPT


# A prompt instruction telling the LLM not to use HTML tags, and to use
# Markdown, must be present -- phrased in French for the documentaire
# system prompt, English for the Code Intelligence one (matches its own
# existing language, see CI_SYSTEM_PROMPT rules 1-6).
_FRENCH_NO_HTML_MARKER_RE = re.compile(r"\bJAMAIS\b.*\bHTML\b", re.IGNORECASE | re.DOTALL)
_FRENCH_MARKDOWN_MARKER_RE = re.compile(r"\bMarkdown\b", re.IGNORECASE)
_ENGLISH_NO_HTML_MARKER_RE = re.compile(r"\bNEVER\b.*\bHTML\b", re.IGNORECASE)
_ENGLISH_MARKDOWN_MARKER_RE = re.compile(r"\bMarkdown\b", re.IGNORECASE)


def test_documentaire_system_prompt_forbids_raw_html():
    """core/prompts.py::SYSTEM_PROMPT (documentaire branch, document_rag/generate_node.py)
    must explicitly instruct the LLM to answer in Markdown only, never raw HTML."""
    rendered = SYSTEM_PROMPT.format(context="CTX", out_of_scope_answer=OUT_OF_SCOPE_ANSWER)
    assert _FRENCH_MARKDOWN_MARKER_RE.search(rendered), (
        "SYSTEM_PROMPT must instruct the LLM to use Markdown formatting"
    )
    assert _FRENCH_NO_HTML_MARKER_RE.search(rendered), (
        "SYSTEM_PROMPT must explicitly forbid raw HTML tags in the answer"
    )
    # Sanity: the instructional text itself illustrates forbidden tags
    # (e.g. "<strong>") as prose examples -- that's expected and fine, this
    # only guards against the instruction disappearing entirely.


def test_code_intelligence_system_prompt_forbids_raw_html():
    """code_intelligence/ci_helpers.py::CI_SYSTEM_PROMPT (code_intelligence branch)
    must carry the same Markdown-only contract -- Bug A was reproduced on
    this branch too (todo/contexte.txt section 378)."""
    assert _ENGLISH_MARKDOWN_MARKER_RE.search(CI_SYSTEM_PROMPT)
    assert _ENGLISH_NO_HTML_MARKER_RE.search(CI_SYSTEM_PROMPT)


def test_donnees_erp_and_hybride_prompts_forbid_raw_html():
    """erp_data/orm_agent_node.py's local system_prompt (donnees_erp branch)
    and combine_prompt (hybride branch) are built inline inside their
    respective functions rather than as importable module-level constants
    -- read the source directly and assert the instruction text is present,
    rather than re-deriving the prompts by re-implementing the function
    bodies (which would just duplicate the source instead of testing it)."""
    import inspect
    from erp_data import orm_agent_node

    source = inspect.getsource(orm_agent_node)

    # Both inline prompts (orm_agent_loop's system_prompt, hybrid_node's
    # combine_prompt) were extended with the same Markdown-only / no-HTML
    # instruction text (section 382) -- assert it appears at least twice
    # (once per prompt) rather than pinning down the exact prompt boundary.
    occurrences = source.count("balise HTML brute")
    assert occurrences >= 2, (
        "Expected the Markdown-only / no-raw-HTML instruction in both "
        "orm_agent_loop's system_prompt and hybrid_node's combine_prompt "
        f"(erp_data/orm_agent_node.py) -- found {occurrences} occurrence(s)."
    )
