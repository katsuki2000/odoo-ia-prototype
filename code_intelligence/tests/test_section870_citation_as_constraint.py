"""
code_intelligence/tests/test_section870_citation_as_constraint.py

todo/plan_4.1_citation_as_constraint.md / todo/contexte.txt sections 870-873.

dispatch_guards.verify_citations() (section 814, see test_bug4/test_j14)
only WARNS when a fenced code block presenting real Python syntax has no
scoped file:// citation nearby -- the fabricated block itself stays
visible to the user. substitute_or_strip_code_blocks() closes that gap:
either the block is replaced by the real source lines read from disk, or
it is stripped entirely (no citation, multi-file citations, a read error,
or -- section 873 -- cited ranges that do not overlap the def/class the
block names) -- never left displayed as fabricated text, warned or not.

Uses pytest's temporary directory as an explicitly configured custom-addon
root, so the reader's production path-allowlist remains enabled in tests.
"""

from pathlib import Path

import pytest

from code_intelligence.agent.dispatch_guards import substitute_or_strip_code_blocks


_SOURCE = """\
def _helper(self):
    return 1

@api.constrains('name')
def _check_name(self):
    value = 2
    return value

def _tail(self):
    return 3
"""
# _helper: L1-L2, _check_name: L4-L7 (decorator included), _tail: L9-L10


@pytest.fixture
def numbered_file(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "CUSTOM_ADDONS_PATH", str(tmp_path))
    path = tmp_path / "numbered.py"
    path.write_text(_SOURCE, encoding="utf-8")
    return path


@pytest.fixture
def padded_file(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "CUSTOM_ADDONS_PATH", str(tmp_path))
    padding = "\n".join("# padding" for _ in range(300))
    source = f"def _helper(self):\n    return 1\n\n{padding}\n\ndef _check_name(self):\n    return 2\n"
    path = tmp_path / "padded.py"
    path.write_text(source, encoding="utf-8")
    return path


def _file_link(path: Path, start: int, end: int) -> str:
    return f"[{path.name}:L{start}-L{end}](file://{path}#L{start}-L{end})"


def _fenced_block(body: str) -> str:
    return f"```python\n{body}\n```"


_FABRICATED_BODY = (
    "@api.constrains('name')\n"
    "def _check_name(self):\n"
    "    raise ValidationError('invented, does not match the real file')"
)


def test_single_nearby_citation_substitutes_real_source(numbered_file):
    answer = (
        f"Voir {_file_link(numbered_file, 5, 6)} :\n\n"
        f"{_fenced_block(_FABRICATED_BODY)}\n"
    )
    out = substitute_or_strip_code_blocks(answer)

    assert "invented, does not match" not in out
    assert "   5 | def _check_name(self):" in out
    assert "   6 |     value = 2" in out
    assert _file_link(numbered_file, 5, 6) in out


def test_two_citations_same_file_are_unioned(numbered_file):
    """Mirrors the ACC-Q2 round-2 pattern (todo/contexte.txt section 864):
    the LLM cited two separate single-line ranges of the same file, both
    inside the definition its block names -- the union of the two cited
    ranges is what should replace the block, not either range alone."""
    answer = (
        f"Voir {_file_link(numbered_file, 5, 5)} et {_file_link(numbered_file, 7, 7)} :\n\n"
        f"{_fenced_block(_FABRICATED_BODY)}\n"
    )
    out = substitute_or_strip_code_blocks(answer)

    for line in ("def _check_name(self):", "value = 2", "return value"):
        assert line in out
    assert "_helper" not in out
    assert "_tail" not in out


def test_no_nearby_citation_strips_block():
    answer = f"Aucune citation ici.\n\n{_fenced_block(_FABRICATED_BODY)}\n"
    out = substitute_or_strip_code_blocks(answer)

    assert "invented, does not match" not in out
    assert "```" not in out
    assert "bloc de code omis" in out


def test_citations_spanning_two_different_files_strip_block(numbered_file):
    other_path = numbered_file.with_suffix(".other.py")
    answer = (
        f"Voir {_file_link(numbered_file, 1, 2)} et "
        f"{_file_link(other_path, 1, 2)} :\n\n"
        f"{_fenced_block(_FABRICATED_BODY)}\n"
    )
    out = substitute_or_strip_code_blocks(answer)

    assert "invented, does not match" not in out
    assert "```" not in out
    assert "bloc de code omis" in out


def test_citation_pointing_to_nonexistent_file_strips_block():
    fake_path = "/tmp/does-not-exist-section-870.py"
    answer = (
        f"Voir [x.py:L1-L2](file://{fake_path}#L1-L2) :\n\n"
        f"{_fenced_block(_FABRICATED_BODY)}\n"
    )
    out = substitute_or_strip_code_blocks(answer)

    assert "invented, does not match" not in out
    assert "```" not in out
    assert "bloc de code omis" in out


def test_citation_range_exceeding_max_lines_strips_block(numbered_file):
    answer = (
        f"Voir [x.py:L1-L300](file://{numbered_file}#L1-L300) :\n\n"
        f"{_fenced_block(_FABRICATED_BODY)}\n"
    )
    out = substitute_or_strip_code_blocks(answer)

    assert "invented, does not match" not in out
    assert "```" not in out
    assert "bloc de code omis" in out


def test_non_python_code_fence_is_left_untouched():
    """A fenced block with no def/@api./raise/class marker is ordinary
    formatting (SQL, plain text, etc.) -- not in scope for this guard,
    same narrow scope as verify_citations' uncited_code_blocks check."""
    answer = "```\nSELECT * FROM account_move;\n```\n"
    out = substitute_or_strip_code_blocks(answer)
    assert out == answer


def test_answer_with_no_code_fence_is_unchanged():
    answer = "Reponse en prose, sans aucun bloc de code."
    assert substitute_or_strip_code_blocks(answer) == answer


def test_substituted_block_then_passes_verify_citations(numbered_file):
    """End-to-end of the two guards in the order postprocess.py runs them:
    once substituted, the block is genuinely covered by its own nearby
    citation and verify_citations must not re-flag it."""
    from code_intelligence.agent.dispatch_guards import verify_citations

    raw_tool_output = f"voir {_file_link(numbered_file, 3, 5)}"
    answer = (
        f"Voir {_file_link(numbered_file, 3, 5)} :\n\n"
        f"{_fenced_block(_FABRICATED_BODY)}\n"
    )
    substituted = substitute_or_strip_code_blocks(answer)
    result = verify_citations(substituted, raw_tool_output)
    assert result.uncited_code_blocks == []


def test_citation_on_another_definition_strips_block_and_names_the_mismatch(numbered_file):
    """Section 872 SAL-Q5: the block describes one constraint but the
    citation the LLM attached points at its neighbour -- substituting the
    real code of the neighbour would look authoritative and be wrong."""
    answer = (
        f"Voir {_file_link(numbered_file, 1, 2)} :\n\n"
        f"{_fenced_block(_FABRICATED_BODY)}\n"
    )
    out = substitute_or_strip_code_blocks(answer)

    assert "```" not in out
    assert "_helper" not in out.replace(_file_link(numbered_file, 1, 2), "")
    assert "`_check_name`" in out
    assert "L1-L2" in out.split("bloc de code omis")[1]


def test_neighbouring_block_citation_is_not_merged_into_the_range(padded_file):
    """Section 872 2a: a citation belonging to the previous block sits in
    the same proximity window; taking min/max over all citations made a
    300+ line range that hit the read cap and stripped a correct block."""
    answer = (
        f"Avant {_file_link(padded_file, 1, 2)}\n\n"
        f"Voir {_file_link(padded_file, 305, 306)} :\n\n"
        f"{_fenced_block(_FABRICATED_BODY)}\n"
    )
    out = substitute_or_strip_code_blocks(answer)

    assert "bloc de code omis" not in out
    assert "def _check_name(self):" in out
    assert "def _helper" not in out


def test_unparseable_cited_file_strips_block(tmp_path):
    plain = tmp_path / "notes.py"
    plain.write_text("line 1\nline 2\nline 3\n")
    answer = (
        f"Voir {_file_link(plain, 1, 3)} :\n\n"
        f"{_fenced_block(_FABRICATED_BODY)}\n"
    )
    out = substitute_or_strip_code_blocks(answer)

    assert "```" not in out
    assert "bloc de code omis" in out


def test_every_named_definition_must_be_backed(numbered_file):
    body = _FABRICATED_BODY + "\n\ndef _missing(self):\n    return 0"
    answer = (
        f"Voir {_file_link(numbered_file, 5, 6)} :\n\n"
        f"{_fenced_block(body)}\n"
    )
    out = substitute_or_strip_code_blocks(answer)

    assert "```" not in out
    assert "`_check_name`, `_missing`" in out


def test_block_without_definition_keeps_range_substitution(numbered_file):
    """No def/class to anchor on: nothing to check the citation against,
    behaviour of section 871 is unchanged."""
    body = "raise ValidationError('invented')"
    answer = (
        f"Voir {_file_link(numbered_file, 5, 6)} :\n\n"
        f"{_fenced_block(body)}\n"
    )
    out = substitute_or_strip_code_blocks(answer)

    assert "invented" not in out
    assert "   6 |     value = 2" in out
