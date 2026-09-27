from __future__ import annotations
"""
code_intelligence/ci_security_locks.py

Extraction and contradiction correction for security lock condition amounts
and threshold comparisons in Python methods and exception strings.
"""

import logging
import re
from typing import List, Optional, Tuple

from code_intelligence.utils import (
    _match_near_truncation,
    _extract_amount,
    _question_is_approval_related,
    _has_can_view_amount_fact,
    _split_before_first_fact_marker,
    _LOCK_CONDITION_LINE_RE,
    _AMOUNT_CMP_RE,
)
from code_intelligence.rules.group_resolver import _fold_accents

logger = logging.getLogger(__name__)

_OVERRIDE_CHAIN_AMOUNT_RE = re.compile(r"rec\.\w+\s*>\s*(\d[\d\s]*\d)")


def _amount_present_in_text(amount: str, text: str) -> bool:
    """True if amount appears in text as a standalone number."""
    spaced = f"{amount[:-3]} {amount[-3:]}" if len(amount) > 3 else amount
    for candidate in {amount, spaced}:
        pattern = r"(?<!\d)" + re.escape(candidate) + r"(?!\d)"
        if re.search(pattern, text):
            return True
    return False


_SECURITY_LOCK_MESSAGES_MARKER = "Security lock messages (UserError/ValidationError)"


def _extract_security_lock_condition_amounts(raw_tool_output: str) -> List[str]:
    """Pull monetary thresholds in security lock exception conditions."""
    amounts: List[str] = []
    for block in raw_tool_output.split("\n\n"):
        if _SECURITY_LOCK_MESSAGES_MARKER not in block:
            continue
        for match in _OVERRIDE_CHAIN_AMOUNT_RE.finditer(block):
            if _match_near_truncation(block, match.start(), match.end()):
                continue
            amount = match.group(1).replace(" ", "").strip()
            if amount and amount not in amounts:
                amounts.append(amount)
    return amounts


def _backfill_missing_security_lock_amount(
    final_answer: str, raw_tool_output: str, question: Optional[str] = None
) -> str:
    """Append security lock numeric threshold as a deterministic fact if missing."""
    if question is not None:
        if _has_can_view_amount_fact(final_answer):
            return final_answer
        if not (_question_is_approval_related(question) or _extract_amount(question) is not None):
            return final_answer
        amount = _extract_amount(question)
    else:
        amount = None

    amounts = _extract_security_lock_condition_amounts(raw_tool_output)
    if not amounts:
        return final_answer

    if amount is not None:
        amounts = [a for a in amounts if float(a) <= amount]
        if not amounts:
            return final_answer

    amount_list = ", ".join(f"{a}€" for a in amounts)
    logger.info(
        "Node [code_intelligence_agent]: backfilling security-lock condition amount "
        "threshold(s) missing from synthesized answer: %s",
        amount_list,
    )
    return (
        final_answer
        + f"\n\n[FAIT DÉTERMINISTIQUE] Le verrou de sécurité contient une condition "
        f"supplémentaire déclenchée au-delà de {amount_list}, distincte du groupe "
        f"requis ci-dessus. Fait extrait directement de l'analyse statique du code."
    )


def _correct_security_lock_threshold_contradictions(
    final_answer: str, scoped_tool_output: str, question: str
) -> str:
    """Detect and correct inversions of Python security lock threshold logic."""
    amount = _extract_amount(question)
    if amount is None:
        return final_answer

    rules: List[Tuple[str, str, float, str]] = []
    for match in _LOCK_CONDITION_LINE_RE.finditer(scoped_tool_output):
        if _match_near_truncation(scoped_tool_output, match.start(), match.end()):
            continue
        cond_text = match.group(1)
        group_name = match.group(2).strip()
        cmp_match = _AMOUNT_CMP_RE.search(cond_text)
        if cmp_match:
            op = cmp_match.group(1)
            thresh = float(cmp_match.group(2))
            rules.append((group_name, op, thresh, cond_text))

    if not rules:
        return final_answer

    triggered = [
        (g, op, thresh, cond)
        for g, op, thresh, cond in rules
        if (op == ">" and amount > thresh) or (op == ">=" and amount >= thresh)
    ]
    higher_untriggered = [
        (g, op, thresh, cond)
        for g, op, thresh, cond in rules
        if op in (">", ">=") and thresh > amount
    ]

    if not triggered and not higher_untriggered:
        return final_answer

    prose = _split_before_first_fact_marker(final_answer)
    suffix = final_answer[len(prose):]

    if "\n\n" in prose:
        delimiter = "\n\n"
        chunks = prose.split("\n\n")
    elif "\n-" in prose or "\n*" in prose:
        delimiter = "\n"
        chunks = prose.split("\n")
    else:
        delimiter = "\n\n"
        chunks = [prose]

    amt_s = str(int(amount))
    amt_sp = f"{int(amount):,}".replace(",", " ")
    new_chunks = []
    contradiction_found = False

    for chunk in chunks:
        c_folded = _fold_accents(chunk.lower())
        prefix = "- " if chunk.strip().startswith("- ") else ("* " if chunk.strip().startswith("* ") else "")
        replaced = False

        for g, op, thresh, cond in triggered:
            t_s = str(int(thresh))
            t_sp = f"{int(thresh):,}".replace(",", " ")
            g_short = g.split(".")[-1].replace("group_", "")

            group_keywords = [g.lower(), g_short.lower()]
            if "account" in g.lower() or "comptab" in cond.lower():
                group_keywords.extend(["comptabilit", "responsable"])
            if "manager" in g.lower():
                group_keywords.extend(["manager", "responsable", "gestionnaire"])

            has_group_ref = any(k in c_folded for k in group_keywords)
            if has_group_ref:
                is_inv = False
                if any(w in c_folded for w in ["jusqu", "plafond", "limite"]) and (t_s in c_folded or t_sp in c_folded):
                    if any(w in c_folded for w in ["n'a pas le permission", "ne peut pas", "ne peut donc pas", "n'est pas autoris", "pas autoris"]):
                        is_inv = True
                elif any(w in c_folded for w in ["n'a pas le permission de valider", "ne peut pas valider", "ne peut donc pas valider", "n'est pas autoris"]):
                    if amt_s in c_folded or amt_sp in c_folded or "ce document" in c_folded or "ce montant" in c_folded:
                        is_inv = True

                if is_inv:
                    new_chunks.append(
                        f"{prefix}Pour un document de {amt_sp}€ (dépassant le seuil de {t_sp}€), "
                        f"la validation exige d'être membre du groupe `{g}`. "
                        f"Un membre de ce groupe a donc le permission de valider ce document."
                    )
                    replaced = True
                    contradiction_found = True
                    break

        if replaced:
            continue

        for hg, hop, hthresh, hcond in higher_untriggered:
            ht_s = str(int(hthresh))
            ht_sp = f"{int(hthresh):,}".replace(",", " ")
            hg_short = hg.split(".")[-1].replace("group_", "")

            hg_keywords = [hg.lower(), hg_short.lower()]
            if "system" in hg.lower() or "admin" in hg.lower():
                hg_keywords.extend(["administrateur", "system"])

            has_hg_ref = any(k in c_folded for k in hg_keywords)
            if has_hg_ref:
                is_wrong = False
                if ht_s in c_folded or ht_sp in c_folded or "100k" in c_folded or "100 k" in c_folded:
                    if any(w in c_folded for w in ["a le permission de valider", "peut valider", "est autoris"]):
                        if amt_s in c_folded or amt_sp in c_folded or "ce document" in c_folded or "ce montant" in c_folded:
                            is_wrong = True

                if is_wrong:
                    new_chunks.append(
                        f"{prefix}Le verrou supérieur (> {ht_sp}€, réservé à `{hg}`) ne s'applique pas "
                        f"à {amt_sp}€ car le montant est inférieur à {ht_sp}€."
                    )
                    replaced = True
                    contradiction_found = True
                    break

        if not replaced:
            new_chunks.append(chunk)

    if not contradiction_found:
        return final_answer

    logger.warning(
        "Node [code_intelligence_agent]: synthesis asserted an inverted/contradictory "
        "security lock threshold verdict for amount %s -- replacing contradictory sentences.",
        amount,
    )
    return delimiter.join(new_chunks) + suffix

# ── Security Gate ────────────────────────────────────────────────────────


import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set, Tuple

import networkx as nx

_OMITTED_MARKER = "ELEMENT OMITTED FOR AUTHORIZATION REASON"
_HAS_GROUP_SOURCE_PATTERN = re.compile(r"\.has_group\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")



@dataclass
class OmittedItem:
    """
    A single element withheld from the demandeur for authorization reasons.
    `reason` is always explicit and human-readable -- never a bare status
    code -- so it can be surfaced to the user as-is, distinct from a
    confidence/coverage score.
    """
    label: str
    reason: str


def _extract_has_group_xmlids_from_source(G: nx.DiGraph, model_name: str) -> Set[str]:
    from code_intelligence.agent.tool_helpers import find_model_source_filepaths

    filepaths = find_model_source_filepaths(G, model_name)
    found: Set[str] = set()
    for fp in filepaths:
        p = Path(fp)
        if not p.exists():
            continue
        try:
            code = p.read_text(encoding="utf-8")
        except Exception:
            continue
        found.update(_HAS_GROUP_SOURCE_PATTERN.findall(code))
    return found


def _expand_user_groups_ordered(G: nx.DiGraph, user_groups: List[str]) -> List[str]:
    if not user_groups:
        return []

    from code_intelligence.rules.group_resolver import _expand_implied_user_groups

    explicit_seen: Set[str] = set()
    ordered_groups: List[str] = []
    for ug in user_groups:
        s = str(ug)
        if s not in explicit_seen:
            explicit_seen.add(s)
            ordered_groups.append(s)

    implied_set: Set[str] = set()
    for g in ordered_groups:
        _expand_implied_user_groups(G, g, implied_set)

    implied_sorted: List[str] = sorted(g for g in implied_set if g not in explicit_seen)
    return ordered_groups + implied_sorted


def _has_elevated_access(G: nx.DiGraph, model_name: str, user_groups: List[str]) -> bool:
    if not model_name:
        return False

    from code_intelligence.rules.access_evaluator import _eval_single_permission
    from code_intelligence.rules.group_resolver import resolve_group_identifier

    expanded_groups = _expand_user_groups_ordered(G, user_groups)

    source_has_group_ids = _extract_has_group_xmlids_from_source(G, model_name)
    if source_has_group_ids:
        candidate_groups = list(source_has_group_ids)
        return any(
            resolve_group_identifier(G, str(ug), candidate_groups) is not None
            for ug in expanded_groups
        )

    write_groups, write_auth, *_ = _eval_single_permission(G, model_name, "write")
    unlink_groups, unlink_auth, *_ = _eval_single_permission(G, model_name, "unlink")

    if write_auth or unlink_auth:
        # ACL grants the right to all authenticated users -- not gated.
        return True

    candidate_groups = list(write_groups | unlink_groups)
    if not candidate_groups:
        return False

    return any(
        resolve_group_identifier(G, str(ug), candidate_groups) is not None
        for ug in expanded_groups
    )


def _find_elevating_group(G: nx.DiGraph, model_name: str, user_groups: List[str]) -> Optional[str]:
    if not model_name or not user_groups:
        return None

    from code_intelligence.rules.access_evaluator import _eval_single_permission
    from code_intelligence.rules.group_resolver import resolve_group_identifier

    expanded_groups = _expand_user_groups_ordered(G, user_groups)

    source_has_group_ids = _extract_has_group_xmlids_from_source(G, model_name)
    if source_has_group_ids:
        candidate_groups = list(source_has_group_ids)
        for ug in expanded_groups:
            resolved = resolve_group_identifier(G, str(ug), candidate_groups)
            if resolved is not None:
                return resolved
        return None

    write_groups, write_auth, *_ = _eval_single_permission(G, model_name, "write")
    unlink_groups, unlink_auth, *_ = _eval_single_permission(G, model_name, "unlink")
    if write_auth or unlink_auth:
        return None  # Elevated for everyone -- not a distinguishing fact.

    candidate_groups = list(write_groups | unlink_groups)
    if not candidate_groups:
        return None
    for ug in expanded_groups:
        resolved = resolve_group_identifier(G, str(ug), candidate_groups)
        if resolved is not None:
            return resolved
    return None


def _redact_sensitive_bypass_lines(
    observation: str,
    model_name: str,
    G: nx.DiGraph,
    user_groups: List[str],
) -> Tuple[str, List[OmittedItem]]:
    from code_intelligence.utils import SENSITIVE_BYPASS_MARKER

    if SENSITIVE_BYPASS_MARKER not in observation:
        return observation, []
    if _has_elevated_access(G, model_name, user_groups):
        return observation, []

    omitted: List[OmittedItem] = []
    out_lines: List[str] = []
    for line in observation.splitlines():
        if SENSITIVE_BYPASS_MARKER not in line:
            out_lines.append(line)
            continue

        detail = line.split(SENSITIVE_BYPASS_MARKER, 1)[1].strip(" -")
        label = (detail.split(":")[0].strip() if detail else "") or "mécanisme de contournement de sécurité"
        model_suffix = f" ({model_name})" if model_name else ""
        omitted.append(OmittedItem(
            label=f"{label}{model_suffix}",
            reason=(
                f"Élément omis pour raison d'autorisation ({_OMITTED_MARKER}) : cette ligne "
                "décrit un mécanisme de contournement de sécurité (accès privilégié codé en "
                "dur, sudo(), ou traitement non documenté hors des ACL/ir.rule standards) et "
                f"le demandeur ne dispose pas d'un accès élevé sur '{model_name}'." if model_name else
                f"Élément omis pour raison d'autorisation ({_OMITTED_MARKER}) : cette ligne "
                "décrit un mécanisme de contournement de sécurité."
            ),
        ))
        out_lines.append(f"  - [{_OMITTED_MARKER}] (détail masqué -- mécanisme de contournement de sécurité)")

    return "\n".join(out_lines), omitted


def gate_observation(
    tool_name: str,
    model_name: str,
    observation: str,
    G: nx.DiGraph,
    user_groups: List[str],
    rule_result: Optional["object"] = None,
) -> Tuple[str, List[OmittedItem]]:

    omitted_items: List[OmittedItem] = []

    observation, bypass_omitted = _redact_sensitive_bypass_lines(observation, model_name, G, user_groups)
    omitted_items.extend(bypass_omitted)

    return observation, omitted_items
