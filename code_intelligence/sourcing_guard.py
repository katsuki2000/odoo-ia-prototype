"""
code_intelligence/sourcing_guard.py

Mechanical verification that every citation in the agent's final answer corresponds
to citations produced in the raw tool output for the question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set, Tuple

# Scoped file citation: explicit line range, per CI_SYSTEM_PROMPT's own
# instruction ("[file.py:L12-L25](file:///path#L12-L25)").
_SCOPED_FILE_LINK_PATTERN = re.compile(
    r"\(file:///(?P<path>[^\#\)]+)#L(?P<start>\d+)-L(?P<end>\d+)\)"
)
# Any file:// link at all, scoped or not -- used to find bare links that
# skipped the line-range requirement entirely.
_ANY_FILE_LINK_PATTERN = re.compile(r"\(file:///(?P<path>[^\#\)]+?)(?:#L\d+-L\d+)?\)")

# Explicit xml_id: prefix, per the format this patch adds to the prompts.
# A bare identifier like "account.group_account_manager" with no prefix is
# NOT treated as a citation -- it's ordinary technical vocabulary the LLM
# is expected to use throughout the answer, not a sourcing claim.
_XML_ID_PATTERN = re.compile(r"xml_id:\s*([a-zA-Z_]\w*\.[a-zA-Z_][\w.]*)")


@dataclass
class SourcingVerificationResult:
    unverified_scoped_citations: List[Tuple[str, int, int]] = field(default_factory=list)
    bare_file_links: List[str] = field(default_factory=list)  # no line range at all
    unverified_xml_ids: List[str] = field(default_factory=list)

    @property
    def is_fully_verified(self) -> bool:
        return not (self.unverified_scoped_citations or self.bare_file_links or self.unverified_xml_ids)


def _scoped_covered(citation: Tuple[str, int, int], ground_truth: Set[Tuple[str, int, int]]) -> bool:
    """Covered if the cited range falls within a ground-truth range for the
    same file -- subset, not exact equality, since the LLM may legitimately
    narrow a citation when quoting part of a larger source snippet."""
    path, start, end = citation
    return any(
        gt_path == path and gt_start <= start and end <= gt_end
        for gt_path, gt_start, gt_end in ground_truth
    )


def verify_citations(final_answer: str, raw_tool_output: str) -> SourcingVerificationResult:
    ground_truth_scoped = {
        (m.group("path"), int(m.group("start")), int(m.group("end")))
        for m in _SCOPED_FILE_LINK_PATTERN.finditer(raw_tool_output)
    }
    ground_truth_xml_ids = set(_XML_ID_PATTERN.findall(raw_tool_output))

    result = SourcingVerificationResult()

    for citation in {
        (m.group("path"), int(m.group("start")), int(m.group("end")))
        for m in _SCOPED_FILE_LINK_PATTERN.finditer(final_answer)
    }:
        if not _scoped_covered(citation, ground_truth_scoped):
            result.unverified_scoped_citations.append(citation)

    for m in _ANY_FILE_LINK_PATTERN.finditer(final_answer):
        if "#L" not in m.group(0):
            result.bare_file_links.append(m.group("path"))

    for xml_id in set(_XML_ID_PATTERN.findall(final_answer)):
        if xml_id not in ground_truth_xml_ids:
            result.unverified_xml_ids.append(xml_id)

    return result


def annotate_unverifiable_citations(final_answer: str, result: SourcingVerificationResult) -> str:
    """Never silently strip or rewrite around an unverified citation --
    that risks introducing new unverified content. Append a visible,
    explicit warning instead."""
    if result.is_fully_verified:
        return final_answer

    warnings = []
    if result.unverified_scoped_citations:
        cites = ", ".join(f"{p}#L{s}-L{e}" for p, s, e in result.unverified_scoped_citations)
        warnings.append(f"citation(s) fichier non retrouvée(s) dans les données produites: {cites}")
    if result.bare_file_links:
        warnings.append(
            "lien(s) fichier sans plage de lignes (non vérifiable mécaniquement): "
            + ", ".join(result.bare_file_links)
        )
    if result.unverified_xml_ids:
        warnings.append(
            "xml_id(s) non retrouvé(s) dans les données produites: " + ", ".join(result.unverified_xml_ids)
        )

    return (
        final_answer
        + "\n\n SOURCING NON VÉRIFIÉ (J14): " + " ; ".join(warnings)
        + ". Ne pas considérer ces éléments comme confirmés pour cette question."
    )