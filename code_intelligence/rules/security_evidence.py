"""
code_intelligence/semgrep_locks_evidence.py

Evidence production, text summary formatting, and site-level security constraint extraction.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import logging
import re

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence
from core.output import confidence_label
from code_intelligence.agent.context import _truncate_observation
from code_intelligence.agent.tool_helpers import get_current_question
from code_intelligence.rules.relevance_budget import (
    _rerank_by_relevance,
    _waterfill_with_protected_minimum,
)

if TYPE_CHECKING:
    from code_intelligence.rules.security import PythonSecurityLockAnalysis

logger = logging.getLogger(__name__)

# Marker that opens the verbose, low-density "exception messages" section
# inside a single file's formatted summary (see format_security_locks_summary
# below) -- everything before it (header, required_groups, static_filters)
# is the compact, high-density "essential" portion prioritized by
# assemble_security_lock_blocks.
_EXCEPTION_MESSAGES_MARKER = "  - Security lock messages"

# Section 846: intra-block relevance reranking (_rerank_by_relevance) and
# the protected-minimum water-filling primitive
# (_waterfill_with_protected_minimum) used below now live in
# relevance_budget.py (todo/contexte.txt section 950) -- generalized from
# this file to who_has_access_to/evaluate_record_rules/
# analyze_method_override_chain, which had no equivalent protection and
# fell back to plain positional head-truncation (section 948, point 1).


def build_security_lock_evidence(
    filepath: str,
    hardcoded_logins: List[str],
    exception_messages: List[str],
    exception_conditions: List[str],
    exception_guard_fields: List[str],
    exception_linenos: List[int],
    required_groups: List[str],
    required_group_methods: List[str],
    required_group_linenos: List[int],
    dynamic_dispatch_types: List[str],
    required_group_is_gating: Optional[List[bool]] = None,
    required_group_alt_conditions: Optional[List[str]] = None,
) -> List[Evidence]:
    """Produce structured Evidence objects for security locks and uncertainties."""
    evidence: List[Evidence] = []

    # 1. hardcoded_logins
    if hardcoded_logins:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"File '{filepath}' contains hardcoded privileged login(s)/"
                f"email(s): {hardcoded_logins}"
            ),
            source=f"security_lock:{filepath}:hardcoded_logins",
            value=hardcoded_logins,
            confidence="HIGH",
            scope={},
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"File '{filepath}' contains no hardcoded login/email",
            source=f"security_lock:{filepath}:hardcoded_logins",
            value=None,
            confidence="HIGH",
            scope={},
        ))

    # 2. exception_messages
    if exception_messages:
        conditions = exception_conditions or [""] * len(exception_messages)
        guard_fields = exception_guard_fields or [""] * len(exception_messages)
        linenos = exception_linenos or [0] * len(exception_messages)
        for i, (message, condition, guard_field, lineno) in enumerate(
            zip(exception_messages, conditions, guard_fields, linenos)
        ):
            claim = f"File '{filepath}' raises UserError/ValidationError \"{message}\""
            if condition:
                claim += f" (condition: {condition})"
            if guard_field:
                claim += f" (link-guarded on '{guard_field}')"
            scope: Dict[str, Any] = {}
            if lineno:
                scope["lineno"] = lineno
            disambiguator = lineno if lineno else i
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=claim,
                source=f"security_lock:{filepath}:exception:{disambiguator}",
                value=message,
                confidence="HIGH",
                scope=scope,
            ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"File '{filepath}' raises no UserError/ValidationError with "
                f"an extractable message"
            ),
            source=f"security_lock:{filepath}:exception",
            value=None,
            confidence="HIGH",
            scope={},
        ))

    # 3. required_groups
    if required_groups:
        methods = required_group_methods or [""] * len(required_groups)
        linenos = required_group_linenos or [0] * len(required_groups)
        is_gating = required_group_is_gating or [True] * len(required_groups)
        alt_conditions = required_group_alt_conditions or [""] * len(required_groups)
        for group_xmlid, method_name, lineno, gating, alt in zip(
            required_groups, methods, linenos, is_gating, alt_conditions
        ):
            if gating and alt:
                claim = (
                    f"File '{filepath}' checks group '{group_xmlid}' via has_group()/user_has_groups(), "
                    f"but this check is NOT the only sufficient path -- the enclosing 'or' expression is "
                    f"also satisfied by: {alt}. Do not present this group as unconditionally required."
                )
            elif gating:
                claim = f"File '{filepath}' requires group '{group_xmlid}' via has_group()"
            else:
                claim = (
                    f"File '{filepath}' checks group '{group_xmlid}' via has_group()/user_has_groups() "
                    f"but ONLY to select which error message text to use -- this check does not gate "
                    f"whether the action is blocked"
                )
            if method_name:
                claim += f" in method '{method_name}()'"
            scope: Dict[str, Any] = {}
            if method_name:
                scope["method"] = method_name
            if lineno:
                scope["lineno"] = lineno
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=claim,
                source=f"security_lock:{filepath}:group:{group_xmlid}",
                value=group_xmlid,
                confidence="HIGH",
                scope=scope,
            ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"File '{filepath}' contains no has_group() requirement",
            source=f"security_lock:{filepath}:group",
            value=None,
            confidence="HIGH",
            scope={},
        ))

    # 4. dynamic_dispatch
    if dynamic_dispatch_types:
        for pattern_name in dynamic_dispatch_types:
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=(
                    f"File '{filepath}' uses dynamic dispatch via {pattern_name}(), "
                    f"not statically classifiable"
                ),
                source=f"security_lock:{filepath}:dynamic_dispatch:{pattern_name}",
                value=pattern_name,
                confidence="LOW",
                scope={},
            ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"File '{filepath}' uses no dynamic dispatch (getattr/eval/exec)",
            source=f"security_lock:{filepath}:dynamic_dispatch",
            value=None,
            confidence="HIGH",
            scope={},
        ))

    return evidence


def format_security_locks_summary(
    analysis: Any,
    code: str,
    filepath: str,
) -> str:
    """Format human-readable summary text for PythonSecurityLockAnalysis."""
    from code_intelligence.utils import (
        SENSITIVE_BYPASS_MARKER,
        format_file_link,
        format_xml_id_citation,
    )

    line_count = max(1, len(code.splitlines()))
    file_link = format_file_link(filepath, 1, line_count)

    lines = [f"Analyse des verrous Python ({file_link}) [Confiance: {confidence_label(analysis.confidence)}]:"]

    if analysis.has_hardcoded_logins:
        lines.append(f"  - {SENSITIVE_BYPASS_MARKER} Logins/Emails privilégies en dur: {analysis.hardcoded_logins}")

    if analysis.required_groups:
        methods = analysis.required_group_methods or [""] * len(analysis.required_groups)
        group_linenos = analysis.required_group_linenos or [0] * len(analysis.required_groups)
        is_gating_list = getattr(analysis, "required_group_is_gating", None) or [True] * len(analysis.required_groups)
        action_groups = [g for g, m in zip(analysis.required_groups, methods) if m]
        if action_groups:
            groups_joined = ', '.join(action_groups)
            lines.append(f"  - Groupe(s) technique(s) requis detecte(s) (has_group): {groups_joined}")
            # Section 846: rerank so the finding actually relevant to the
            # current question -- not just whichever comes first in source
            # order -- is the one that survives if a downstream budget cut
            # (837's _protected_prefix_end) can only keep the first line.
            alt_conditions_list = (
                getattr(analysis, "required_group_alt_conditions", None) or [""] * len(analysis.required_groups)
            )
            action_rows = _rerank_by_relevance(
                list(zip(analysis.required_groups, methods, group_linenos, is_gating_list, alt_conditions_list)),
                text_fn=lambda row: f"{row[0]} {row[1]}",
                question=get_current_question(),
            )
            for group_xmlid, method_name, glineno, gating, alt in action_rows:
                if method_name:
                    citation = format_xml_id_citation(group_xmlid)
                    # Section 835 (option A) -- attach this finding's OWN file link
                    # (not just the block-level header link) so that when several
                    # blocks/files get concatenated (824's multi-block assembly),
                    # the correct source stays adjacent to the fact it describes
                    # wherever it lands in the concatenated text, instead of relying
                    # on the LLM to still have the header link in view.
                    site_link = format_file_link(filepath, glineno, glineno) if glineno else file_link
                    if gating and alt:
                        # todo/contexte.txt, session "SecurityLockASTVisitor
                        # BoolOp/Or gap" (PUR-Q1 rejeu): this has_group()/
                        # user_has_groups() call is one disjunct of an `or`
                        # whose other disjuncts are unrelated to any group
                        # and independently sufficient -- the group is NOT a
                        # hard requirement, just one of several paths.
                        lines.append(
                            f"    * has_group('{group_xmlid}') se trouve dans la methode '{method_name}()', mais "
                            f"N'EST PAS le seul chemin : cette verification fait partie d'un 'or' dont les autres "
                            f"conditions sont independantes de tout groupe ({alt}) -- si l'une d'elles est vraie, "
                            f"l'action est autorisee MEME SANS ce groupe. NE PAS presenter ce groupe comme requis "
                            f"dans tous les cas sans verifier ces conditions alternatives. "
                            f"({citation}) ({site_link})"
                        )
                    elif gating:
                        lines.append(
                            f"    * has_group('{group_xmlid}') se trouve dans la methode '{method_name}()' -- "
                            f"ne pas l'attribuer a une autre methode sans le verifier explicitement dans le code source. "
                            f"({citation}) ({site_link})"
                        )
                    else:
                        lines.append(
                            f"    * has_group('{group_xmlid}') se trouve dans la methode '{method_name}()' MAIS NE FAIT QUE "
                            f"SELECTIONNER LE TEXTE DU MESSAGE D ERREUR -- l instruction raise qui suit ne depend PAS de ce "
                            f"groupe et s execute de toute facon ; NE PAS presenter ce groupe comme requis pour agir, "
                            f"autorise a contourner ou exempte de la regle sur la seule base de cette ligne. "
                            f"({citation}) ({site_link})"
                        )
        for group_xmlid, method_name, glineno in zip(analysis.required_groups, methods, group_linenos):
            if not method_name:
                citation = format_xml_id_citation(group_xmlid)
                site_link = format_file_link(filepath, glineno, glineno) if glineno else file_link
                lines.append(
                    f"  - has_group('{group_xmlid}') se trouve hors de toute methode (niveau module, "
                    f"ex: valeur par defaut d'un champ UI) -- NE PAS interpreter comme un verrou d'acces ou de modification du modele. "
                    f"({citation}) ({site_link})"
                )

    if analysis.static_filters:
        for f_name, f_val, s_line, e_line in analysis.static_filters:
            link = format_file_link(filepath, s_line, e_line)
            lines.append(f"  - Filtre d'exclusion statique '{f_name}' ({link}): {f_val}")

    if analysis.exception_messages:
        lines.append(f"  - Security lock messages (UserError/ValidationError):")
        conditions = analysis.exception_conditions or [""] * len(analysis.exception_messages)
        guard_fields = analysis.exception_guard_fields or [""] * len(analysis.exception_messages)
        exc_linenos = analysis.exception_linenos or [0] * len(analysis.exception_messages)
        # Section 846: same reranking as the has_group findings above --
        # this is precisely the gap 836/837 left open (account.move,
        # ACC-Q2: source order put an unrelated "journal not found" message
        # first, so IT is what 837's protected-minimum kept every rerun,
        # never the actually-relevant lock-date message further down).
        exc_rows = _rerank_by_relevance(
            list(zip(analysis.exception_messages, conditions, guard_fields, exc_linenos)),
            text_fn=lambda row: f"{row[0]} {row[1]}",
            question=get_current_question(),
        )
        for msg, condition, guard_field, exc_lineno in exc_rows:
            # Section 835 (option A) -- same per-finding file link as required_groups
            # above: the block header link alone is not enough once several files'
            # blocks are concatenated (824) -- attach it to this exact finding line.
            site_link = format_file_link(filepath, exc_lineno, exc_lineno) if exc_lineno else file_link
            if condition:
                lines.append(f"    * \"{msg}\" (condition : {condition}) ({site_link})")
            else:
                lines.append(f"    * \"{msg}\" ({site_link})")
            if guard_field:
                lines.append(
                    f"      [GARDE DE LIEN: si '{guard_field}' est vide/absent (aucun "
                    f"enregistrement lie), cette condition est FAUSSE par court-circuit "
                    f"Python (evaluation de gauche a droite d'un 'and') -- la regle ci-dessus "
                    f"NE S'APPLIQUE PAS dans ce cas, quel que soit le reste de la condition.]"
                )

    if analysis.has_dynamic_dispatch:
        lines.append(f"  - Incertitude dynamique ({', '.join(analysis.dynamic_dispatch_types)}): revue manuelle recommandée")

    if not analysis.security_warnings and not analysis.exception_messages and not analysis.static_filters:
        lines.append("  - Aucun verrou spécifique ni incertitude dynamique détecté.")

    return "\n".join(lines)


_EMPTY_BLOCK_LINE = "Aucun verrou sp\u00e9cifique ni incertitude dynamique d\u00e9tect\u00e9."


def _compact_empty_block(text: str) -> str:
    """Section 837 (option 1, mandat 836): a block with zero findings still
    pays for a full header (file link + confidence label) plus one filler
    sentence -- pure water-filling budget waste when several such blocks
    compete against a large, information-dense block (section 836:
    account.move has 4/11 strictly-empty blocks eating ~850 chars for zero
    signal). Collapse to a single short line, keeping only the file link
    for traceability.
    """
    lines = text.split("\n")
    if len(lines) == 2 and lines[1].strip().lstrip("-").strip() == _EMPTY_BLOCK_LINE:
        m = re.search(r"(\[[^\]]+\]\([^)]+\))", lines[0])
        link = m.group(1) if m else lines[0]
        return f"{link}: aucun verrou."
    return text


def assemble_security_lock_blocks(blocks: List[str], budget: int) -> str:
    """Join per-file `format_security_locks_summary` blocks under a fixed
    total character budget, WITHOUT letting a naive head-truncation starve
    whichever block happens to be assembled last (section 820: for
    `account.move`, the native Odoo file -- by far the largest and most
    relevant block -- is sorted after 3 custom-module blocks by
    `_sort_filepaths_custom_first`, so a flat "\n\n".join(...) + head-cut
    silently drops it entirely once the custom blocks alone exceed the cap).

    Two-tier water-filling (section 824), with two refinements (section 837,
    mandat 836 -- options 1+3, see that section for the account.move repro
    where the tier-1 budget was exhausted before ever reaching tier 2 and
    the tier-1 allocation itself landed mid-line on the block that mattered
    most):
      1. Each block is split at `_EXCEPTION_MESSAGES_MARKER` into an
         "essential" portion (header, required_groups, static_filters --
         compact, high information density, already prioritized within a
         single block by the 819 reordering) and an "exception_messages"
         portion (verbose UserError/ValidationError text dump, low density).
      2. Strictly-empty blocks (no findings at all) are compacted to a
         single short line before entering the water-filling competition
         at all (`_compact_empty_block`), so they no longer pay full header
         price for zero signal.
      3. Within each tier, every non-empty block is first guaranteed a
         protected minimum covering its header plus first finding line
         (`_waterfill_with_protected_minimum`) before the remaining budget
         is water-filled proportionally across the rest -- so a block that
         gets a small share still keeps one complete, highest-priority
         line rather than losing it whole to a mid-line cut.
      4. Whatever essential-tier budget remains goes to the
         exception-message portions, same protected-minimum + water-fill
         treatment, so no single block's verbose dump can crowd out
         another block's exception message, and each non-empty exception
         portion keeps at least its first message line if any budget
         reaches tier 2 at all.
    Blocks are reassembled in their original (input) order -- this function
    does not re-sort; ordering (e.g. custom-first) is the caller's decision.
    """
    if not blocks:
        return ""
    if budget <= 0:
        return _truncate_observation("", 0)

    blocks = [_compact_empty_block(b) for b in blocks]

    essentials: List[str] = []
    exceptions: List[str] = []
    for block in blocks:
        idx = block.find(_EXCEPTION_MESSAGES_MARKER)
        if idx == -1:
            essentials.append(block)
            exceptions.append("")
        else:
            essentials.append(block[:idx].rstrip("\n"))
            exceptions.append(block[idx:])

    essential_sizes = [len(e) for e in essentials]
    essential_budget = min(budget, sum(essential_sizes))
    essential_alloc = _waterfill_with_protected_minimum(essential_sizes, essentials, essential_budget)

    used = sum(essential_alloc)
    remaining_budget = max(0, budget - used)
    exception_sizes = [len(e) for e in exceptions]
    # Section 837: prioritize the exception tier by how much essential-tier
    # budget each block actually earned -- a proxy for how substantive/
    # important that block's analysis turned out to be, so the same block
    # that won the essential tier's fight for its finding line also gets
    # first claim on tier-2 budget for its associated exception message.
    exception_alloc = _waterfill_with_protected_minimum(
        exception_sizes, exceptions, remaining_budget, priority=essential_alloc
    )

    parts: List[str] = []
    for essential, ess_cap, exc_text, exc_cap in zip(
        essentials, essential_alloc, exceptions, exception_alloc
    ):
        # Section 837:  always appends its
        # "[... Content truncated ...]" marker, even at a 0 budget -- so a
        # dropped block (all-or-nothing allocation, see
        # ) must be skipped outright
        # rather than routed through it, or it silently reappears as pure
        # marker noise with zero actual content.
        if ess_cap <= 0:
            continue
        block_text = _truncate_observation(essential, ess_cap) if ess_cap < len(essential) else essential
        if exc_cap > 0:
            exc_piece = exc_text if exc_cap >= len(exc_text) else _truncate_observation(exc_text, exc_cap)
            block_text = block_text + "\n" + exc_piece
        parts.append(block_text)

    return "\n\n".join(parts)


def extract_method_security_constraints(
    analysis: Any, lineno: int, end_lineno: int
) -> List[str]:
    """Filter file-level security findings down to [lineno, end_lineno] range."""
    constraints: List[str] = []

    alt_conditions = (
        getattr(analysis, "required_group_alt_conditions", None) or [""] * len(analysis.required_groups)
    )
    for group_xmlid, method_name, group_lineno, alt in zip(
        analysis.required_groups,
        analysis.required_group_methods,
        analysis.required_group_linenos,
        alt_conditions,
    ):
        if group_lineno and lineno <= group_lineno <= end_lineno:
            location = f"dans '{method_name}()'" if method_name else "a cette ligne"
            if alt:
                constraints.append(
                    f"VERROU RATTACHE AU SITE: has_group('{group_xmlid}') verifie {location}, mais N'EST PAS le "
                    f"seul chemin -- egalement satisfait sans ce groupe si : {alt}."
                )
            else:
                constraints.append(
                    f"VERROU RATTACHE AU SITE: has_group('{group_xmlid}') requis {location}."
                )

    exception_conditions = analysis.exception_conditions or [""] * len(analysis.exception_messages)
    exception_guard_fields = analysis.exception_guard_fields or [""] * len(analysis.exception_messages)
    for message, condition, guard_field, exc_lineno in zip(
        analysis.exception_messages,
        exception_conditions,
        exception_guard_fields,
        analysis.exception_linenos,
    ):
        if exc_lineno and lineno <= exc_lineno <= end_lineno:
            text = f'VERROU RATTACHE AU SITE: "{message}"'
            if condition:
                text += f" (condition : {condition})"
            if guard_field:
                text += (
                    f" [GARDE DE LIEN: si '{guard_field}' est vide/absent, cette "
                    f"condition est FAUSSE par court-circuit Python -- la regle NE "
                    f"S'APPLIQUE PAS dans ce cas.]"
                )
            constraints.append(text)

    return constraints
