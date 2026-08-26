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

    lines = [f"Évaluation des règles d'enregistrement (ir.rule) pour '{model_name}':"]
    if applied_global:
        lines.append("  - Règles Globales (ET pour tous): " + ", ".join([f"{r.rule_name} [{r.domain_force}]" for r in applied_global]))
    else:
        lines.append("  - Règles Globales: Aucune")

    if applied_group:
        lines.append("  - Règles de Groupe applicables (combinées en OU): " + ", ".join([f"{r.rule_name} [{r.domain_force}]" for r in applied_group]))
    else:
        lines.append("  - Règles de Groupe applicables: Aucune (l'utilisateur n'appartient à aucun des groupes visés)")

    if ignored_group:
        lines.append("  - Règles de Groupe ignorées (non-membre): " + ", ".join([f"{r.rule_name} [{r.domain_force}]" for r in ignored_group]))

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

    return RuleEvaluationResult(
        model_name=model_name,
        user_groups=user_groups,
        applied_global_rules=applied_global,
        applied_group_rules=applied_group,
        ignored_group_rules=ignored_group,
        effective_domain_summary=summary_text,
        summary_text=summary_text,
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

        for p in ["read", "write", "create", "unlink"]:
            grps, auth, rules = _eval_single_permission(G, model_name, p, group_id)
            all_allowed.update(grps)
            all_rules.extend(rules)
            if auth:
                all_auth = True
            
            grp_str = "All authenticated users" if auth else (", ".join(sorted(grps)) if grps else "None")
            rights_summary.append(f"[{p.upper()}]: {grp_str} (Rules: {len(rules)})")

        summary = f"Access Matrix for '{model_name}':\n" + "\n".join(rights_summary)

        return AccessEvaluationResult(
            model_name=model_name,
            requested_permission="all",
            allowed_groups=sorted(list(all_allowed)),
            all_authenticated_access=all_auth,
            active_rules=all_rules,
            summary_text=summary,
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
            summary = (
                f"Group '{display_id}' HAS {permission.upper()} access to '{model_name}'."
                if has_access
                else f"Group '{display_id}' DOES NOT HAVE {permission.upper()} access to '{model_name}'."
            )
    else:
        if all_authenticated:
            grp_str = "All authenticated users"
        elif allowed_groups:
            grp_str = ", ".join(sorted(allowed_groups))
        else:
            grp_str = "No groups explicitly granted"

        summary = f"Model '{model_name}' [{permission.upper()}]: Granted to {grp_str}. Active Rules: {len(active_rules)}."

    return AccessEvaluationResult(
        model_name=model_name,
        requested_permission=permission,
        allowed_groups=sorted(list(allowed_groups)),
        all_authenticated_access=all_authenticated,
        active_rules=active_rules,
        client_side_checks=[],
        summary_text=summary,
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


def button_execution_path(
    G: nx.DiGraph,
    button_label_or_name: str,
    model_name: str,
    user_groups: Optional[List[str]] = None,
) -> ButtonExecutionPathResult:
    """
    Traces step-by-step workflow execution path for a UI button click.
    Combines UI View Button -> Python Method -> Workflow State Transition -> Security Rules.
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

    # Search workflow transition edges
    for u, v, edge_data in G.edges(data=True):
        if edge_data.get("edge_type") == "TRANSITIONS_VIA":
            m_name = edge_data.get("method_name", "")
            btn_label = edge_data.get("label_bouton", "")

            # Match button by method name or label
            if (
                button_label_or_name.lower() in m_name.lower()
                or button_label_or_name.lower() in btn_label.lower()
                or m_name.lower() in button_label_or_name.lower()
            ):
                method_name = m_name
                orig_st = u.replace(f"state:{model_name}.", "").replace("state:", "")
                targ_st = v.replace(f"state:{model_name}.", "").replace("state:", "")

                origin_states.add(orig_st)
                target_state = targ_st

                groups_req = edge_data.get("groupe_requis", [])
                if isinstance(groups_req, list):
                    required_groups.update(groups_req)

    # If method_name not found via workflow edges, search direct method nodes
    if not method_name:
        method_name = button_label_or_name if button_label_or_name.startswith("action_") or button_label_or_name.startswith("_") else f"action_{button_label_or_name.lower()}"

    method_node_id = f"method:{model_name}.{method_name}"
    method_exists = method_node_id in G
    method_tags = tags_for_node_attrs(G.nodes[method_node_id]) if method_exists else []

    # Build execution steps
    execution_steps.append(f"1. UI Click: User clicks button '{button_label_or_name}' on form view of '{model_name}'.")
    execution_steps.append(f"2. Method Invocation: Calls Python method '{method_name}()' (Defined: {method_exists}).")

    if origin_states and target_state:
        orig_str = ", ".join(sorted(origin_states))
        execution_steps.append(f"3. State Transition: Transitions model '{model_name}' state from [{orig_str}] -> '{target_state}'.")
    else:
        execution_steps.append(f"3. State Transition: Executes method logic without state machine transition.")

    if required_groups:
        grp_str = ", ".join(sorted(required_groups))
        execution_steps.append(f"4. Security Requirement: Button restricted to groups [{grp_str}].")
    else:
        execution_steps.append(f"4. Security Requirement: No button-level group restriction specified.")

    summary = (
        f"Button '{button_label_or_name}' on '{model_name}': "
        f"Calls '{method_name}()'. "
        f"Transition: [{', '.join(sorted(origin_states))}] -> '{target_state}'. "
        f"Required Groups: [{', '.join(sorted(required_groups)) if required_groups else 'None'}]."
    )

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
            summary_text=f"Model '{model_name}' exists in the index but does not inherit from any other models."
        )

    ext_str = ", ".join(sorted(extension_parents)) if extension_parents else "None"
    del_str = ", ".join([f"{m} (via {fk})" for m, fk in delegation_parents.items()]) if delegation_parents else "None"

    summary = (
        f"Inheritance Chain for '{model_name}': "
        f"Extensions (_inherit): [{ext_str}]. "
        f"Delegations (_inherits): [{del_str}]. "
        f"Full Ancestor Chain: [{', '.join(full_ancestors)}]."
    )

    return InheritanceChainResult(
        model_name=model_name,
        status=QueryStatus.FOUND,
        extension_parents=sorted(list(extension_parents)),
        delegation_parents=delegation_parents,
        full_ancestors=full_ancestors,
        model_tags=model_tags,
        summary_text=summary,
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
            summary_text=f"Model '{model_name}' exists in the index but has no explicit workflow state transitions defined."
        )

    steps_text = []
    for idx, tr in enumerate(transitions, 1):
        grp_str = ", ".join(tr["required_groups"]) if tr["required_groups"] else "All Users"
        steps_text.append(
            f"Step {idx}: [{tr['origin_state']}] -> [{tr['target_state']}] "
            f"via Button '{tr['button_label']}' (Method: `{tr['method_name']}()`, Role: [{grp_str}])"
        )

    summary = f"Workflow Process for '{model_name}' ({len(transitions)} transitions):\n" + "\n".join(steps_text)

    return WorkflowProcessResult(
        model_name=model_name,
        status=QueryStatus.FOUND,
        states=sorted(list(states)),
        transitions=transitions,
        model_tags=model_tags,
        summary_text=summary,
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
