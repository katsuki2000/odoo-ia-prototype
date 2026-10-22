"""
code_intelligence/deterministic/access_evaluator.py

Evaluation of model-level Access Control Lists (ACLs, ir.model.access)
and combining with ir.rule record rules.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
import networkx as nx

from code_intelligence.rules.model_suggestions import model_not_found_message
from code_intelligence.rules.group_resolver import (
    _expand_implied_user_groups,
    _expand_inheriting_acl_groups,
    get_group_display_name,
    resolve_group_identifier,
)
from code_intelligence.rules.record_rules import RuleDetail
from code_intelligence.rules.ontology import tags_for_node_attrs
from code_intelligence.rules.relevance_budget import assemble_relevance_ranked_blocks
from code_intelligence.utils import format_xml_id_citation, format_xml_id_citations
from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence


@dataclass
class AccessEvaluationResult:
    model_name: str
    requested_permission: str
    allowed_groups: List[str] = field(default_factory=list)
    all_authenticated_access: bool = False
    active_rules: List[RuleDetail] = field(default_factory=list)
    client_side_checks: List[Dict[str, Any]] = field(default_factory=list)
    summary_text: str = ""
    # B1 replication of the B0 pilot: structured Evidence produced at the source.
    evidence: List[Evidence] = field(default_factory=list)


def requester_acl_summary(
    G: nx.DiGraph,
    model_name: str,
    user_groups: Optional[List[str]],
    groups_known: bool,
) -> tuple[str, List[Evidence], Optional[Dict[str, bool]]]:
    if not groups_known:
        return (
            f"[REQUESTER ACL STATUS] The authenticated requester's groups could not be fully resolved; "
            f"do not infer this user's access from the generic ACL matrix for '{model_name}'.",
            [],
            None,
        )

    if f"model:{model_name}" not in G:
        return (
            f"[REQUESTER ACL STATUS] The model '{model_name}' is not present in the code graph; "
            "the personalized ACL verdict is unknown. Do not infer it from the generic ACL matrix.",
            [],
            None,
        )

    effective_groups = set(user_groups or [])
    unresolved_groups = [group for group in effective_groups if f"group:{group}" not in G]
    if unresolved_groups:
        return (
            f"[REQUESTER ACL STATUS] The requester's groups are not fully represented in the code graph "
            f"for '{model_name}' ({', '.join(sorted(unresolved_groups))}); "
            "the personalized ACL verdict is unknown. "
            "Do not infer it from the generic ACL matrix.",
            [],
            None,
        )

    for group in list(effective_groups):
        _expand_implied_user_groups(G, group, effective_groups)

    labels = {"read": "READ", "write": "WRITE", "create": "CREATE", "unlink": "DELETE"}
    lines = [f"[AUTHENTICATED REQUESTER ACL VERDICT — model '{model_name}']"]
    evidence = []
    verdicts = {}
    labels_by_outcome: Dict[tuple, List[str]] = {}
    for permission, label in labels.items():
        allowed_groups, all_authenticated, _rules, _inherited_via = _eval_single_permission(
            G, model_name, permission,
        )
        matching_groups = sorted(effective_groups.intersection(allowed_groups))
        granted = all_authenticated or bool(matching_groups)
        verdicts[permission] = granted
        if all_authenticated:
            reason = "granted to all authenticated users"
        elif matching_groups:
            reason = f"through {', '.join(matching_groups)}"
        else:
            reason = "no effective requester group has this ACL grant"
        verdict = "GRANTED" if granted else "DENIED"
        labels_by_outcome.setdefault((verdict, reason), []).append(label)
        claim = (
            f"Authenticated requester has model-level {permission} ACL access to '{model_name}'"
            if granted else
            f"Authenticated requester lacks model-level {permission} ACL access to '{model_name}'"
        )
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=claim,
            source=f"requester_acl:{model_name}:{permission}",
            value={"granted": granted, "matching_groups": matching_groups},
            confidence="HIGH",
            scope={"requester_groups": sorted(effective_groups), "decision_layer": "model_acl"},
        ))

    for (verdict, reason), outcome_labels in labels_by_outcome.items():
        lines.append(f"{', '.join(outcome_labels)}: {verdict} ({reason}).")
    lines.append(
        "Scope: this is the model-level ACL decision only; record rules and model business logic "
        "may further restrict access to particular records or operations."
    )
    return "\n".join(lines), evidence, verdicts


def _build_access_evidence(
    model_name: str,
    permission: str,
    allowed_groups: Set[str],
    all_authenticated: bool,
    active_rules: List[RuleDetail],
    group_id: Optional[str] = None,
) -> List[Evidence]:
    """
    B1: one Evidence for the ACL grant fact, plus one Evidence per active ir.rule found.
    """
    scope: Dict[str, Any] = {"group_id": group_id} if group_id else {}
    evidence: List[Evidence] = []

    if all_authenticated:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"ACL grants {permission} access on '{model_name}' to all authenticated users",
            source=f"acl:{model_name}:{permission}",
            value=True,
            confidence="HIGH",
            scope=scope,
        ))
    elif allowed_groups:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"ACL grants {permission} access on '{model_name}' to groups: {', '.join(sorted(allowed_groups))}",
            source=f"acl:{model_name}:{permission}",
            value=sorted(allowed_groups),
            confidence="HIGH",
            scope=scope,
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"No ACL explicitly grants {permission} access on '{model_name}'",
            source=f"acl:{model_name}:{permission}",
            value=None,
            confidence="HIGH",
            scope=scope,
        ))

    for rule in active_rules:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"ir.rule '{rule.rule_name}' can further restrict {permission} access "
                f"on '{model_name}' (groups: {', '.join(rule.groups) if rule.groups else 'global, applies to all'})"
            ),
            source=f"rule:{rule.rule_xml_id}",
            value=rule.domain_force,
            confidence="HIGH",
            scope=scope,
        ))

    return evidence


def _eval_single_permission(G: nx.DiGraph, model_name: str, permission: str, group_id: Optional[str] = None):
    model_node = f"model:{model_name}"
    perm_attr = f"perm_{permission}" if permission in {"read", "write", "create", "unlink"} else "perm_read"

    if model_node not in G:
        return set(), False, [], {}

    allowed_groups: Set[str] = set()
    all_authenticated = False
    active_rules: List[RuleDetail] = []
    # Section 848: {inheriting_group: direct_acl_group} -- which groups in
    # allowed_groups got there only via implied_ids, and which direct ACL
    # they inherited it from. Empty for groups that hold the ACL themselves.
    inherited_via: Dict[str, str] = {}

    for neighbor in G.neighbors(model_node):
        edge_data = G.get_edge_data(model_node, neighbor) or {}
        edge_type = edge_data.get("edge_type")

        if edge_type == "GRANTED_BY" and G.nodes[neighbor].get("node_type") == "AccessEntry":
            acl_node = G.nodes[neighbor]
            if acl_node.get(perm_attr, False):
                if acl_node.get("all_authenticated", False):
                    all_authenticated = True

                for acl_neighbor in G.neighbors(neighbor):
                    acl_edge = G.get_edge_data(neighbor, acl_neighbor) or {}
                    if acl_edge.get("edge_type") == "APPLIES_TO_GROUP":
                        grp_xml_id = acl_neighbor.replace("group:", "")
                        allowed_groups.add(grp_xml_id)
                        inherited_via.update(_expand_inheriting_acl_groups(G, grp_xml_id, allowed_groups))

        elif edge_type == "RESTRICTED_BY" and G.nodes[neighbor].get("node_type") == "Rule":
            rule_node = G.nodes[neighbor]
            # Inactive rules (active=0) are kept in the graph but never enforced.
            if rule_node.get("active", True) and rule_node.get(perm_attr, True):
                rule_groups = []
                for rule_neighbor in G.neighbors(neighbor):
                    rule_edge = G.get_edge_data(neighbor, rule_neighbor) or {}
                    if rule_edge.get("edge_type") == "APPLIES_TO_GROUP":
                        grp_xml_id = rule_neighbor.replace("group:", "")
                        rule_groups.append(grp_xml_id)

                active_rules.append(
                    RuleDetail(
                        rule_xml_id=rule_node.get("xml_id", neighbor.replace("rule:", "")),
                        rule_name=rule_node.get("name", ""),
                        domain_force=rule_node.get("domain_force", ""),
                        groups=rule_groups,
                        tags=tags_for_node_attrs(rule_node),
                    )
                )

    return allowed_groups, all_authenticated, active_rules, inherited_via


def _format_group_with_display_name(G: Optional[nx.DiGraph], group_xml_id: str) -> str:
    dname = get_group_display_name(G, group_xml_id)
    return f"{group_xml_id} ('{dname}')" if dname else group_xml_id


def _annotate_inherited(
    groups: List[str],
    inherited_via: Dict[str, str],
    G: Optional[nx.DiGraph] = None,
) -> str:
    """Section 848 / 944: render a sorted group list with display names
    and an inline "(via implied_ids <- X)" annotation on any group present only because
    it implies another group's direct ACL -- see _expand_inheriting_acl_groups.

    Section 948 (todo/contexte.txt): direct (non-via) groups are listed
    BEFORE via-only groups -- each tier still alphabetically sorted within
    itself, rather than one single alphabetical interleaving. A group's own
    direct grant is the single highest-value, non-redundant fact in this
    list; every via-annotated entry is a derivative repetition of ANOTHER
    group's same grant (one widely-implied group, e.g. base.group_user, can
    produce dozens of these). The naive head-truncation this observation is
    later subject to (_truncate_observation, context.py) previously had
    equal odds of cutting BEFORE a direct grant that happened to sort late
    alphabetically among many via-entries -- confirmed root cause of a real
    wrong answer on STK-Q1 (section 893: base.group_user's own direct WRITE
    grant on stock.move.line sat past the old cap, hidden behind other
    groups' via-annotations). Prioritizing direct grants first protects the
    least redundant, highest-information content from being the one
    silently dropped."""
    direct = [g for g in sorted(groups) if not inherited_via.get(g)]
    via_only = [g for g in sorted(groups) if inherited_via.get(g)]
    parts = []
    for g in direct + via_only:
        via = inherited_via.get(g)
        g_fmt = _format_group_with_display_name(G, g)
        if via:
            via_fmt = _format_group_with_display_name(G, via)
            parts.append(f"{g_fmt} (via implied_ids <- {via_fmt})")
        else:
            parts.append(g_fmt)
    return ", ".join(parts)


def who_has_access_to(
    G: nx.DiGraph,
    model_name: str,
    permission: str = "read",
    group_id: Optional[str] = None
) -> AccessEvaluationResult:
    """
    Evaluates access rights for a given model and permission type.
    Combines CSV ACLs, ir.rule domain_force expressions, res.groups implied hierarchy, and JS client checks.
    Supports permission='all' to evaluate all 4 permissions in a single pass.
    """
    model_node = f"model:{model_name}"

    if model_node not in G:
        return AccessEvaluationResult(
            model_name=model_name,
            requested_permission=permission,
            summary_text=model_not_found_message(G, model_name)
        )

    if permission.lower() == "all":
        rights_summary = []
        all_allowed: Set[str] = set()
        all_rules: List[RuleDetail] = []
        all_auth = False
        all_evidence: List[Evidence] = []

        for p in ["read", "write", "create", "unlink"]:
            grps, auth, rules, inherited_via = _eval_single_permission(G, model_name, p, group_id)
            all_allowed.update(grps)
            all_rules.extend(rules)
            if auth:
                all_auth = True
            all_evidence.extend(_build_access_evidence(model_name, p, grps, auth, rules, group_id))

            # Section 848 / 944: annotate any group present only via implied_ids
            # inheritance, not its own direct ACL, with functional display names.
            grp_str = "All authenticated users" if auth else (_annotate_inherited(list(grps), inherited_via, G) if grps else "None")
            _grp_citations = format_xml_id_citations(sorted(grps)) if (grps and not auth) else ""
            _grp_suffix = f" ({_grp_citations})" if _grp_citations else ""
            rights_summary.append(f"[{p.upper()}]: {grp_str} (Rules: {len(rules)}){_grp_suffix}")

        header = f"Access Matrix for '{model_name}':"
        from code_intelligence.agent.context import PER_TOOL_OBSERVATION_CAPS
        from code_intelligence.agent.tools.helpers import get_current_question
        # Section 950 (todo/contexte.txt section 948, point 1): the 4
        # permission blocks used to be flat-joined and left to the
        # generic, position-blind head-truncation in
        # context.py::_truncate_observation, which drops whichever
        # block(s) sit AFTER wherever the cut lands, in fixed READ/WRITE/
        # CREATE/UNLINK order regardless of which permission the question
        # actually asks about (confirmed root cause of STK-Q1, section
        # 894 -- write.access.group_user sat past the old cap and was
        # silently dropped). assemble_relevance_ranked_blocks keeps every
        # block in that same original order in the OUTPUT, but decides
        # which one(s) survive a cut by relevance to the question instead
        # of pure position -- a no-op when everything already fits.
        body_budget = max(0, PER_TOOL_OBSERVATION_CAPS.get("who_has_access_to", 11000) - len(header) - 1)
        body = assemble_relevance_ranked_blocks(
            rights_summary, body_budget, question=get_current_question(), separator="\n",
        )
        summary = f"{header}\n{body}"

        return AccessEvaluationResult(
            model_name=model_name,
            requested_permission="all",
            allowed_groups=sorted(list(all_allowed)),
            all_authenticated_access=all_auth,
            active_rules=all_rules,
            summary_text=summary,
            evidence=all_evidence,
        )

    # Single permission evaluation
    allowed_groups, all_authenticated, active_rules, inherited_via = _eval_single_permission(G, model_name, permission, group_id)

    if group_id:
        resolved_group_id = resolve_group_identifier(G, group_id, list(allowed_groups)) if allowed_groups else None
        if resolved_group_id is None and not all_authenticated:
            summary = (
                f"Group identifier '{group_id}' could not be resolved against any group "
                f"with {permission.upper()} rules or ACLs on '{model_name}'. This does NOT mean "
                f"access is denied -- it means the identifier itself could not be matched. "
                f"Try list_involved_modules or resolve_technical_name to find the exact group xml_id."
            )
        else:
            has_access = all_authenticated or (resolved_group_id is not None)
            display_id = resolved_group_id or group_id
            _display_citation = format_xml_id_citation(display_id)
            dname = get_group_display_name(G, display_id)
            dname_suffix = f" ('{dname}')" if dname else ""
            # Section 848 / 944: same implied_ids annotation with display names for single-group query.
            _via = inherited_via.get(display_id) if resolved_group_id else None
            if _via:
                _via_fmt = _format_group_with_display_name(G, _via)
                _via_suffix = f" (via implied_ids <- {_via_fmt})"
            else:
                _via_suffix = ""
            summary = (
                f"Group '{display_id}'{dname_suffix} HAS {permission.upper()} access to '{model_name}'{_via_suffix}. ({_display_citation})"
                if has_access
                else f"Group '{display_id}'{dname_suffix} DOES NOT HAVE {permission.upper()} access to '{model_name}'. ({_display_citation})"
            )
    else:
        if all_authenticated:
            grp_str = "All authenticated users"
        elif allowed_groups:
            grp_str = _annotate_inherited(list(allowed_groups), inherited_via, G)
        else:
            grp_str = "No groups explicitly granted"

        _allowed_citations = (
            format_xml_id_citations(sorted(allowed_groups))
            if (allowed_groups and not all_authenticated) else ""
        )
        _allowed_suffix = f" ({_allowed_citations})" if _allowed_citations else ""
        summary = f"Model '{model_name}' [{permission.upper()}]: Granted to {grp_str}.{_allowed_suffix} Active Rules: {len(active_rules)}."

    return AccessEvaluationResult(
        model_name=model_name,
        requested_permission=permission,
        allowed_groups=sorted(list(allowed_groups)),
        all_authenticated_access=all_authenticated,
        active_rules=active_rules,
        client_side_checks=[],
        summary_text=summary,
        evidence=_build_access_evidence(model_name, permission, allowed_groups, all_authenticated, active_rules, group_id),
    )


# ── Section 955: single-fact synthesis-inversion guard for ACL permission ──
# verdicts (STK-Q1, todo/contexte.txt sections 952/954). Same family as
# _correct_can_view_amount_contradictions / _correct_security_lock_
# threshold_contradictions / _answer_denies_other_overrides: the parsed
# observation ("Group '...' HAS/DOES NOT HAVE {PERM} access to '{model}'")
# is a single, unambiguous, already-correct fact; the bug is the LLM's own
# prose asserting the exact opposite. Deliberately scoped as a splice-out
# correction against a known-good fact, not core/evidence_sufficiency.py's
# CONFLICTING status (H3 proper), which is reserved for two VALID findings
# disagreeing with each other -- see EvidenceSufficiencyStatus docstring.
import logging
import re

_access_logger = logging.getLogger(__name__)

_ACCESS_VERDICT_RE = re.compile(
    r"Group\s+'[^']*'(?:\s*\([^)]*\))?\s+(HAS|DOES NOT HAVE)\s+"
    r"(READ|WRITE|CREATE|UNLINK)\s+access\s+to\s+'([^']+)'",
)

# Verb stems per permission, matched against French synthesis prose.
# Intentionally not exhaustive NLU -- same targeted-pattern discipline as
# _CAN_VIEW_ALLOW_ASSERTION_RE/_CAN_VIEW_DENY_ASSERTION_RE in
# can_view_verifier.py: catches the known phrasings the synthesis prompt's
# own vocabulary produces, not every conceivable paraphrase.
_ACCESS_VERBS_FR = {
    "READ": r"consult\w*|voir|lire|acc[ée]d\w*",
    "WRITE": r"modifi\w*|chang\w*|[ée]dit\w*|mettre\s+[àa]\s+jour",
    "CREATE": r"cr[ée][ée]?r?\w*",
    "UNLINK": r"supprim\w*|effac\w*",
}


def _access_deny_re(verb_re: str) -> "re.Pattern":
    return re.compile(
        rf"(?:ne\s+peut\s+pas|ne\s+(?:poss[èe]de|dispose)\s+pas\s+(?:du|de\s+la|le)?\s*"
        rf"(?:droit|permission)\s+de|n['’]a\s+pas\s+(?:le\s+droit|la\s+permission)\s+de|"
        rf"n['’]est\s+pas\s+autoris[ée]\w*\s+[àa])\s*(?:{verb_re})",
        re.IGNORECASE,
    )


def _access_allow_re(verb_re: str) -> "re.Pattern":
    return re.compile(
        rf"(?<!ne\s)(?<!pas\s)\bpeut\s+(?:{verb_re})|"
        rf"\b(?:a|dispose\s+du|poss[èe]de\s+le)\s+droit\s+de\s+(?:{verb_re})|"
        rf"\best\s+autoris[ée]\w*\s+[àa]\s+(?:{verb_re})",
        re.IGNORECASE,
    )


_ACCESS_VERB_WORDS = {"READ": "consulter", "WRITE": "modifier", "CREATE": "créer", "UNLINK": "supprimer"}
# Section 956: a naive "up to the first period" split breaks on the
# model's OWN internal period ("stock.quant" -> stops at "stock."). A
# real sentence end is a period followed by whitespace or end-of-block;
# "stock.quant" is followed immediately by "q", so the lookahead skips it.
_ACCESS_SENTENCE_RE = re.compile(r"[^\n]*?\.(?=\s|$)")


def _correct_access_permission_contradictions(final_answer: str, scoped_tool_output: str) -> str:
    """Detect and correct a synthesis-level inversion of a who_has_access_to
    verdict: the observation says HAS/DOES NOT HAVE a given permission on a
    given model, the prose asserts the opposite.

    Section 956 (todo/contexte.txt): the STK-Q1 rejeu that confirmed the
    section 955 fix on the WRITE volet also showed READ still uninverted --
    the denial sentence ("ne peut pas consulter les quantités en stock")
    never names `stock.quant` at all, only the FOLLOWING sentence does
    ("...enregistrements de stock.quant"). A same-sentence match therefore
    missed it. Scoped one level up instead, to the paragraph/block (text
    between blank lines) that mentions the model literally -- close enough
    to keep the correction targeted (this codebase's own citation
    discipline still puts the model name near its verdict, just not always
    in the identical sentence), while a block naming a DIFFERENT model that
    also has its own fact this turn is skipped entirely, so a two-model
    answer (STK-Q1 itself: stock.quant + stock.move.line) never lets one
    model's correction bleed into the other's paragraph."""
    if not scoped_tool_output:
        return final_answer
    facts = _ACCESS_VERDICT_RE.findall(scoped_tool_output)
    if not facts:
        return final_answer

    footer_idx = final_answer.find("[Source:")
    prose_end = footer_idx if footer_idx != -1 else len(final_answer)
    corrected = final_answer
    all_models = [m for _, _, m in facts]

    for verdict, permission, model in facts:
        has_access = verdict == "HAS"
        verb_re = _ACCESS_VERBS_FR.get(permission)
        if not verb_re:
            continue
        model_re = re.escape(model)
        other_models_re = [re.escape(m) for m in all_models if m != model]
        deny_re = _access_deny_re(verb_re)
        allow_re = _access_allow_re(verb_re)

        for block in re.split(r"\n\s*\n", corrected[:prose_end]):
            if not re.search(model_re, block, re.IGNORECASE):
                continue
            if any(re.search(om, block, re.IGNORECASE) for om in other_models_re):
                continue

            for match in list(_ACCESS_SENTENCE_RE.finditer(block)):
                sentence = match.group(0)
                # Section 956: Markdown emphasis markers routinely sit between
                # the negation and the verb ("**ne peut pas** consulter"), which
                # a plain \s* separator does not cross. Match against an
                # emphasis-stripped copy; splice the ORIGINAL sentence text
                # (with its markers intact) so the replacement stays valid
                # Markdown and corrected.replace() still finds an exact match.
                sentence_plain = sentence.replace("**", "").replace("*", "")
                is_denied = bool(deny_re.search(sentence_plain))
                is_allowed = (not is_denied) and bool(allow_re.search(sentence_plain))
                verb_word = _ACCESS_VERB_WORDS[permission]
                if has_access and is_denied:
                    replacement = f"L'utilisateur PEUT {verb_word} `{model}` (voir le fait déterministe ci-dessous)."
                elif (not has_access) and is_allowed:
                    replacement = f"L'utilisateur NE PEUT PAS {verb_word} `{model}` (voir le fait déterministe ci-dessous)."
                else:
                    continue
                _access_logger.warning(
                    "Node [code_intelligence_agent]: synthesis asserted the opposite of "
                    "who_has_access_to's own '%s %s access to %s' verdict -- replacing sentence.",
                    verdict, permission, model,
                )
                corrected = corrected.replace(sentence, replacement, 1)

    return corrected
