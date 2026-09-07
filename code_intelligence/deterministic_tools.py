"""
code_intelligence/deterministic_tools.py

Specialized Deterministic Graph Query Tools for Odoo Code Intelligence.
Provides tools for access evaluation, field impact analysis, button execution paths,
and ir.rule evaluation.
"""

from dataclasses import dataclass, field
from enum import Enum
from collections import deque
from typing import Dict, List, Optional, Set, Any, Tuple
import ast
import logging

import networkx as nx
import unicodedata
from rapidfuzz import fuzz

from code_intelligence.semantic_tag_query import tags_for_node_attrs
from code_intelligence.utils import format_file_link, format_xml_id_citation, format_xml_id_citations
from core.evidence import Evidence, EvidenceSourceType, make_evidence

_logger = logging.getLogger(__name__)

# Shared literal marker for "model/field not found in graph" messages.
# Used downstream by code_intelligence_agent() to bypass LLM synthesis
# for deterministic structural facts (never paraphrased, per plan rule
# against presenting LLM-derived text as a certain structural fact).
NOT_FOUND_MARKER = "was not found in the indexed knowledge graph"


# ---------------------------------------------------------------------------
# domain_force evaluator: safe AST parser + three-valued (Kleene) logic
# ---------------------------------------------------------------------------
# Evaluates domain_force expressions safely with Kleene 3-valued logic (True/False/None).
# Handles complex leaf expressions, prefix Polish notation, implicit AND, and dynamic refs.
# evaluate_domain_force() is the public entry point: returns (Optional[bool], List[str]).


_DOMAIN_COMPARISON_OPS = {"=", "!=", ">", ">=", "<", "<=", "in", "not in", "like", "ilike"}
_DOMAIN_LOGICAL_OPS = {"&", "|", "!"}


class _DomainParseError(Exception):
    """Raised internally when domain_force cannot be safely parsed or
    evaluated. Always caught at the evaluate_domain_force() boundary --
    callers never see a raw parser exception, only a tri-state None
    ("cannot conclude")."""


class _DynamicRef:
    """
    Marks an unevaluated dotted-attribute reference from domain_force, e.g.
    user.company_id.id -> _DynamicRef(['user', 'company_id', 'id']).
    Resolved later against the evaluation context's dict-based dotted-path
    lookup (see _resolve_dynamic_ref) -- never against a real object's
    __getattr__, so no live Odoo environment is required to evaluate a
    domain_force abstractly.
    """

    __slots__ = ("path",)

    def __init__(self, path: List[str]):
        self.path = path

    def __repr__(self):
        return ".".join(self.path)


def _domain_ast_op(node: ast.AST) -> str:
    """A leaf's comparison operator must be a plain string constant --
    anything else means this isn't a well-formed domain leaf."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    raise _DomainParseError(f"expected a string constant for operator, got {type(node).__name__}")


def _domain_ast_field(node: ast.AST):
    """
    The field-name position of a leaf. Normally a plain string (the field
    being tested against context), but Odoo also uses two literal-
    comparison idioms that are NOT field references at all:
      - TRUE_LEAF  (1, '=', 1)  -- always-true marker
      - FALSE_LEAF (0, '=', 1)  -- always-false marker
    For these the "field" position is a bare int/bool constant rather than
    a field name -- returned as-is (not coerced to str) so _evaluate_leaf
    can recognize and evaluate them as self-contained literal comparisons,
    never as a context field lookup. Real example confirmed on disk: the
    old can_view_amount() regex special-cased the string
    "[(1, '=', 1)]" as an unconditional-True marker; this generalizes that
    to the actual AST shape instead of a hardcoded string match.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, bool)):
        return node.value
    raise _DomainParseError(f"expected a string or literal constant for field, got {type(node).__name__}")


def _domain_ast_value(node: ast.AST):
    """
    The right-hand side of a leaf condition: a literal constant, a list of
    literals (for 'in'/'not in'), a negative numeric literal, or a
    dotted-attribute expression like user.company_id.id -- represented as
    a _DynamicRef and resolved later against the context dict, never
    evaluated as real Python attribute access.
    """
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_domain_ast_value(e) for e in node.elts]

    if isinstance(node, (ast.Attribute, ast.Name)):
        path: List[str] = []
        cur = node
        while isinstance(cur, ast.Attribute):
            path.insert(0, cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            path.insert(0, cur.id)
            return _DynamicRef(path)
        raise _DomainParseError("unsupported dotted-attribute base")

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _domain_ast_value(node.operand)
        if isinstance(inner, (int, float)):
            return -inner
        raise _DomainParseError("unary minus on non-numeric literal")

    raise _DomainParseError(f"unsupported value node type: {type(node).__name__}")


def _domain_ast_to_token(node: ast.AST):
    """
    Convert a single AST node from the parsed domain_force list into a
    Python-level token: a '&'/'|'/'!' string for a logical operator, or a
    3-tuple (field, op, value) for a leaf condition. Deliberately does NOT
    use eval()/exec() anywhere -- every node shape is matched explicitly,
    so no arbitrary expression coming from indexed source code is ever
    executed as code, only walked as inert data.
    """
    if isinstance(node, ast.Constant):
        val = node.value
        if isinstance(val, str) and val in _DOMAIN_LOGICAL_OPS:
            return val
        raise _DomainParseError(f"unexpected bare constant at domain top level: {val!r}")

    if isinstance(node, (ast.Tuple, ast.List)):
        elts = list(node.elts)
        if len(elts) != 3:
            raise _DomainParseError(f"leaf condition with {len(elts)} elements, expected 3")
        leaf_field = _domain_ast_field(elts[0])
        op = _domain_ast_op(elts[1])
        if op not in _DOMAIN_COMPARISON_OPS:
            raise _DomainParseError(f"unsupported comparison operator: {op!r}")
        value = _domain_ast_value(elts[2])
        return (leaf_field, op, value)

    raise _DomainParseError(f"unsupported domain element node type: {type(node).__name__}")


def _parse_domain_ast(domain_force: str) -> List[Any]:
    """
    Safely parse an Odoo domain_force string (e.g.
    "[('company_id', '=', user.company_id.id)]") into a flat list of
    tokens ('&'/'|'/'!' strings and leaf 3-tuples), using ast.parse in
    'eval' mode to build the tree WITHOUT ever calling eval()/exec() on the
    resulting code -- only ast.AST nodes are walked, never executed.
    Raises _DomainParseError on anything unsupported (malformed domain,
    unrecognized node types).
    """
    domain_force = (domain_force or "").strip()
    if not domain_force:
        return []

    try:
        tree = ast.parse(domain_force, mode="eval")
    except SyntaxError as exc:
        raise _DomainParseError(f"domain_force is not valid Python syntax: {exc}") from exc

    body = tree.body
    if not isinstance(body, (ast.List, ast.Tuple)):
        raise _DomainParseError("domain_force root is not a list/tuple")

    return [_domain_ast_to_token(elt) for elt in body.elts]


def _normalize_domain_tokens(tokens: List[Any]) -> List[Any]:
    """
    Reproduce Odoo's own domain normalization: a domain is prefix-notation
    logic, but consecutive leaves with no explicit leading operator are
    implicitly AND-ed together. A fully-formed prefix-notation domain needs
    (n_leaves - 1) binary operators ('!' is unary and doesn't count); any
    shortfall is filled by prepending that many '&' tokens at the front,
    mirroring Odoo's own normalize_domain().
    """
    if not tokens:
        return tokens

    n_leaves = sum(1 for t in tokens if isinstance(t, tuple))
    n_binary_ops = sum(1 for t in tokens if t in ("&", "|"))
    missing = (n_leaves - 1) - n_binary_ops
    if missing > 0:
        return ["&"] * missing + tokens
    return tokens


def _resolve_dynamic_ref(ref: "_DynamicRef", context: Dict[str, Any]) -> Any:
    """
    Resolve a dotted-attribute reference (e.g. user.company_id.id) against
    the context dict by walking nested dict lookups -- context['user'] is
    itself expected to be a plain dict (e.g. {'company_id': {'id': 3}}),
    never a real recordset, so this is dict traversal, not live attribute
    access. Returns None (unresolved) if any segment of the path is
    missing from context.
    """
    current: Any = context
    for segment in ref.path:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return None
    return current


def _resolve_leaf_value(value: Any, context: Dict[str, Any]) -> Any:
    if isinstance(value, _DynamicRef):
        return _resolve_dynamic_ref(value, context)
    if isinstance(value, list):
        return [_resolve_leaf_value(v, context) for v in value]
    return value


def _evaluate_leaf(field_name: Any, op: str, value: Any, context: Dict[str, Any]) -> Tuple[Optional[bool], List[str]]:
    """
    Evaluate a single leaf condition against context using Kleene
    three-valued logic: True/False when both sides resolve, None ("cannot
    conclude") when the field itself is absent from context, its
    right-hand side is a dynamic reference that doesn't resolve, or the
    two sides aren't comparable. An evaluator that cannot resolve a leaf
    must say so explicitly, per rules.md Regle 5, instead of guessing True
    or False.

    field_name is usually a field name (str) looked up in context, but two
    special cases are self-contained and never depend on context at all:
      - a non-str field_name (int/bool) is Odoo's TRUE_LEAF/FALSE_LEAF
        literal-comparison idiom (see _domain_ast_field's docstring) --
        evaluated directly against the literal, not a context lookup.
      - the leaf ('id', '!=', False) is Odoo's own "any real record has a
        truthy id" invariant -- unconditionally true by construction, not
        a context-dependent verdict (matches the marker the old regex-
        based can_view_amount() special-cased by exact string match).

    Returns (verdict, missing_names): missing_names lists every context
    key this leaf needed but couldn't get.
    """
    missing: List[str] = []

    if not isinstance(field_name, str):
        left = field_name
    elif field_name == "id" and op == "!=" and value is False:
        return True, []
    elif field_name not in context:
        left = None
        missing.append(field_name)
    else:
        left = context[field_name]

    if isinstance(value, _DynamicRef):
        right = _resolve_dynamic_ref(value, context)
        if right is None:
            ref_name = value.path[0]
            if ref_name not in missing:
                missing.append(ref_name)
    else:
        right = _resolve_leaf_value(value, context)

    if missing:
        return None, missing

    try:
        if op == "=":
            return left == right, []
        if op == "!=":
            return left != right, []
        if op == ">":
            return left > right, []
        if op == ">=":
            return left >= right, []
        if op == "<":
            return left < right, []
        if op == "<=":
            return left <= right, []
        if op == "in":
            if right is None:
                name = field_name if isinstance(field_name, str) else None
                return None, ([name] if name else [])
            return left in right, []
        if op == "not in":
            if right is None:
                name = field_name if isinstance(field_name, str) else None
                return None, ([name] if name else [])
            return left not in right, []
    except TypeError:
        name = field_name if isinstance(field_name, str) else None
        return None, ([name] if name else [])

    name = field_name if isinstance(field_name, str) else None
    return None, ([name] if name else [])


def _kleene_and(a: Optional[bool], b: Optional[bool]) -> Optional[bool]:
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def _kleene_or(a: Optional[bool], b: Optional[bool]) -> Optional[bool]:
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def _kleene_not(a: Optional[bool]) -> Optional[bool]:
    if a is None:
        return None
    return not a


def _evaluate_domain_tokens(
    tokens: List[Any], context: Dict[str, Any], unresolved: List[str]
) -> Optional[bool]:
    """
    Recursive evaluator for normalized prefix-notation domain tokens.
    Consumes tokens left-to-right via a shared cursor.
    Appends to `unresolved` (in place) every leaf field/reference name
    that genuinely contributed to the final None verdict.
    """
    cursor = [0]

    def _consume() -> Tuple[Optional[bool], List[str]]:
        if cursor[0] >= len(tokens):
            raise _DomainParseError("domain_force ran out of tokens (malformed prefix notation)")
        token = tokens[cursor[0]]
        cursor[0] += 1

        if token == "&":
            left_v, left_u = _consume()
            right_v, right_u = _consume()
            verdict = _kleene_and(left_v, right_v)
            if verdict is None:
                combined = list(left_u) if left_v is None else []
                for name in (right_u if right_v is None else []):
                    if name not in combined:
                        combined.append(name)
                return verdict, combined
            return verdict, []
        if token == "|":
            left_v, left_u = _consume()
            right_v, right_u = _consume()
            verdict = _kleene_or(left_v, right_v)
            if verdict is None:
                combined = list(left_u) if left_v is None else []
                for name in (right_u if right_v is None else []):
                    if name not in combined:
                        combined.append(name)
                return verdict, combined
            return verdict, []
        if token == "!":
            operand_v, operand_u = _consume()
            verdict = _kleene_not(operand_v)
            return verdict, (operand_u if verdict is None else [])

        leaf_field, op, value = token
        result, leaf_unresolved = _evaluate_leaf(leaf_field, op, value, context)
        return result, (leaf_unresolved if result is None else [])

    if not tokens:
        # Odoo semantics: an empty domain matches everything.
        return True

    verdict, final_unresolved = _consume()
    if cursor[0] != len(tokens):
        raise _DomainParseError("domain_force has trailing unconsumed tokens (malformed)")
    for name in final_unresolved:
        if name not in unresolved:
            unresolved.append(name)
    return verdict


def evaluate_domain_force(
    domain_force: str, context: Dict[str, Any]
) -> Tuple[Optional[bool], List[str]]:
    """
    Public entry point: safely evaluate an Odoo ir.rule domain_force string
    against a context dict of known field values (e.g. {'amount': 60000,
    'company_id': 3, 'user': {'company_id': {'id': 3}}}).

    Returns (verdict, unresolved_fields):
      - verdict is True/False when the domain fully resolves, or None when
        it cannot be conclusively evaluated.
      - unresolved_fields lists every leaf field name that contributed to
        a None verdict.
    """
    unresolved: List[str] = []
    try:
        tokens = _normalize_domain_tokens(_parse_domain_ast(domain_force))
        verdict = _evaluate_domain_tokens(tokens, context, unresolved)
    except _DomainParseError as exc:
        _logger.warning(
            "evaluate_domain_force: could not parse/evaluate domain_force %r: %s",
            domain_force, exc,
        )
        return None, unresolved

    return verdict, unresolved


@dataclass
class RuleDetail:
    rule_xml_id: str
    rule_name: str
    domain_force: str
    groups: List[str]
    # Bloc P2 Jour 4 (todo/plan.md, todo/contexte.txt section 172): the
    # Rule node's own behavioral_tags/technical_tags (graph_builder.py,
    # Bloc P2 Jour 2-3), copied through so who_has_access_to and
    # evaluate_record_rules callers can query e.g. "is this a
    # workflow_rule" without a second graph lookup. Always at least
    # ["visibility_rule", "record_rule"] for any Rule node (see
    # graph_builder.py), empty only for a caller that never went through
    # a real Rule node (e.g. a hand-built RuleDetail in a test).
    tags: List[str] = field(default_factory=list)


@dataclass
class RuleEvaluationResult:
    model_name: str
    user_groups: List[str]
    applied_global_rules: List[RuleDetail] = field(default_factory=list)
    applied_group_rules: List[RuleDetail] = field(default_factory=list)
    ignored_group_rules: List[RuleDetail] = field(default_factory=list)
    effective_domain_summary: str = ""
    summary_text: str = ""
    # B0 pilot (todo/contexte.txt sections 426-428): structured Evidence
    # produced at the source, one per rule actually evaluated (global,
    # applied group, or ignored group). Populated by evaluate_record_rules()
    # below. Not yet consumed downstream (B2/B3) -- exposed here so the
    # Evidence Builder has something real to wire into once it exists.
    evidence: List[Evidence] = field(default_factory=list)

    def can_view_amount(self, amount: float) -> bool:
        """
        Helper method to evaluate effective rules against a specific monetary threshold.
        """
        import re

        # Check global rules first (AND logic)
        for rule in self.applied_global_rules:
            m = re.search(r"<=['\"\s]*,['\"\s]*(-?\d+(?:\.\d+)?)", rule.domain_force)
            if m:
                limit = float(m.group(1))
                if amount > limit:
                    return False

        # If user has no applicable group rules, they are NOT restricted by group rules!
        if not self.applied_group_rules:
            return True

        # If user has applied group rules, they are combined with OR
        # If any applied group rule allows the amount, OR evaluates to True!
        for rule in self.applied_group_rules:
            dom = rule.domain_force
            if dom in ("[(1, '=', 1)]", "[(1,'=',1)]", "[('id', '!=', False)]"):
                return True
            m = re.search(r"<=['\"\s]*,['\"\s]*(-?\d+(?:\.\d+)?)", dom)
            if m:
                limit = float(m.group(1))
                if amount <= limit:
                    return True
            else:
                # Group rule with no numeric limit (e.g. unlimited or non-amount rule) allows access
                return True

        return False

    def can_view_amount_v2(self, context: Dict[str, Any]) -> Tuple[Optional[bool], List[str]]:
        """
        Evaluates the full domain_force of every applied rule (global AND group) via
        evaluate_domain_force() using Kleene three-valued logic.

        Returns (verdict, unresolved_fields):
          - verdict: True/False when conclusively resolved, None when uncertain.
          - unresolved_fields: list of field names that could not be determined.
        """
        unresolved: List[str] = []

        # Global rules: AND across ALL of them.
        global_verdict: Optional[bool] = True
        for rule in self.applied_global_rules:
            verdict, rule_unresolved = evaluate_domain_force(rule.domain_force, context)
            global_verdict = _kleene_and(global_verdict, verdict)
            for f in rule_unresolved:
                if f not in unresolved:
                    unresolved.append(f)

        # Group rules: OR across the group rules the user actually belongs
        # to (already filtered into applied_group_rules upstream by
        # evaluate_record_rules's group-membership check -- this
        # method never re-derives group membership itself). No applied
        # group rule at all means the user is NOT restricted by any group
        # rule, same convention as can_view_amount(): contributes True to
        # the final AND, not None.
        if not self.applied_group_rules:
            group_verdict: Optional[bool] = True
        else:
            group_verdict = False
            for rule in self.applied_group_rules:
                verdict, rule_unresolved = evaluate_domain_force(rule.domain_force, context)
                group_verdict = _kleene_or(group_verdict, verdict)
                for f in rule_unresolved:
                    if f not in unresolved:
                        unresolved.append(f)

        return _kleene_and(global_verdict, group_verdict), unresolved


FUZZY_GROUP_MATCH_THRESHOLD = 75


def _group_short_name(xml_id: str) -> str:
    """Part of a group xml_id after the last '.', used as a tolerant
    fallback when a full module-qualified id doesn't match exactly."""
    return xml_id.rsplit(".", 1)[-1]


def _group_display_name(G: nx.DiGraph, full_xml_id: str) -> str:
    """Human-readable name of a group node (e.g. 'Avoirs - Visibilite
    Regionale'), looked up from the graph. Empty string if not found."""
    node_id = f"group:{full_xml_id}"
    if node_id in G:
        return G.nodes[node_id].get("name", "")
    return ""


def _strip_group_prefix(s: str) -> str:
    """
    Strip the Odoo naming-convention prefix "group_" (e.g.
    "group_regional" -> "regional") before fuzzy-matching against a
    group's human-readable display name. Without this, the prefix
    dilutes the match score below threshold: "group_regional" vs
    "Avoirs - Visibilite Regionale" scores ~70 (just under the 75
    threshold) via partial_ratio, while "regional" alone (prefix
    stripped) scores much higher, since "group_" has no counterpart
    in the display name.
    """
    return s[len("group_"):] if s.lower().startswith("group_") else s


def _fold_accents(s: str) -> str:
    """
    Strip accents for accent-insensitive fuzzy matching. NFC normalization
    alone (used elsewhere for exact alias lookup) is NOT enough here: it
    only picks a canonical encoding for an accented character, it never
    removes the accent itself.
    """
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c))


def _group_fuzzy_matches_display_name(G: nx.DiGraph, user_group: str, rule_group_full_xml_id: str) -> bool:
    """
    Fuzzy-match a user-supplied group identifier against a specific group's
    human-readable display name (e.g. "Avoirs - Visibilite Nationale").
    """
    display_name = _group_display_name(G, rule_group_full_xml_id)
    if not display_name:
        return False
    folded_display_name = _fold_accents(display_name.lower())
    folded_user_group = _fold_accents(_strip_group_prefix(user_group).lower())
    score = max(
        fuzz.token_set_ratio(folded_user_group, folded_display_name),
        fuzz.partial_ratio(folded_user_group, folded_display_name),
    )
    return score >= FUZZY_GROUP_MATCH_THRESHOLD


def resolve_group_identifier(G: nx.DiGraph, user_group: str, candidate_full_xml_ids: List[str]) -> Optional[str]:
    """
    Shared tolerant group-identifier resolver, used by both
    evaluate_record_rules() and who_has_access_to() so an LLM tool call
    supplying an imprecise group name (short name, missing module prefix,
    or a bare business word like "regional" instead of any technical
    identifier) resolves consistently across every tool, not just the one
    that happened to be patched first.

    Real bug found via J4 benchmark analysis on Q6.1/Q6.2: the LLM's tool
    calls supplied plain words like "regional"/"national" or short names
    like "group_regional" instead of the fully-qualified group xml_id.
    Without this tolerant resolution, evaluate_record_rules and
    who_has_access_to silently disagreed with each other on the same question.

    Tried in order, from most to least strict -- this only widens WHICH
    identifier counts as a match, it never touches any access/security
    decision logic itself:
      1. Exact match on the full xml_id.
      2. Short-name match (part after the last '.').
      3. Fuzzy match against the group's human-readable display name.

    Returns the matching full_xml_id from candidate_full_xml_ids, or None
    if no candidate matches by any of the three methods -- callers MUST
    treat None as "group identifier could not be resolved", distinct from
    "group resolved but does not have access".
    """
    if user_group in candidate_full_xml_ids:
        return user_group

    short_user_group = _group_short_name(user_group)
    for candidate in candidate_full_xml_ids:
        if _group_short_name(candidate) == short_user_group:
            return candidate

    for candidate in candidate_full_xml_ids:
        if _group_fuzzy_matches_display_name(G, user_group, candidate):
            return candidate

    return None


def _build_record_rules_evidence(
    model_name: str,
    permission: str,
    user_groups: List[str],
    applied_global: List[RuleDetail],
    applied_group: List[RuleDetail],
    ignored_group: List[RuleDetail],
) -> List[Evidence]:
    """
    B0 pilot (todo/contexte.txt sections 426-428): generate one Evidence per
    rule actually evaluated, at the source, instead of leaving the caller to
    parse summary_text back into facts. Each rule's applied/ignored status
    depends on user_groups, so that context goes in scope rather than being
    baked into the claim string. confidence="HIGH" reflects that this is a
    deterministic graph read (static AST-derived domain_force/groups), not
    an LLM-interpreted heuristic -- same vocabulary CI already uses
    elsewhere (analyze_data_constraints's [Confiance: HIGH] tag).
    """
    scope = {"user_groups": sorted(user_groups)}
    evidence: List[Evidence] = []

    for rule in applied_global:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Global ir.rule '{rule.rule_name}' unconditionally restricts "
                f"{permission} access on '{model_name}' (AND-combined with every other rule)"
            ),
            source=f"rule:{rule.rule_xml_id}",
            value=rule.domain_force,
            confidence="HIGH",
            scope=scope,
        ))

    for rule in applied_group:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Group ir.rule '{rule.rule_name}' applies to the requester and "
                f"potentially restricts {permission} access on '{model_name}' "
                f"(OR-combined with other applied group rules)"
            ),
            source=f"rule:{rule.rule_xml_id}",
            value=rule.domain_force,
            confidence="HIGH",
            scope=scope,
        ))

    for rule in ignored_group:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Group ir.rule '{rule.rule_name}' exists on '{model_name}' but does NOT "
                f"apply to the requester (not a member of any of its groups: "
                f"{', '.join(rule.groups)})"
            ),
            source=f"rule:{rule.rule_xml_id}",
            value=rule.domain_force,
            confidence="HIGH",
            scope=scope,
        ))

    return evidence


def evaluate_record_rules(
    G: nx.DiGraph,
    model_name: str,
    permission: str = "read",
    user_groups: Optional[List[str]] = None
) -> RuleEvaluationResult:
    """
    Stories S2.1 & S2.2: Evaluates Odoo ir.rule record rules for a user, model, and permission type (read, write, create, unlink):
    - Global rules (no groups) are combined with AND across ALL users.
    - Group-specific rules are combined with OR across groups the user belongs to.
    - If user belongs to NO groups linked to a group rule, that group rule is IGNORED (does not restrict the user).
    """
    if user_groups is None:
        user_groups = []

    model_node = f"model:{model_name}"
    perm_attr = f"perm_{permission}" if permission in {"read", "write", "create", "unlink"} else "perm_read"

    if model_node not in G:
        return RuleEvaluationResult(
            model_name=model_name,
            user_groups=user_groups,
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER}."
        )

    # Find all rules attached to model that apply to requested permission
    all_rules: List[RuleDetail] = []
    for neighbor in G.neighbors(model_node):
        edge_data = G.get_edge_data(model_node, neighbor) or {}
        if edge_data.get("edge_type") == "RESTRICTED_BY" and G.nodes[neighbor].get("node_type") == "Rule":
            rule_node = G.nodes[neighbor]
            if not rule_node.get(perm_attr, True):
                continue

            rule_groups = []
            for r_neighbor in G.neighbors(neighbor):
                r_edge = G.get_edge_data(neighbor, r_neighbor) or {}
                if r_edge.get("edge_type") == "APPLIES_TO_GROUP":
                    grp_xml_id = r_neighbor.replace("group:", "")
                    rule_groups.append(grp_xml_id)

            all_rules.append(
                RuleDetail(
                    rule_xml_id=rule_node.get("xml_id", neighbor.replace("rule:", "")),
                    rule_name=rule_node.get("name", ""),
                    domain_force=rule_node.get("domain_force", ""),
                    groups=rule_groups,
                    tags=tags_for_node_attrs(rule_node),
                )
            )

    applied_global: List[RuleDetail] = []
    applied_group: List[RuleDetail] = []
    ignored_group: List[RuleDetail] = []

    user_group_set = set(user_groups)
    for g in list(user_group_set):
        _expand_implied_user_groups(G, g, user_group_set)

    def _user_belongs_to_rule_group(user_groups_set: set, rule_groups: List[str]) -> bool:
        """
        Tolerant membership check between user-supplied group identifiers and rule group xml_ids:
          1. Exact match on the full xml_id.
          2. Short-name match.
          3. Fuzzy match against the group's display name.
        """
        # Step 1: exact match
        if user_groups_set.intersection(rule_groups):
            return True

        # Step 2: short-name match
        short_rule_groups = {_group_short_name(g) for g in rule_groups}
        short_user_groups = {_group_short_name(g) for g in user_groups_set}
        if short_user_groups.intersection(short_rule_groups):
            return True

        # Step 3: fuzzy match against display name
        for rule_group in rule_groups:
            if resolve_group_identifier(G, next(iter(user_groups_set), ""), [rule_group]) or any(
                _group_fuzzy_matches_display_name(G, ug, rule_group) for ug in user_groups_set
            ):
                return True

        return False

    for rule in all_rules:
        if not rule.groups:
            applied_global.append(rule)
        else:
            if _user_belongs_to_rule_group(user_group_set, rule.groups):
                applied_group.append(rule)
            else:
                ignored_group.append(rule)

    # Bug 1 fix (todo/contexte.txt section 490, option A): each rule's own
    # rule_xml_id is exactly the kind of identifier CI_SYSTEM_PROMPT tells
    # the synthesis LLM to cite with an 'xml_id: ...' prefix -- emit that
    # ground truth token here so sourcing_guard.py can actually verify it.
    lines = [f"Évaluation des règles d'enregistrement (ir.rule) pour '{model_name}':"]
    if applied_global:
        lines.append("  - Règles Globales (ET pour tous): " + ", ".join([f"{r.rule_name} [{r.domain_force}] ({format_xml_id_citation(r.rule_xml_id)})" for r in applied_global]))
    else:
        lines.append("  - Règles Globales: Aucune")

    if applied_group:
        lines.append("  - Règles de Groupe applicables (combinées en OU): " + ", ".join([f"{r.rule_name} [{r.domain_force}] ({format_xml_id_citation(r.rule_xml_id)})" for r in applied_group]))
    else:
        lines.append("  - Règles de Groupe applicables: Aucune (l'utilisateur n'appartient à aucun des groupes visés)")

    if ignored_group:
        lines.append("  - Règles de Groupe ignorées (non-membre): " + ", ".join([f"{r.rule_name} [{r.domain_force}] ({format_xml_id_citation(r.rule_xml_id)})" for r in ignored_group]))

    if applied_group:
        lines.append(
            "  -> CONCLUSION: Au moins une regle de groupe applicable restreint potentiellement "
            "l'acces -- se referer aux domain_force ci-dessus pour les conditions exactes "
            "(combinees en OU entre elles, puis en ET avec les regles globales)."
        )
    else:
        lines.append(
            "  -> CONCLUSION: Aucune regle de groupe applicable (l'utilisateur n'appartient a aucun "
            "groupe cible par une regle sur ce modele). Seules les regles globales ci-dessus "
            "s'appliquent -- il n'y a AUCUNE restriction supplementaire de montant ou de portee "
            "provenant d'une regle de groupe pour cet utilisateur."
        )

    summary_text = "\n".join(lines)

    evidence = _build_record_rules_evidence(
        model_name, permission, user_groups, applied_global, applied_group, ignored_group
    )

    return RuleEvaluationResult(
        model_name=model_name,
        user_groups=user_groups,
        applied_global_rules=applied_global,
        applied_group_rules=applied_group,
        ignored_group_rules=ignored_group,
        effective_domain_summary=summary_text,
        summary_text=summary_text,
        evidence=evidence,
    )


@dataclass
class AccessEvaluationResult:
    model_name: str
    requested_permission: str
    allowed_groups: List[str] = field(default_factory=list)
    all_authenticated_access: bool = False
    active_rules: List[RuleDetail] = field(default_factory=list)
    client_side_checks: List[Dict[str, Any]] = field(default_factory=list)
    summary_text: str = ""
    # B1 replication of the B0 pilot (todo/contexte.txt sections 426-440):
    # structured Evidence produced at the source, one per ACL grant fact
    # and one per active ir.rule found for the permission(s) evaluated.
    # Populated by who_has_access_to() below.
    evidence: List[Evidence] = field(default_factory=list)


def _build_access_evidence(
    model_name: str,
    permission: str,
    allowed_groups: Set[str],
    all_authenticated: bool,
    active_rules: List[RuleDetail],
    group_id: Optional[str] = None,
) -> List[Evidence]:
    """
    B1 (todo/contexte.txt section 440): one Evidence for the ACL grant fact
    (who is granted `permission` at all), plus one Evidence per active
    ir.rule found for this model/permission (a rule that CAN further
    restrict access, regardless of any single requester's membership --
    who_has_access_to answers "who has access in general", not "does this
    requester have access", unlike evaluate_record_rules). scope carries
    group_id only when the caller narrowed the query to one group -- the
    ACL/rule facts themselves are not requester-specific.
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
        return set(), False, []

    allowed_groups: Set[str] = set()
    all_authenticated = False
    active_rules: List[RuleDetail] = []

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
                        _expand_inheriting_acl_groups(G, grp_xml_id, allowed_groups)

        elif edge_type == "RESTRICTED_BY" and G.nodes[neighbor].get("node_type") == "Rule":
            rule_node = G.nodes[neighbor]
            if rule_node.get(perm_attr, True):
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

    return allowed_groups, all_authenticated, active_rules


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
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER} (probable typo or missing model)."
        )

    if permission.lower() == "all":
        rights_summary = []
        all_allowed: Set[str] = set()
        all_rules: List[RuleDetail] = []
        all_auth = False
        all_evidence: List[Evidence] = []

        for p in ["read", "write", "create", "unlink"]:
            grps, auth, rules = _eval_single_permission(G, model_name, p, group_id)
            all_allowed.update(grps)
            all_rules.extend(rules)
            if auth:
                all_auth = True
            all_evidence.extend(_build_access_evidence(model_name, p, grps, auth, rules, group_id))
            
            grp_str = "All authenticated users" if auth else (", ".join(sorted(grps)) if grps else "None")
            # Bug 1 fix (todo/contexte.txt section 490, option A): emit
            # 'xml_id: ...' ground truth for each group xml_id named here.
            _grp_citations = format_xml_id_citations(sorted(grps)) if (grps and not auth) else ""
            _grp_suffix = f" ({_grp_citations})" if _grp_citations else ""
            rights_summary.append(f"[{p.upper()}]: {grp_str} (Rules: {len(rules)}){_grp_suffix}")

        summary = f"Access Matrix for '{model_name}':\n" + "\n".join(rights_summary)

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
    allowed_groups, all_authenticated, active_rules = _eval_single_permission(G, model_name, permission, group_id)

    if group_id:
        resolved_group_id = resolve_group_identifier(G, group_id, list(allowed_groups)) if allowed_groups else None
        if resolved_group_id is None and not all_authenticated:
            # Distinguish "we could not identify this group at all" from
            # "this group was identified and does not have access" -- the
            # latter is a security decision, the former is an input
            # resolution failure and must never be silently reported as if
            # it were the former. Real bug found via J4 benchmark analysis:
            # who_has_access_to previously reported "DOES NOT HAVE access" for
            # imprecise group identifiers purely because of a strict
            # membership check, causing the LLM to synthesize a confidently
            # wrong final answer for Q6.1/Q6.2.
            summary = (
                f"Group identifier '{group_id}' could not be resolved against any group "
                f"with {permission.upper()} rules or ACLs on '{model_name}'. This does NOT mean "
                f"access is denied -- it means the identifier itself could not be matched. "
                f"Try list_involved_modules or resolve_technical_name to find the exact group xml_id."
            )
        else:
            has_access = all_authenticated or (resolved_group_id is not None)
            display_id = resolved_group_id or group_id
            # Bug 1 fix (todo/contexte.txt section 490, option A): emit
            # 'xml_id: ...' ground truth for the resolved group xml_id.
            _display_citation = format_xml_id_citation(display_id)
            summary = (
                f"Group '{display_id}' HAS {permission.upper()} access to '{model_name}'. ({_display_citation})"
                if has_access
                else f"Group '{display_id}' DOES NOT HAVE {permission.upper()} access to '{model_name}'. ({_display_citation})"
            )
    else:
        if all_authenticated:
            grp_str = "All authenticated users"
        elif allowed_groups:
            grp_str = ", ".join(sorted(allowed_groups))
        else:
            grp_str = "No groups explicitly granted"

        # Bug 1 fix (todo/contexte.txt section 490, option A): emit
        # 'xml_id: ...' ground truth for each group xml_id named above.
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


@dataclass
class FieldImpactResult:
    field_name: str
    model_name: str
    upstream_triggers: List[str] = field(default_factory=list)
    upstream_trigger_paths: Dict[str, str] = field(default_factory=dict)
    downstream_computed_fields: List[str] = field(default_factory=list)
    propagation_depth: int = 0
    relational_target: Optional[str] = None
    compute_method: Optional[str] = None
    # Bloc P2 Jour 4 (todo/plan.md, todo/contexte.txt section 172): this
    # field's own behavioral_tags/technical_tags (graph_builder.py, Bloc
    # P2 Jour 2-3) -- e.g. ["calculation_rule", "computed_field"] for a
    # compute= field, [] for a plain stored field.
    field_tags: List[str] = field(default_factory=list)
    summary_text: str = ""
    # B1 replication of the B0 pilot (todo/contexte.txt sections 426-441):
    # structured Evidence produced at the source, one per upstream trigger
    # dependency and one per downstream computed field discovered by the
    # BFS. Populated by field_change_impact() below.
    evidence: List[Evidence] = field(default_factory=list)


# ---------- helpers for multi-hop BFS ----------

def _field_to_short_name(field_node_id: str) -> str:
    """'field:hr.expense.risk_score' -> 'risk_score'.
    Field node IDs have the format 'field:{model_name}.{field_name}' where
    model_name itself contains dots (e.g. 'hr.expense'), so the field name
    is always the last dot-segment.
    """
    # Strip 'field:' prefix if present
    raw = field_node_id.removeprefix("field:")
    # The field name is the last dot-segment
    return raw.rsplit(".", 1)[-1]


def _bfs_downstream(
    G: nx.DiGraph,
    start_field_node: str,
    max_depth: int = 10,
) -> Tuple[Set[str], int]:
    """
    Multi-hop BFS downstream propagation.
    From a field node, follows:
      in_edges DEPENDS_ON -> method node -> in_edges COMPUTED_BY -> computed field node
    then recurses from each discovered computed field.
    Returns (set_of_downstream_field_node_ids, max_depth_reached).
    """
    visited_fields: Set[str] = set()
    queue: deque = deque()  # (field_node_id, depth)
    queue.append((start_field_node, 0))
    visited_fields.add(start_field_node)
    max_depth_reached = 0

    while queue:
        current_field, depth = queue.popleft()
        if depth >= max_depth:
            continue

        # Find methods that DEPENDS_ON this field (in_edges of current_field)
        for in_node, _, in_edge_data in G.in_edges(current_field, data=True):
            if in_edge_data.get("edge_type") != "DEPENDS_ON":
                continue
            method_node = in_node
            # Find computed fields attached to this method (in_edges of method with COMPUTED_BY)
            for comp_node, _, comp_edge_data in G.in_edges(method_node, data=True):
                if comp_edge_data.get("edge_type") != "COMPUTED_BY":
                    continue
                if comp_node not in visited_fields:
                    visited_fields.add(comp_node)
                    next_depth = depth + 1
                    if next_depth > max_depth_reached:
                        max_depth_reached = next_depth
                    queue.append((comp_node, next_depth))

    # Remove the start node itself from results
    visited_fields.discard(start_field_node)
    return visited_fields, max_depth_reached


def _collect_upstream_triggers(
    G: nx.DiGraph,
    field_node: str,
) -> Tuple[Set[str], Dict[str, str]]:
    """
    Collect upstream trigger fields for a computed field.
    Returns (set_of_trigger_short_names, dict_of_trigger_short_name -> trigger_path).
    trigger_path is the full dotted dependency path stored on the DEPENDS_ON edge
    (e.g. 'employee_id.department_id'), or the short name itself if no dotted path.
    """
    upstream_triggers: Set[str] = set()
    trigger_paths: Dict[str, str] = {}

    for neighbor in G.neighbors(field_node):
        edge_data = G.get_edge_data(field_node, neighbor) or {}
        if edge_data.get("edge_type") != "COMPUTED_BY":
            continue
        method_node = neighbor
        for method_neighbor in G.neighbors(method_node):
            m_edge = G.get_edge_data(method_node, method_neighbor) or {}
            if m_edge.get("edge_type") != "DEPENDS_ON":
                continue
            trig_short = _field_to_short_name(method_neighbor)
            upstream_triggers.add(trig_short)
            # Read trigger_path edge attribute (full dotted path)
            trigger_path = m_edge.get("trigger_path")
            if trigger_path and trigger_path != trig_short:
                trigger_paths[trig_short] = trigger_path

    return upstream_triggers, trigger_paths


def _build_field_impact_evidence(
    model_name: str,
    field_name: str,
    upstream_triggers: Set[str],
    upstream_trigger_paths: Dict[str, str],
    downstream_field_nodes: Set[str],
) -> List[Evidence]:
    """
    B1 (todo/contexte.txt section 440+, tool 2/24): one Evidence per
    upstream trigger dependency (the fact that this computed field
    recomputes when a given trigger field changes) and one Evidence per
    downstream computed field discovered by the BFS (the fact that
    changing this field propagates to recompute that other field). Both
    are deterministic graph reads (DEPENDS_ON / COMPUTED_BY edges), so
    CODE / HIGH like the B0/B1 precedents. Unlike who_has_access_to there
    is no requester-specific context (no group_id equivalent), so scope
    stays empty for every fact here.
    """
    evidence: List[Evidence] = []

    for trig in sorted(upstream_triggers):
        trigger_path = upstream_trigger_paths.get(trig, trig)
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"'{model_name}.{field_name}' is recomputed when '{trigger_path}' changes",
            source=f"depends_on:{model_name}.{field_name}:{trig}",
            value=trigger_path,
            confidence="HIGH",
        ))

    for dn in sorted(downstream_field_nodes):
        short_name = _field_to_short_name(dn)
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Changing '{model_name}.{field_name}' triggers recomputation of '{short_name}'",
            source=dn,
            value=short_name,
            confidence="HIGH",
        ))

    return evidence


def field_change_impact(
    G: nx.DiGraph,
    field_name: str,
    model_name: str,
    max_depth: int = 10,
) -> FieldImpactResult:
    """
    Analyzes upstream dependencies and downstream impact of modifying a field.
    Traces COMPUTED_BY, DEPENDS_ON, and RELATES_TO edges on the Knowledge Graph.
    """
    field_node = f"field:{model_name}.{field_name}"

    if field_node not in G:
        return FieldImpactResult(
            field_name=field_name,
            model_name=model_name,
            summary_text=f"Field '{field_name}' on model '{model_name}' {NOT_FOUND_MARKER}."
        )

    f_data = G.nodes[field_node]
    compute_method = f_data.get("compute")
    relational_target = f_data.get("comodel_name")

    # 1. Upstream: field -> COMPUTED_BY -> method -> DEPENDS_ON -> trigger fields
    upstream_triggers, trigger_paths = _collect_upstream_triggers(G, field_node)

    # 2. Downstream: multi-hop BFS from this field through DEPENDS_ON / COMPUTED_BY chains
    downstream_field_nodes, depth_reached = _bfs_downstream(G, field_node, max_depth=max_depth)
    downstream_computed_fields: Set[str] = set()
    for dn in downstream_field_nodes:
        downstream_computed_fields.add(_field_to_short_name(dn))

    # Build summary
    downstream_str = ", ".join(sorted(downstream_computed_fields)) if downstream_computed_fields else "None"

    # Build upstream string with trigger_paths when available
    upstream_parts: List[str] = []
    for trig in sorted(upstream_triggers):
        if trig in trigger_paths:
            upstream_parts.append(f"{trig} (via {trigger_paths[trig]})")
        else:
            upstream_parts.append(trig)
    upstream_str = ", ".join(upstream_parts) if upstream_parts else "None"

    summary = (
        f"Field '{field_name}' on '{model_name}': "
        f"Triggers recomputation of [{downstream_str}]. "
        f"Depends on [{upstream_str}]."
    )

    return FieldImpactResult(
        field_name=field_name,
        model_name=model_name,
        upstream_triggers=sorted(list(upstream_triggers)),
        upstream_trigger_paths=trigger_paths,
        downstream_computed_fields=sorted(list(downstream_computed_fields)),
        propagation_depth=depth_reached,
        relational_target=relational_target,
        compute_method=compute_method,
        field_tags=tags_for_node_attrs(f_data),
        summary_text=summary,
        evidence=_build_field_impact_evidence(
            model_name, field_name, upstream_triggers, trigger_paths, downstream_field_nodes
        ),
    )


@dataclass
class ButtonExecutionPathResult:
    button_identifier: str
    model_name: str
    method_name: str = ""
    origin_states: List[str] = field(default_factory=list)
    target_state: str = ""
    required_groups: List[str] = field(default_factory=list)
    execution_steps: List[str] = field(default_factory=list)
    summary_text: str = ""
    # Whether the button is available to the requester
    available_to_requester: Optional[bool] = None
    unavailable_reason: str = ""
    # Bloc P2 Jour 4 (todo/plan.md, todo/contexte.txt section 172): the
    # called method's own behavioral_tags/technical_tags (graph_builder.py,
    # Bloc P2 Jour 2-3) -- e.g. ["blocking_rule"] when the method's source
    # contains both has_group() and a raise. Empty when the method node
    # was not found (method_exists=False) or carries no tag.
    method_tags: List[str] = field(default_factory=list)
    # B1 replication of the B0 pilot (todo/contexte.txt sections 426-444):
    # structured Evidence produced at the source -- method invocation,
    # state transition (or its absence), button-level security requirement
    # (or its absence), and requester availability when user_groups was
    # supplied. Populated by button_execution_path() below.
    evidence: List[Evidence] = field(default_factory=list)


def _requester_satisfies_required_groups(
    G: nx.DiGraph, required_groups: List[str], user_groups: List[str]
) -> bool:
    """
    True if the demandeur belongs to at least one of required_groups (Odoo
    button-level groups="..." is an OR condition across the listed groups,
    same semantics as an ACL's APPLIES_TO_GROUP set). No required_groups at
    all means the button carries no button-level restriction -- available
    to everyone, same convention as button_execution_path's own summary
    text ("No button-level group restriction specified").

    Reuses resolve_group_identifier (already used by who_has_access_to and
    evaluate_record_rules) so a required_groups entry supplied as a
    short name or a display-name fuzzy match resolves exactly the same way
    here as everywhere else in the module -- one tolerant resolver, not a
    fourth reimplementation of it.
    """
    if not required_groups:
        return True
    if not user_groups:
        return False

    user_group_set: Set[str] = set(user_groups)
    for g in list(user_group_set):
        _expand_implied_user_groups(G, g, user_group_set)

    return any(
        resolve_group_identifier(G, ug, required_groups) is not None
        for ug in user_group_set
    )


def _build_button_execution_evidence(
    button_label_or_name: str,
    model_name: str,
    method_name: str,
    method_exists: bool,
    origin_states: Set[str],
    target_state: str,
    required_groups: Set[str],
    user_groups: Optional[List[str]],
    available_to_requester: Optional[bool],
) -> List[Evidence]:
    """
    B1 (todo/contexte.txt section 440+, tool 3/24): four structural facts,
    each always asserted explicitly rather than silently omitted when
    negative (same convention as who_has_access_to's "No ACL explicitly
    grants..." branch) -- method invocation, state transition (or its
    absence), button-level security requirement (or its absence), and
    requester availability only when user_groups was actually supplied
    (that one carries scope, the other three are requester-agnostic
    structural facts).
    """
    evidence: List[Evidence] = []

    evidence.append(make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=(
            f"Button '{button_label_or_name}' on '{model_name}' calls method "
            f"'{method_name}()' (method_exists={method_exists})"
        ),
        source=f"method:{model_name}.{method_name}",
        value=method_name,
        confidence="HIGH",
    ))

    if origin_states and target_state:
        origins_str = ", ".join(sorted(origin_states))
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Button '{button_label_or_name}' transitions '{model_name}' "
                f"from [{origins_str}] to '{target_state}'"
            ),
            source=f"transition:{model_name}:{method_name}",
            value=target_state,
            confidence="HIGH",
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Button '{button_label_or_name}' on '{model_name}' triggers no workflow state transition",
            source=f"transition:{model_name}:{method_name}",
            value=None,
            confidence="HIGH",
        ))

    if required_groups:
        grp_str = ", ".join(sorted(required_groups))
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Button '{button_label_or_name}' on '{model_name}' is restricted to groups: {grp_str}",
            source=f"button_security:{model_name}:{method_name}",
            value=sorted(required_groups),
            confidence="HIGH",
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Button '{button_label_or_name}' on '{model_name}' carries no button-level group restriction",
            source=f"button_security:{model_name}:{method_name}",
            value=None,
            confidence="HIGH",
        ))

    if user_groups is not None:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Button '{button_label_or_name}' on '{model_name}' is "
                f"{'available' if available_to_requester else 'NOT available'} to this requester"
            ),
            source=f"button_availability:{model_name}:{method_name}",
            value=available_to_requester,
            confidence="HIGH",
            scope={"user_groups": sorted(user_groups)},
        ))

    return evidence


def _find_field_in_xml_views(
    G: nx.DiGraph,
    model_name: str,
    field_identifier: str,
    user_groups: Optional[List[str]] = None,
) -> Optional[ButtonExecutionPathResult]:
    """Search XML form views for field definitions matching field_identifier (name or label)
    and extract UI constraints (readonly, invisible, required, groups)."""
    import xml.etree.ElementTree as ET
    from pathlib import Path

    clean_id = field_identifier.strip().lower()
    matched_field_name = None
    matched_field_label = None

    model_node = f"model:{model_name}"
    if model_node in G:
        for _, v, d in G.out_edges(model_node, data=True):
            if d.get("edge_type") == "HAS_FIELD":
                fnode = G.nodes.get(v, {})
                fname = fnode.get("name", "")
                flabel = fnode.get("label", "")
                if clean_id in (fname.lower(), flabel.lower()):
                    matched_field_name = fname
                    matched_field_label = flabel or fname
                    break

    if not matched_field_name and model_node in G:
        import re
        FR_EN = {
            "nom": "name", "personnalise": "custom", "personnalisé": "custom",
            "section": "section", "facture": "invoice", "factures": "invoice",
            "vente": "sale", "commande": "order", "type": "type",
            "statut": "state", "etat": "state", "état": "state",
            "date": "date", "montant": "amount", "prix": "price",
            "societe": "company", "société": "company", "partenaire": "partner",
            "ligne": "line", "lignes": "line", "champ": "field",
        }
        words = set(re.findall(r"\w+", clean_id.lower()))
        en_words = {FR_EN.get(w, w) for w in words} | words
        candidates = []
        for _, v, d in G.out_edges(model_node, data=True):
            if d.get("edge_type") == "HAS_FIELD":
                fnode = G.nodes.get(v, {})
                fname = fnode.get("name", "")
                flabel = fnode.get("label", "")
                ftokens = set(re.findall(r"\w+", fname.lower())) | set(re.findall(r"\w+", flabel.lower()))
                score = len(en_words & ftokens)
                if score > 1:
                    candidates.append((score, fname, flabel))
        if candidates:
            candidates.sort(reverse=True, key=lambda c: c[0])
            matched_field_name = candidates[0][1]
            matched_field_label = candidates[0][2] or matched_field_name

    if not matched_field_name:
        if clean_id.replace("_", "").isalnum():
            matched_field_name = clean_id
            matched_field_label = field_identifier

    if not matched_field_name:
        return None

    candidate_dirs = set()
    for m_node, m_data in G.nodes(data=True):
        if m_data.get("node_type") == "Module":
            mfp = m_data.get("filepath")
            if mfp:
                vdir = Path(mfp).parent / "views"
                if vdir.exists():
                    candidate_dirs.add(vdir)

    view_matches = []
    for vdir in candidate_dirs:
        for xml_file in vdir.glob("*.xml"):
            try:
                content = xml_file.read_text(encoding="utf-8")
                if f'name="{matched_field_name}"' not in content and f"name='{matched_field_name}'" not in content:
                    continue
                root = ET.fromstring(content)
                for rec in root.findall(".//record"):
                    if rec.attrib.get("model") != "ir.ui.view":
                        continue
                    rec_id = rec.attrib.get("id", "")
                    parent_map = {c: p for p in rec.iter() for c in p}
                    for fld in rec.findall(f'.//field[@name="{matched_field_name}"]'):
                        attrs = dict(fld.attrib)
                        curr = fld
                        ancestor_with_constraints = None
                        while curr in parent_map:
                            curr = parent_map[curr]
                            for k in ("groups", "invisible", "readonly", "required"):
                                if k in curr.attrib and k not in attrs:
                                    attrs[k] = curr.attrib[k]
                                    if not ancestor_with_constraints:
                                        ancestor_with_constraints = curr
                        if "readonly" in attrs or "invisible" in attrs or "required" in attrs or "groups" in attrs:
                            lines = content.splitlines()
                            ln = 1
                            ancestor_name = ancestor_with_constraints.attrib.get("name", "") if ancestor_with_constraints is not None else ""
                            for idx, l in enumerate(lines, 1):
                                if ancestor_name and f'name="{ancestor_name}"' in l:
                                    ln = idx
                                    break
                                if f'name="{matched_field_name}"' in l or f"name='{matched_field_name}'" in l:
                                    ln = idx
                                    break
                            link = format_file_link(str(xml_file), ln, min(len(lines), ln + 6))
                            view_matches.append((rec_id, str(xml_file), ln, attrs, link))
            except Exception:
                continue

    if not view_matches:
        return None

    view_matches.sort(key=lambda x: (0 if ("/addons/" not in x[1] or "oca" in x[1]) else 1, x[0]))
    rec_id, xml_file, ln, attrs, link = view_matches[0]

    readonly_cond = attrs.get("readonly", "")
    invisible_cond = attrs.get("invisible", "")
    required_cond = attrs.get("required", "")
    groups_cond = attrs.get("groups", "")

    steps = [
        f"1. UI Field Declaration: Champ '{matched_field_name}' ({matched_field_label}) dans la vue '{rec_id}' (modèle '{model_name}').",
        f"2. Source XML: Déclaré dans {link}.",
    ]
    if readonly_cond:
        steps.append(f"3. Condition Readonly: readonly=\"{readonly_cond}\" -- le champ devient non modifiable sous cette condition.")
    if required_cond:
        steps.append(f"4. Condition Required: required=\"{required_cond}\".")
    if invisible_cond:
        steps.append(f"5. Condition Invisible: invisible=\"{invisible_cond}\".")
    if groups_cond:
        _grp_citations = format_xml_id_citations([g.strip() for g in groups_cond.split(",") if g.strip()])
        steps.append(f"6. Groupes requis: groups=\"{groups_cond}\" ({_grp_citations}).")

    summary_parts = [
        f"Champ '{matched_field_name}' ({matched_field_label}) sur la vue '{rec_id}' ({link}) du modèle '{model_name}':"
    ]
    if readonly_cond:
        summary_parts.append(f"Non modifiable (readonly) lorsque: readonly=\"{readonly_cond}\".")
    if required_cond:
        summary_parts.append(f"Requis lorsque: required=\"{required_cond}\".")
    if invisible_cond:
        summary_parts.append(f"Invisible lorsque: invisible=\"{invisible_cond}\".")
    if groups_cond:
        _grp_citations = format_xml_id_citations([g.strip() for g in groups_cond.split(",") if g.strip()])
        summary_parts.append(f"Restreint aux groupes: [{groups_cond}] ({_grp_citations}).")
    else:
        summary_parts.append("Aucune restriction par groupe sur ce champ.")

    req_groups_list = [g.strip() for g in groups_cond.split(",") if g.strip()] if groups_cond else []
    return ButtonExecutionPathResult(
        button_identifier=field_identifier,
        model_name=model_name,
        method_name="",
        origin_states=[],
        target_state="",
        required_groups=req_groups_list,
        execution_steps=steps,
        summary_text=" ".join(summary_parts),
        evidence=[],
    )


def button_execution_path(
    G: nx.DiGraph,
    button_label_or_name: str,
    model_name: str,
    user_groups: Optional[List[str]] = None,
) -> ButtonExecutionPathResult:
    """
    Traces step-by-step workflow execution path for a UI button click or UI field inspection.
    Combines UI View Button/Field -> Python Method -> Workflow State Transition -> Security Rules.
    """
    model_node = f"model:{model_name}"

    if model_node not in G:
        return ButtonExecutionPathResult(
            button_identifier=button_label_or_name,
            model_name=model_name,
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER}."
        )

    # Search for TRANSITIONS_VIA edges linked to this model
    method_name = ""
    origin_states: Set[str] = set()
    target_state = ""
    required_groups: Set[str] = set()
    execution_steps: List[str] = []

    # Search workflow transition edges with scored matching (exact match prioritizes over substring)
    candidate_transitions = []
    target_clean = button_label_or_name.strip().lower()
    for u, v, edge_data in G.edges(data=True):
        if edge_data.get("edge_type") == "TRANSITIONS_VIA":
            # If the state node has a model prefix, it must match model_name
            state_val = u.replace("state:", "")
            if "." in state_val:
                edge_model = state_val.rsplit(".", 1)[0]
                if edge_model != model_name:
                    continue

            m_name = (edge_data.get("method_name") or "").strip()
            btn_label = (edge_data.get("label_bouton") or "").strip()
            m_lower = m_name.lower()
            lbl_lower = btn_label.lower()

            score = 0
            if target_clean == m_lower or (lbl_lower and target_clean == lbl_lower):
                score = 3
            elif (lbl_lower and target_clean in lbl_lower) or (m_lower and target_clean in m_lower):
                score = 2
            elif (m_lower and m_lower in target_clean) or (lbl_lower and lbl_lower in target_clean):
                score = 1

            if score > 0:
                candidate_transitions.append((score, m_name, u, v, edge_data))

    if candidate_transitions:
        max_score = max(c[0] for c in candidate_transitions)
        best_candidates = [c for c in candidate_transitions if c[0] == max_score]
        chosen_method = best_candidates[0][1]
        for score, m_name, u, v, edge_data in best_candidates:
            if m_name == chosen_method:
                method_name = m_name
                orig_st = u.replace(f"state:{model_name}.", "").replace("state:", "")
                targ_st = v.replace(f"state:{model_name}.", "").replace("state:", "")
                origin_states.add(orig_st)
                target_state = targ_st
                groups_req = edge_data.get("groupe_requis", [])
                if isinstance(groups_req, list):
                    required_groups.update(groups_req)

    invisible_condition = ""
    # Search HAS_BUTTON edges linked to this model if not found via workflow edges
    if not method_name:
        model_node_id = f"model:{model_name}"
        if model_node_id in G:
            candidate_buttons = []
            for _, _, edge_data in G.out_edges(model_node_id, data=True):
                if edge_data.get("edge_type") == "HAS_BUTTON":
                    m_name = (edge_data.get("method_name") or "").strip()
                    btn_label = (edge_data.get("label_bouton") or "").strip()
                    m_lower = m_name.lower()
                    lbl_lower = btn_label.lower()
                    score = 0
                    if target_clean == m_lower or (lbl_lower and target_clean == lbl_lower):
                        score = 3
                    elif (lbl_lower and target_clean in lbl_lower) or (m_lower and target_clean in m_lower):
                        score = 2
                    elif (m_lower and m_lower in target_clean) or (lbl_lower and lbl_lower in target_clean):
                        score = 1
                    if score > 0:
                        candidate_buttons.append((score, m_name, edge_data))
            if candidate_buttons:
                candidate_buttons.sort(key=lambda x: x[0], reverse=True)
                _, method_name, edge_data = candidate_buttons[0]
                groups_req = edge_data.get("groupe_requis", [])
                if isinstance(groups_req, list):
                    required_groups.update(groups_req)
                invisible_condition = edge_data.get("invisible", "")

    # If neither transition nor button edge matched, check if identifier refers to a field in XML views
    if not method_name:
        field_view_res = _find_field_in_xml_views(G, model_name, button_label_or_name, user_groups=user_groups)
        if field_view_res is not None:
            return field_view_res

    # If method_name not found via workflow or button edges, search direct method nodes
    if not method_name:
        method_name = button_label_or_name if button_label_or_name.startswith("action_") or button_label_or_name.startswith("_") else f"action_{button_label_or_name.lower()}"

    method_node_id = f"method:{model_name}.{method_name}"
    method_exists = method_node_id in G
    method_tags = tags_for_node_attrs(G.nodes[method_node_id]) if method_exists else []

    # If not found via buttons/methods/transitions, check dynamic view hooks or Menu nodes
    if not method_exists and not origin_states and not invisible_condition:
        # Check if dynamic view injection (get_view / fields_view_get) overrides exist on this model
        get_view_id = f"method:{model_name}.get_view"
        fvg_id = f"method:{model_name}.fields_view_get"
        view_hook_id = get_view_id if get_view_id in G else (fvg_id if fvg_id in G else None)
        if view_hook_id:
            hook_data = G.nodes[view_hook_id]
            hook_name = hook_data.get("name", "get_view")
            hook_fp = hook_data.get("filepath", "")
            hook_line = hook_data.get("lineno", 0)
            hook_sites = hook_data.get("override_sites") or []
            end_line = hook_sites[0].get("end_lineno", hook_line + 48) if hook_sites else (hook_line + 48)
            hook_file_link = format_file_link(hook_fp, hook_line, end_line)
            dynamic_summary = (
                f"Button '{button_label_or_name}' on '{model_name}': No static XML button declaration found in views. "
                f"Dynamic View Injection Detected: Method '{model_name}.{hook_name}' is overridden at {hook_file_link}. "
                f"In Odoo, models overriding {hook_name}() dynamically inject buttons, labels, and widgets into the view arch "
                f"at runtime (via xpath on /form/header/button, QWeb rendering, or _tier_validation_manual_config) "
                f"without declaring them in static XML view files."
            )
            return ButtonExecutionPathResult(
                button_identifier=button_label_or_name,
                model_name=model_name,
                method_name=hook_name,
                origin_states=[],
                target_state="",
                required_groups=[],
                execution_steps=[
                    f"1. Dynamic View Injection: Method '{model_name}.{hook_name}()' dynamically processes form view XML.",
                    f"2. Source Hook: Defined at {hook_file_link}.",
                    f"3. Runtime XPath: Injects dynamic buttons into form header at runtime without static XML view declaration.",
                ],
                summary_text=dynamic_summary,
                evidence=[],
            )

        target_modules = set()
        model_node = f"model:{model_name}"
        if model_node in G:
            for neighbor in G.neighbors(model_node):
                edge_data = G.get_edge_data(model_node, neighbor) or {}
                if edge_data.get("edge_type") == "DEFINED_IN":
                    target_modules.add(neighbor.replace("module:", ""))
        if not target_modules:
            target_modules.add(model_name.split(".")[0])

        btn_clean = button_label_or_name.strip().lower()
        scored_menus = []
        for node_id, data in G.nodes(data=True):
            if data.get("node_type") == "Menu":
                m_name = (data.get("name") or "").strip()
                m_xml_id = (data.get("xml_id") or "").strip()
                m_mod = m_xml_id.split(".")[0] if "." in m_xml_id else ""
                name_match = (btn_clean == m_name.lower()) or (len(btn_clean) >= 3 and btn_clean in m_name.lower())
                id_match = (btn_clean == m_xml_id.lower()) or (len(btn_clean) >= 3 and btn_clean in m_xml_id.lower())
                if not (name_match or id_match):
                    continue
                score = 0
                if m_mod in target_modules:
                    score += 10
                if btn_clean == m_name.lower():
                    score += 5
                if btn_clean == m_xml_id.lower():
                    score += 3
                scored_menus.append((score, node_id, data))

        if scored_menus:
            scored_menus.sort(key=lambda x: x[0], reverse=True)
            _score, menu_id, menu_data = scored_menus[0]
            menu_name = menu_data.get("name", button_label_or_name)
            menu_xml_id = menu_data.get("xml_id", "")
            menu_fp = menu_data.get("filepath", "")
            menu_groups = menu_data.get("groups", [])
            grp_str = ", ".join(sorted(menu_groups)) if menu_groups else "None"
            req_citations = format_xml_id_citations(sorted(menu_groups)) if menu_groups else ""
            citations_str = f" ({req_citations})" if req_citations else ""

            menu_lineno = 1
            end_lineno = 10
            if menu_fp:
                from pathlib import Path
                p = Path(menu_fp)
                if p.exists():
                    try:
                        import re
                        m_txt = p.read_text(encoding="utf-8")
                        rec_id = menu_xml_id.split(".")[-1]
                        m_pos = re.search(r"id=[\"']" + re.escape(rec_id) + r"[\"']", m_txt)
                        if m_pos:
                            menu_lineno = m_txt[:m_pos.start()].count("\n") + 1
                            after = m_txt[m_pos.start():]
                            close_tag = after.find("</record>")
                            if close_tag != -1:
                                end_lineno = menu_lineno + after[:close_tag].count("\n")
                            else:
                                end_lineno = menu_lineno + 6
                    except Exception:
                        pass
            menu_link = f"[{Path(menu_fp).name}:L{menu_lineno}-L{end_lineno}](file://{menu_fp}#L{menu_lineno}-L{end_lineno})" if menu_fp else menu_fp

            menu_steps = [
                f"1. UI Menu: User navigates to menu item '{menu_name}' (id: {menu_xml_id}).",
                f"2. File Declaration: Declared in {menu_link}.",
                f"3. Security Requirement: Menu restricted to groups [{grp_str}].{citations_str}",
            ]
            menu_summary = (
                f"Menu '{menu_name}' (id: {menu_xml_id}) in {menu_link}: "
                f"Restricted to groups [{grp_str}].{citations_str} "
                f"Only users belonging to these groups have visibility to this menu item."
            )
            return ButtonExecutionPathResult(
                button_identifier=button_label_or_name,
                model_name=model_name,
                method_name="",
                origin_states=[],
                target_state="",
                required_groups=sorted(menu_groups),
                execution_steps=menu_steps,
                summary_text=menu_summary,
                evidence=[],
            )

    # Build execution steps
    if not method_exists and not origin_states and not invisible_condition:
        execution_steps.append(f"1. UI Search: Button or UI element '{button_label_or_name}' was not found in XML views for '{model_name}'.")
        execution_steps.append(f"2. Method Lookup: Candidate method '{method_name}()' is not defined on model '{model_name}'.")
        execution_steps.append("3. State Transition: None.")
        execution_steps.append("4. Security Requirement: None.")
        summary = (
            f"Button or UI element '{button_label_or_name}' on '{model_name}': "
            f"Neither button declaration nor method '{method_name}()' found in knowledge graph. "
            f"Transition: [] -> ''. "
            f"Required Groups: [None]."
        )
    else:
        method_link_str = f"Defined: {method_exists}"
        if method_exists and method_node_id in G:
            m_node = G.nodes[method_node_id]
            m_fp = m_node.get("filepath", "")
            m_line = m_node.get("lineno", 0)
            m_sites = m_node.get("override_sites") or []
            m_end = m_sites[0].get("end_lineno", m_line + 30) if m_sites else (m_line + 30)
            if m_fp:
                m_link = format_file_link(m_fp, m_line, m_end)
                method_link_str = f"Defined at {m_link}"
        execution_steps.append(f"1. UI Click: User clicks button '{button_label_or_name}' on form view of '{model_name}'.")
        execution_steps.append(f"2. Method Invocation: Calls Python method '{method_name}()' ({method_link_str}).")

        if origin_states and target_state:
            orig_str = ", ".join(sorted(origin_states))
            execution_steps.append(f"3. State Transition: Transitions model '{model_name}' state from [{orig_str}] -> '{target_state}'.")
        else:
            execution_steps.append(f"3. State Transition: Executes method logic without state machine transition.")

        if required_groups:
            grp_str = ", ".join(sorted(required_groups))
            # Bug 1 fix (todo/contexte.txt section 490, option A): emit
            # 'xml_id: ...' ground truth for each required-group xml_id.
            _req_citations = format_xml_id_citations(sorted(required_groups))
            execution_steps.append(f"4. Security Requirement: Button restricted to groups [{grp_str}]. ({_req_citations})")
        else:
            execution_steps.append(f"4. Security Requirement: No button-level group restriction specified.")

        if invisible_condition:
            execution_steps.append(f"5. Visibility Condition: Button invisible condition '{invisible_condition}'.")

        summary = (
            f"Button '{button_label_or_name}' on '{model_name}': "
            f"Calls '{method_name}()' ({method_link_str}). "
            f"Transition: [{', '.join(sorted(origin_states))}] -> '{target_state}'. "
            f"Required Groups: [{', '.join(sorted(required_groups)) if required_groups else 'None'}]."
        )
        if invisible_condition:
            summary += f" Visibility: invisible='{invisible_condition}'."

    available_to_requester: Optional[bool] = None
    unavailable_reason = ""
    if user_groups is not None:
        available_to_requester = _requester_satisfies_required_groups(G, sorted(required_groups), user_groups)
        if not available_to_requester:
            unavailable_reason = (
                f"Ce bouton est restreint aux groupes [{', '.join(sorted(required_groups))}], "
                "dont le demandeur ne fait partie d'aucun -- l'action n'est pas disponible "
                "pour lui dans l'interface (bouton absent ou grise), pas seulement documentee "
                "comme restreinte."
            )
            summary += f" NON DISPONIBLE POUR LE DEMANDEUR : {unavailable_reason}"
            execution_steps.append(
                f"5. Disponibilite reelle : NON -- {unavailable_reason}"
            )
        else:
            execution_steps.append(
                "5. Disponibilite reelle : OUI -- le demandeur appartient a un groupe requis "
                "(ou aucun groupe n'est requis)."
            )

    return ButtonExecutionPathResult(
        button_identifier=button_label_or_name,
        model_name=model_name,
        method_name=method_name,
        origin_states=sorted(list(origin_states)),
        target_state=target_state,
        required_groups=sorted(list(required_groups)),
        execution_steps=execution_steps,
        summary_text=summary,
        available_to_requester=available_to_requester,
        unavailable_reason=unavailable_reason,
        method_tags=method_tags,
        evidence=_build_button_execution_evidence(
            button_label_or_name, model_name, method_name, method_exists,
            origin_states, target_state, required_groups,
            user_groups, available_to_requester,
        ),
    )


class QueryStatus(Enum):
    FOUND = "found"
    EMPTY = "empty"
    NOT_FOUND = "not_found"


@dataclass
class InheritanceChainResult:
    model_name: str
    status: QueryStatus = QueryStatus.NOT_FOUND
    extension_parents: List[str] = field(default_factory=list)
    delegation_parents: Dict[str, str] = field(default_factory=dict)
    full_ancestors: List[str] = field(default_factory=list)
    # Bloc P2 Jour 4 (todo/plan.md, todo/contexte.txt section 172): the
    # queried model's own behavioral_tags/technical_tags (graph_builder.py,
    # Bloc P2 Jour 2-3) -- e.g. ["workflow_rule"] when the model has a
    # `state` field. Empty when the model was not found in the graph.
    model_tags: List[str] = field(default_factory=list)
    summary_text: str = ""
    # B1 replication of the B0 pilot (todo/contexte.txt sections 426-446):
    # structured Evidence produced at the source -- one per direct EXTENDS
    # (_inherit) parent and one per direct DELEGATES_TO (_inherits) parent,
    # or a single explicit "no inheritance" fact when neither is found.
    # Populated by trace_full_inheritance() below. Deliberately limited to
    # the model's DIRECT parents (the actual graph edges read), not the
    # full transitive ancestor closure -- same convention as
    # who_has_access_to's active_rules (one Evidence per edge actually
    # read, not per derived/aggregated fact).
    evidence: List[Evidence] = field(default_factory=list)


@dataclass
class WorkflowProcessResult:
    model_name: str
    status: QueryStatus = QueryStatus.NOT_FOUND
    states: List[str] = field(default_factory=list)
    transitions: List[Dict[str, Any]] = field(default_factory=list)
    # Bloc P2 Jour 4 (todo/plan.md, todo/contexte.txt section 172): the
    # queried model's own behavioral_tags/technical_tags (graph_builder.py,
    # Bloc P2 Jour 2-3) -- e.g. ["workflow_rule"] when the model has a
    # `state` field. Empty when the model was not found in the graph.
    model_tags: List[str] = field(default_factory=list)
    summary_text: str = ""
    # B1 replication of the B0 pilot (todo/contexte.txt sections 426-447):
    # structured Evidence produced at the source -- one per TRANSITIONS_VIA
    # edge found (the full step: origin state, target state, button,
    # method, required groups), or a single explicit "no transitions"
    # fact when the model has no workflow state machine at all. Populated
    # by describe_workflow() below.
    evidence: List[Evidence] = field(default_factory=list)


def _build_workflow_evidence(
    model_name: str,
    transitions: List[Dict[str, Any]],
) -> List[Evidence]:
    """
    B1 (todo/contexte.txt section 440+, tool 5/24, last composite CI): one
    Evidence per TRANSITIONS_VIA edge actually found -- each transition is
    a single structural fact bundling origin state, target state, the
    button/method that fires it, and any button-level group restriction
    (already the unit describe_workflow's own summary_text steps_text
    walks one-by-one), or a single explicit "no transitions" fact when the
    model carries no workflow state machine at all -- same always-assert-
    explicitly convention as who_has_access_to/button_execution_path/
    trace_full_inheritance. No requester context here (describe_workflow
    takes no user_groups param, unlike button_execution_path), so scope
    stays empty for every fact.
    """
    evidence: List[Evidence] = []

    for tr in transitions:
        origin = tr.get("origin_state", "")
        target = tr.get("target_state", "")
        method = tr.get("method_name", "")
        button = tr.get("button_label", "")
        req_groups = tr.get("required_groups", [])

        claim = (
            f"Model '{model_name}' transitions from '{origin}' to '{target}' "
            f"via button '{button}' (calls '{method}()')"
        )
        if req_groups:
            claim += f", restricted to groups: {', '.join(req_groups)}"

        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=claim,
            source=f"transition:{model_name}:{method}:{origin}:{target}",
            value=target,
            confidence="HIGH",
        ))

    if not transitions:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Model '{model_name}' has no explicit workflow state transitions defined",
            source=f"workflow:{model_name}",
            value=None,
            confidence="HIGH",
        ))

    return evidence


def _build_inheritance_evidence(
    model_name: str,
    extension_parents: Set[str],
    delegation_parents: Dict[str, str],
) -> List[Evidence]:
    """
    B1 (todo/contexte.txt section 440+, tool 4/24): one Evidence per direct
    EXTENDS (_inherit) parent and one per direct DELEGATES_TO (_inherits)
    parent, or a single explicit "no inheritance" fact when neither is
    found -- same always-assert-explicitly convention as who_has_access_to
    and button_execution_path (never silently omit a negative fact).
    Deliberately limited to the model's DIRECT parents (the actual EXTENDS/
    DELEGATES_TO edges read from the model's own node), not the full
    transitive full_ancestors BFS closure -- one Evidence per edge actually
    read, not per derived/aggregated fact, matching who_has_access_to's
    active_rules convention. No requester context here (no group_id/
    user_groups equivalent), so scope stays empty for every fact.
    """
    evidence: List[Evidence] = []

    for parent in sorted(extension_parents):
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Model '{model_name}' extends '{parent}' via _inherit",
            source=f"extends:{model_name}:{parent}",
            value=parent,
            confidence="HIGH",
        ))

    for parent, fk_field in sorted(delegation_parents.items()):
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Model '{model_name}' delegates to '{parent}' via _inherits "
                f"(foreign key '{fk_field}')"
            ),
            source=f"delegates_to:{model_name}:{parent}",
            value=fk_field,
            confidence="HIGH",
        ))

    if not extension_parents and not delegation_parents:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"Model '{model_name}' does not inherit from any other model (no _inherit or _inherits)",
            source=f"inherits:{model_name}",
            value=None,
            confidence="HIGH",
        ))

    return evidence


def trace_full_inheritance(
    G: nx.DiGraph,
    model_name: str
) -> InheritanceChainResult:
    """
    Traverses full inheritance chain distinguishing _inherit extension vs _inherits delegation.
    """
    model_node = f"model:{model_name}"

    if model_node not in G:
        return InheritanceChainResult(
            model_name=model_name,
            status=QueryStatus.NOT_FOUND,
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER} (probable typo or missing model)."
        )

    extension_parents: Set[str] = set()
    delegation_parents: Dict[str, str] = {}
    full_ancestors: List[str] = []

    # BFS traversal for full ancestors
    visited: Set[str] = {model_name}
    queue: List[str] = [model_name]

    while queue:
        curr = queue.pop(0)
        curr_node = f"model:{curr}"

        if curr_node in G:
            for neighbor in G.neighbors(curr_node):
                edge_data = G.get_edge_data(curr_node, neighbor) or {}
                edge_type = edge_data.get("edge_type")

                if edge_type == "EXTENDS":
                    parent_m = neighbor.replace("model:", "")
                    if curr == model_name:
                        extension_parents.add(parent_m)
                    if parent_m not in visited:
                        visited.add(parent_m)
                        queue.append(parent_m)
                        full_ancestors.append(parent_m)

                elif edge_type == "DELEGATES_TO":
                    parent_m = neighbor.replace("model:", "")
                    fk_field = edge_data.get("fk_field", "")
                    if curr == model_name:
                        delegation_parents[parent_m] = fk_field
                    if parent_m not in visited:
                        visited.add(parent_m)
                        queue.append(parent_m)
                        full_ancestors.append(parent_m)

    model_tags = tags_for_node_attrs(G.nodes[model_node])

    if not extension_parents and not delegation_parents:
        return InheritanceChainResult(
            model_name=model_name,
            status=QueryStatus.EMPTY,
            model_tags=model_tags,
            summary_text=f"Model '{model_name}' exists in the index but does not inherit from any other models.",
            evidence=_build_inheritance_evidence(model_name, extension_parents, delegation_parents),
        )

    ext_str = ", ".join(sorted(extension_parents)) if extension_parents else "None"
    del_str = ", ".join([f"{m} (via {fk})" for m, fk in delegation_parents.items()]) if delegation_parents else "None"

    mixins = [p for p in extension_parents if p.endswith(".mixin") or p in ("mail.thread", "mail.activity.mixin", "rating.mixin", "portal.mixin", "utm.mixin", "image.mixin", "avatar.mixin")]
    business_parents = [p for p in extension_parents if p not in mixins]
    nature_str = ""
    if extension_parents:
        if not business_parents:
            nature_str = f" Nature: Nouveau modèle déclarant son propre _name='{model_name}' avec mixins techniques uniquement ({', '.join(sorted(mixins))}), pas d'extension d'un modèle métier existant."
        else:
            nature_str = f" Nature: Extension de modèle(s) métier ({', '.join(sorted(business_parents))})."

    summary = (
        f"Inheritance Chain for '{model_name}': "
        f"Extensions (_inherit): [{ext_str}]. "
        f"Delegations (_inherits): [{del_str}]. "
        f"Full Ancestor Chain: [{', '.join(full_ancestors)}].{nature_str}"
    )

    filepaths = G.nodes[model_node].get("filepaths", [])
    if filepaths:
        from pathlib import Path
        from code_intelligence.ci_agent_tools import _is_custom_module_filepath
        sorted_filepaths = sorted(filepaths, key=lambda f: not _is_custom_module_filepath(f))
        src_links = []
        for fp in sorted_filepaths:
            p = Path(fp)
            lineno = 1
            line_count = 50
            if p.exists():
                try:
                    text = p.read_text(encoding="utf-8")
                    line_count = max(1, len(text.splitlines()))
                    pos = re.search(r"(?:_name|_inherit)\s*=\s*['\"]" + re.escape(model_name) + r"['\"]", text)
                    if pos:
                        before = text[:pos.start()]
                        class_matches = list(re.finditer(r"class\s+\w+", before))
                        if class_matches:
                            class_pos = class_matches[-1].start()
                            lineno = text[:class_pos].count("\n") + 1
                except Exception:
                    pass
            end_line = min(lineno + 80, line_count)
            src_links.append(f"[{p.name}:L{lineno}-L{end_line}](file://{fp}#L{lineno}-L{end_line})")
        summary += f" Declared in: {', '.join(src_links)}."

    return InheritanceChainResult(
        model_name=model_name,
        status=QueryStatus.FOUND,
        extension_parents=sorted(list(extension_parents)),
        delegation_parents=delegation_parents,
        full_ancestors=full_ancestors,
        model_tags=model_tags,
        summary_text=summary,
        evidence=_build_inheritance_evidence(model_name, extension_parents, delegation_parents),
    )


def describe_workflow(
    G: nx.DiGraph,
    model_name: str
) -> WorkflowProcessResult:
    """
    Traverses WorkflowState -> TRANSITIONS_VIA -> WorkflowState edges.
    """
    model_node = f"model:{model_name}"

    if model_node not in G:
        return WorkflowProcessResult(
            model_name=model_name,
            status=QueryStatus.NOT_FOUND,
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER} (probable typo or missing model)."
        )

    states: Set[str] = set()
    transitions: List[Dict[str, Any]] = []

    # Find workflow state nodes for this model
    for n, data in G.nodes(data=True):
        if data.get("node_type") == "WorkflowState" and data.get("model") == model_name:
            states.add(data.get("state_value", ""))

    # Find TRANSITIONS_VIA edges
    for u, v, edge_data in G.edges(data=True):
        if edge_data.get("edge_type") == "TRANSITIONS_VIA":
            orig_st = u.replace(f"state:{model_name}.", "").replace("state:", "")
            targ_st = v.replace(f"state:{model_name}.", "").replace("state:", "")

            if u.startswith(f"state:{model_name}") or v.startswith(f"state:{model_name}"):
                transitions.append({
                    "origin_state": orig_st,
                    "target_state": targ_st,
                    "method_name": edge_data.get("method_name", ""),
                    "button_label": edge_data.get("label_bouton", ""),
                    "required_groups": edge_data.get("groupe_requis", []),
                })

    model_tags = tags_for_node_attrs(G.nodes[model_node])

    if not transitions:
        return WorkflowProcessResult(
            model_name=model_name,
            status=QueryStatus.EMPTY,
            states=sorted(list(states)),
            model_tags=model_tags,
            summary_text=f"Model '{model_name}' exists in the index but has no explicit workflow state transitions defined.",
            evidence=_build_workflow_evidence(model_name, transitions),
        )

    steps_text = []
    for idx, tr in enumerate(transitions, 1):
        grp_str = ", ".join(tr["required_groups"]) if tr["required_groups"] else "All Users"
        # Bug 1 fix (todo/contexte.txt section 490, option A): emit
        # 'xml_id: ...' ground truth for each required-group xml_id.
        _tr_citations = format_xml_id_citations(tr["required_groups"]) if tr["required_groups"] else ""
        _tr_suffix = f" ({_tr_citations})" if _tr_citations else ""
        steps_text.append(
            f"Step {idx}: [{tr['origin_state']}] -> [{tr['target_state']}] "
            f"via Button '{tr['button_label']}' (Method: `{tr['method_name']}()`, Role: [{grp_str}]){_tr_suffix}"
        )

    summary = f"Workflow Process for '{model_name}' ({len(transitions)} transitions):\n" + "\n".join(steps_text)

    return WorkflowProcessResult(
        model_name=model_name,
        status=QueryStatus.FOUND,
        states=sorted(list(states)),
        transitions=transitions,
        model_tags=model_tags,
        summary_text=summary,
        evidence=_build_workflow_evidence(model_name, transitions),
    )


def _expand_implied_user_groups(G: nx.DiGraph, user_group: str, user_group_set: Set[str]):
    """
    Recursively add every broader group implied BY user_group (Odoo implied_ids
    semantics: membership in user_group automatically grants membership in
    every group it implies, transitively).

    Edge convention in graph_builder.py:
        specific_group --IMPLIES--> broader_group
    So the broader groups a user inherits are reached by walking OUTGOING
    IMPLIES edges from user_group.
    """
    group_node = f"group:{user_group}"
    if group_node not in G:
        return

    for _, broader_node, edge_data in G.out_edges(group_node, data=True):
        if edge_data.get("edge_type") == "IMPLIES":
            broader_group_id = broader_node.replace("group:", "")
            if broader_group_id not in user_group_set:
                user_group_set.add(broader_group_id)
                _expand_implied_user_groups(G, broader_group_id, user_group_set)


def _expand_inheriting_acl_groups(G: nx.DiGraph, acl_group: str, allowed_groups: Set[str]):
    """
    Recursively add every higher-privilege group that IMPLIES acl_group.

    Edge convention in graph_builder.py:
        higher_group --IMPLIES--> acl_group
    When an ACL grants permission to acl_group, any higher_group that implies
    acl_group automatically inherits that ACL permission. Reached by walking
    INCOMING IMPLIES edges to acl_group.
    """
    group_node = f"group:{acl_group}"
    if group_node not in G:
        return

    for higher_node, _, edge_data in G.in_edges(group_node, data=True):
        if edge_data.get("edge_type") == "IMPLIES":
            higher_group_id = higher_node.replace("group:", "")
            if higher_group_id not in allowed_groups:
                allowed_groups.add(higher_group_id)
                _expand_inheriting_acl_groups(G, higher_group_id, allowed_groups)
