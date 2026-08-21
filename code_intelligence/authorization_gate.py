"""
code_intelligence/authorization_gate.py

Bloc 7 / J23-J24, REVISED after J22 decision review: targeted gating, not
generalized gating. History:

  J22 decision (as first recorded): "toute explication filtrée selon les
  droits du demandeur" -- gate an ENTIRE tool observation whenever the
  demandeur lacked elevated access on the model it concerned.

  J23-24 build + first benchmark run: implemented as designed. Regression
  found in the SAME benchmark run: analyze_security_locks mixes
  legitimate governance content (which groups can approve, standard
  thresholds) with the actual sensitive bypass content (hardcoded
  privileged emails, sudo() escapes) in ONE block. Gating the whole block
  made routine questions like "qui a le permission d'approuver un avoir de
  25 000e ?" unanswerable for most requesters -- collateral damage far
  beyond the actual gap (test adversarial 3's hidden validator list).

  Revised decision: tag ONLY the specific bypass-revealing line(s) AT THE
  SOURCE (semgrep_locks_analyzer.py, server_action_analyzer.py) with the
  shared code_intelligence.utils.SENSITIVE_BYPASS_MARKER, and redact ONLY
  those marked lines here -- never the surrounding governance content. The
  guiding principle going forward: the Code Intelligence agent should
  answer everyone on how the system's normal governance works; access
  control belongs primarily on ERP DATA (already covered by the Function
  Calling ERP branch, out of this module's scope), not on explanations of
  how the system is designed -- EXCEPT for the narrow case of an actual
  undisclosed security bypass, which is what this module still protects.

Gating happens PER TOOL OBSERVATION, before synthesis ever sees the text.
This is deliberate: filtering only the final synthesized answer (e.g. by
regexing sensitive strings out of it afterwards) would not catch the
synthesis LLM paraphrasing an omitted fact in its own words. Gating the
raw observation removes the fact from the LLM's context entirely, so it
cannot leak it back out reworded.

Exactly ONE source of privileged content is gated (REVISED 2026-08-07,
see conversation with maître de stage the same day -- real plan.md /
etat_reel.md Bloc 7 entry):

Lines explicitly tagged SENSITIVE_BYPASS_MARKER by the analyzer that
produced them (semgrep_locks_analyzer.py: hardcoded privileged logins;
server_action_analyzer.py: sudo() calls, hardcoded ID lists). Redacted
unless the demandeur holds elevated access on the model the observation
concerns (see _has_elevated_access) -- everything else in the SAME
observation (normal has_group() checks, dynamic-dispatch uncertainty
caveats, approval group listings) is left untouched, tool-name-agnostic:
any tool's output gets this same line-level treatment, so a future
analyzer only needs to tag its own sensitive lines, not be registered
in an allowlist here.

ir.rule group rules the demandeur is NOT a member of (via
RuleEvaluationResult.ignored_group_rules) are DELIBERATELY NOT gated
anymore, even though an earlier version of this module did strip their
name and domain_force. Reviewed 2026-08-07: a rule like "Avoirs -
plafond visibilite regionale (50000e)" describes WHO can see WHAT under
which scope -- that is governance content, the same category as "qui
peut approuver un avoir de 25000e ?", not a security bypass. Gating it
by group membership reproduces, on a smaller scale, exactly the mistake
the J23-24 revision above already fixed once for the whole-observation
case: it makes a legitimate "pourquoi je ne vois pas cet avoir ?"
question unanswerable for precisely the users who would ask it. Only an
actual bypass mechanism (SENSITIVE_BYPASS_MARKER) still withholds
identity-dependent content; a scoping/visibility ir.rule never does,
regardless of the demandeur's groups.

Every omission is recorded as an explicit OmittedItem -- never silently
dropped -- and is kept separate from sourcing_guard.py's citation
verification and from the response's confidence score, per J23-24's own
requirement: "distinct du score de couverture (A1), pour ne pas casser
le principe de sourcing".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set, Tuple

import networkx as nx

_OMITTED_MARKER = "ELEMENT OMITTED FOR AUTHORIZATION REASON"

# J25-26 fix: same has_group('xml.id') detection already trusted for
# ir.actions.server code (server_action_analyzer.py's _HAS_GROUP_PATTERN),
# reused here against a model's own regular Python source files.
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
    """
    J25-26 fix (see test_j25_26_e2e_purchase_bypass_gate.py): statically
    extract the group xml_ids a model's OWN Python source code checks via
    has_group('xml.id') (e.g. inside an action_valider() guard).

    _has_elevated_access() previously used generic ORM write/unlink access
    as its sole proxy for "elevated". That proxy is correct only when the
    model's write ACL itself represents management-level access (true for
    a model whose write ACL is scoped to an actual manager group). It
    silently breaks for a model like custom.purchase.request, whose write
    ACL is granted broadly to base.group_user (every employee, so they can
    edit their OWN records) while the REAL approval/bypass gate is enforced
    separately in Python via has_group('purchase.group_purchase_manager').
    The same mismatch, less extreme, was also found on account.move: its
    supplementary ACL (custom_credit_note_approval) grants write to
    account.group_account_invoice, but action_valider_avoir()'s actual
    guard checks the stricter account.group_account_manager.

    When the model's own source code declares such a check, it is a
    strictly more specific and authoritative signal of what "elevated"
    means for THIS model's security-bypass content than the generic ORM
    ACL -- so it takes priority over write/unlink when present (see
    _has_elevated_access).

    Deliberately simple regex, mirroring server_action_analyzer.py's own
    _HAS_GROUP_PATTERN (same detection already trusted for ir.actions.server
    code) -- this is a detection aid for gating, not a claim about runtime
    control flow: a has_group() call that turns out to be unreachable would
    still be picked up, same conservative bias as analyze_security_locks
    itself (a static match errs toward gating more, never less).

    Reuses find_model_source_filepaths (ci_agent_tools.py) rather than
    re-implementing "which files belong to this model" a third time --
    exactly the duplication that caused the F-08 rule-indexing bug in J7.
    Returns an empty set (never raises) for models with no resolvable
    source files, e.g. the synthetic graphs used by
    test_j23_24_authorization_gate.py / test_j23_24_group_id_xmlid_resolution.py,
    which have no HAS_FIELD/Method nodes -- _has_elevated_access falls back
    to the write/unlink ACL check unchanged in that case.
    """
    from code_intelligence.ci_agent_tools import find_model_source_filepaths

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
    """
    Expand user_groups with transitively implied groups while strictly preserving order:
    1. Explicit user_groups in their original order (deduplicated, first-seen).
    2. Implied groups (recursively inherited via IMPLIES edges) added afterwards, sorted alphabetically.

    This ensures deterministic behavior for functions like _find_elevating_group()
    which return the first matching group in user_groups order, while expanding
    transitive group memberships.
    """
    if not user_groups:
        return []

    from code_intelligence.deterministic_tools import _expand_implied_user_groups

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
    """
    True if the demandeur's real Odoo groups (never LLM-guessed -- see
    rag/graph.py's _override_user_groups_arg) grant elevated access to
    model_name's security-bypass content.

    J25-26 fix: when the model's own Python source declares an explicit
    has_group('xml.id') check (see _extract_has_group_xmlids_from_source),
    that check is authoritative and used INSTEAD of the generic write/
    unlink ACL proxy below -- the source code's own guard is always at
    least as specific as a blanket ORM permission, and per the cases
    documented in _extract_has_group_xmlids_from_source's docstring, is
    sometimes strictly narrower (correctly so). Only when the source
    declares no such check at all does this fall back to write/unlink,
    which remains the right proxy for a model with no explicit Python-level
    group guard.

    Read-only access, or no resolvable access at all, is NOT elevated.

    Deliberately does NOT early-return on an empty user_groups (only on a
    missing model_name) -- regression caught 2026-08-20 via
    test_gated_tool_all_authenticated_write_is_not_omitted: an ACL open to
    all authenticated users (the write_auth/unlink_auth shortcut below)
    must still return True even when user_groups is empty, since "elevated
    for everyone" does not depend on which groups the demandeur happens to
    hold. A combined `or not user_groups` guard here would short-circuit
    before that shortcut is ever reached, silently gating a demandeur on a
    model nobody is actually gated on.
    """
    if not model_name:
        return False

    from code_intelligence.deterministic_tools import (
        _eval_single_permission,
        resolve_group_identifier,
    )

    expanded_groups = _expand_user_groups_ordered(G, user_groups)

    source_has_group_ids = _extract_has_group_xmlids_from_source(G, model_name)
    if source_has_group_ids:
        candidate_groups = list(source_has_group_ids)
        return any(
            resolve_group_identifier(G, str(ug), candidate_groups) is not None
            for ug in expanded_groups
        )

    write_groups, write_auth, _ = _eval_single_permission(G, model_name, "write")
    unlink_groups, unlink_auth, _ = _eval_single_permission(G, model_name, "unlink")

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
    """
    Bloc 9 gap, found 2026-08-11 (elevated-approver mention dropped by
    synthesis under Groq rate-limit stress -- confirmed live: the real-
    auth override log line "overriding LLM-guessed user_groups_json ([])
    with the real requester groups (['account.group_account_manager'])"
    shows the elevation was resolved correctly, but the small model's
    synthesis never stated it in the final answer even though the fact
    was in its context). This is a pure reliability gap, not a security
    one -- the demandeur was never denied anything real, since every tool
    call already used the real override (rag/graph.py's
    _override_user_groups_arg). rag/graph.py's deterministic backfill for
    it needs the SPECIFIC group name to state as fact, not just a bool.

    Deliberately duplicates _has_elevated_access's detection logic exactly
    (same has_group()-source-priority-over-ACL ordering, same conditions)
    rather than changing that function's return type -- it is a Bloc 7
    security-gating primitive and stays untouched here. Returns the first
    matching group xml_id in user_groups order (with implied groups
    checked afterwards in sorted order), or None under the exact same
    conditions _has_elevated_access would return False (including: the ACL
    grants access to all authenticated users, which is elevation for nobody
    in particular and not a fact worth singling out).
    """
    if not model_name or not user_groups:
        return None

    from code_intelligence.deterministic_tools import (
        _eval_single_permission,
        resolve_group_identifier,
    )

    expanded_groups = _expand_user_groups_ordered(G, user_groups)

    source_has_group_ids = _extract_has_group_xmlids_from_source(G, model_name)
    if source_has_group_ids:
        candidate_groups = list(source_has_group_ids)
        for ug in expanded_groups:
            resolved = resolve_group_identifier(G, str(ug), candidate_groups)
            if resolved is not None:
                return resolved
        return None

    write_groups, write_auth, _ = _eval_single_permission(G, model_name, "write")
    unlink_groups, unlink_auth, _ = _eval_single_permission(G, model_name, "unlink")
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
    """
    Bloc 7 (J23-24, revised): redact ONLY the line(s) tagged
    SENSITIVE_BYPASS_MARKER at the source (semgrep_locks_analyzer.py,
    server_action_analyzer.py) -- never the observation as a whole. Applies
    to any tool's output uniformly: there is no tool-name allowlist here
    anymore, just "does this line carry the marker".

    A quick short-circuit (marker not present at all) means this is a
    no-op for the vast majority of observations, which carry no bypass
    content to begin with.
    """
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
        # Best-effort short label for the report: the text right after the
        # marker up to the first colon (e.g. "SUDO détecté", "Logins/Emails
        # privilégies en dur") -- purely descriptive, never the sensitive
        # payload itself (which stays out of both the label and out_lines).
        detail = line.split(SENSITIVE_BYPASS_MARKER, 1)[1].strip(" -")
        label = (detail.split(":")[0].strip() if detail else "") or "mécanisme de contournement de sécurité"
        model_suffix = f" ({model_name})" if model_name else ""
        omitted.append(OmittedItem(
            label=f"{label}{model_suffix}",
            reason=(
                f"{_OMITTED_MARKER} : cette ligne décrit un mécanisme de contournement de "
                "sécurité (accès privilégié codé en dur, sudo(), ou traitement non documenté "
                "hors des ACL/ir.rule standards) et le demandeur ne dispose pas d'un accès "
                f"élevé sur '{model_name}'." if model_name else
                f"{_OMITTED_MARKER} : cette ligne décrit un mécanisme de contournement de sécurité."
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
    """
    Gate a single tool observation against the demandeur's real rights.

    rule_result: the RuleEvaluationResult already computed for this exact
    evaluate_record_rules call, if tool_name is that tool (the
    caller in rag/graph.py already computes it once for the
    can_view_amount deterministic fact -- reused here rather than
    recomputed a second time).

    Returns (gated_text, omitted_items). gated_text is what should be
    handed to the synthesis LLM instead of the raw observation;
    omitted_items (possibly empty, never None) is extended by the caller
    into the response's omitted_for_authorization list.
    """
    omitted_items: List[OmittedItem] = []

    # NOTE (revised 2026-08-07): ir.rule names/domain_force for groups the
    # demandeur isn't a member of used to be stripped here via
    # rule_result.ignored_group_rules. That masking is intentionally gone
    # -- see this module's docstring for why (governance/scoping content,
    # not a security bypass). rule_result is still accepted as a parameter
    # for forward compatibility, but is currently unused by this function.

    # Bloc 7 (J23-24, revised): source-tagged bypass lines are redacted
    # regardless of which tool produced them -- applies uniformly, after
    # the ir.rule-specific handling above (independent concerns, can both
    # apply to the same observation in principle, though in practice no
    # current tool triggers both at once).
    observation, bypass_omitted = _redact_sensitive_bypass_lines(observation, model_name, G, user_groups)
    omitted_items.extend(bypass_omitted)

    return observation, omitted_items
