"""
code_intelligence/deterministic_tools.py

Specialized Deterministic Graph Query Tools for Odoo Code Intelligence.
Implements Epic B:
  - Story B1.1: qui_a_acces_a(model, droit, group_id=None)
  - Story B1.2: impact_changement_champ(field_name, model)
  - Story B1.3: chemin_execution_bouton(button_label_or_name, model)
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

_logger = logging.getLogger(__name__)

# Shared literal marker for "model/field not found in graph" messages.
# Used downstream by code_intelligence_agent() to bypass LLM synthesis
# for deterministic structural facts (never paraphrased, per plan rule
# against presenting LLM-derived text as a certain structural fact).
NOT_FOUND_MARKER = "was not found in the indexed knowledge graph"


# ---------------------------------------------------------------------------
# domain_force evaluator: safe AST parser + three-valued (Kleene) logic
# ---------------------------------------------------------------------------
#
# RuleEvaluationResult.can_view_amount() below only ever looks at the amount
# threshold via a regex on domain_force. That is not a domain evaluator, it
# is a single-field heuristic -- as soon as a domain_force mixes an amount
# condition with anything else (company_id, user_id, partner_id, state...),
# the regex-based check has no way to know whether those OTHER conditions
# also matter, and silently fails OPEN (returns True) whenever it can't
# find an amount pattern it recognizes. This is the confirmed root cause
# behind Bloc9 08c (todo/etat_reel.md): can_view_amount() fails open on a
# domain_force it cannot fully parse, which is exactly the kind of
# unhandled case rules.md Regle 5 says must never be silently folded into
# the happy path.
#
# This section adds an actual domain_force evaluator, used alongside (not
# yet replacing) can_view_amount():
#   1. _parse_domain_ast: parses the domain_force string with ast.parse in
#      'eval' mode and walks the resulting tree WITHOUT ever calling
#      eval()/exec() on it -- domain_force strings routinely contain
#      dynamic references (user.company_id.id) that are not valid Python
#      literals, so ast.literal_eval alone can't handle them, and a raw
#      eval() would execute arbitrary text pulled out of indexed source
#      code as code. Every AST node type is matched explicitly; anything
#      unrecognized raises _DomainParseError instead of being guessed at.
#   2. _normalize_domain_tokens: reproduces Odoo's own implicit-AND
#      normalization (leaves with no explicit leading operator are
#      implicitly AND-ed together).
#   3. _evaluate_domain_tokens: recursive prefix-notation evaluator using
#      Kleene three-valued logic (True / False / None="cannot conclude").
#      Unknown/unresolvable fields propagate as None instead of defaulting
#      to True (can_view_amount()'s current bug) or to False -- per
#      rules.md Regle 5, an unhandled case must be surfaced explicitly,
#      never silently guessed either way.
#
# evaluate_domain_force() is the public entry point: given a domain_force
# string and a context dict of known field values (plus an optional "user"
# sub-dict for dynamic user.* references, e.g.
# {"amount": 60000, "user": {"company_id": {"id": 3}}}), it returns
# (Optional[bool], List[str]) -- the tri-state verdict and the list of
# field names it could not resolve, so a caller can report exactly which
# condition is undetermined rather than pretending to a confidence it
# doesn't have.


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


def _evaluate_leaf(field_name: Any, op: str, value: Any, context: Dict[str, Any]) -> Optional[bool]:
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
    """
    if not isinstance(field_name, str):
        left = field_name
    elif field_name == "id" and op == "!=" and value is False:
        return True
    elif field_name not in context:
        return None
    else:
        left = context[field_name]

    if isinstance(value, _DynamicRef):
        right = _resolve_dynamic_ref(value, context)
        if right is None:
            return None
    else:
        right = _resolve_leaf_value(value, context)

    try:
        if op == "=":
            return left == right
        if op == "!=":
            return left != right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == "in":
            return left in right if right is not None else None
        if op == "not in":
            return left not in right if right is not None else None
    except TypeError:
        # Field present but not comparable to the resolved RHS (e.g. a
        # string compared with '>' to a number) -- cannot conclude, never
        # silently guess a side.
        return None

    # 'like'/'ilike': text-matching semantics deliberately not implemented
    # yet (no confirmed adversarial case needs them) -- cannot conclude
    # rather than pretend a substring match was checked.
    return None


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
    Consumes tokens left-to-right via a shared cursor (closure over a
    single-element list so nested recursive calls advance the same
    cursor) -- same traversal shape as Odoo's own domain evaluator.
    Appends to `unresolved` (in place) every leaf field name that could
    not be conclusively evaluated.
    """
    cursor = [0]

    def _consume() -> Optional[bool]:
        if cursor[0] >= len(tokens):
            raise _DomainParseError("domain_force ran out of tokens (malformed prefix notation)")
        token = tokens[cursor[0]]
        cursor[0] += 1

        if token == "&":
            left = _consume()
            right = _consume()
            return _kleene_and(left, right)
        if token == "|":
            left = _consume()
            right = _consume()
            return _kleene_or(left, right)
        if token == "!":
            operand = _consume()
            return _kleene_not(operand)

        leaf_field, op, value = token
        result = _evaluate_leaf(leaf_field, op, value, context)
        if result is None and isinstance(leaf_field, str) and leaf_field not in unresolved:
            unresolved.append(leaf_field)
        return result

    if not tokens:
        # Odoo semantics: an empty domain matches everything.
        return True

    verdict = _consume()
    if cursor[0] != len(tokens):
        raise _DomainParseError("domain_force has trailing unconsumed tokens (malformed)")
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
        it cannot be conclusively evaluated (unknown field, unresolved
        dynamic reference, unsupported operator, or a domain_force that
        fails to parse).
      - unresolved_fields lists every leaf field name that contributed to
        a None verdict, so a caller can report e.g. "company_id could not
        be determined" as an explicit caveat instead of silently
        defaulting to allow (can_view_amount()'s current bug, Bloc9 08c)
        or to deny.

    None is the deliberately safe default on ANY failure -- malformed
    domain_force, unsupported syntax, unresolvable reference -- per
    rules.md Regle 5 (no unhandled case may silently fall into a "happy
    path" outcome).
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
        Tri-state successor to can_view_amount(): evaluates the FULL
        domain_force of every applied rule (global AND group) via
        evaluate_domain_force() instead of a single-field amount regex.

        can_view_amount() only ever looks at an amount threshold and
        silently returns True whenever a domain_force mixes an amount
        condition with anything else (company_id, user_id, partner_id...)
        it doesn't recognize -- confirmed root cause of Bloc9 08c
        (todo/etat_reel.md): a global company-scoped rule was
        unconditionally treated as satisfied because the regex found no
        amount pattern to check, even though the real domain_force also
        restricted by company_id, which the caller's question explicitly
        said differed.

        context is the same kind of dict evaluate_domain_force() expects,
        e.g. {"amount": 60000, "company_id": 3,
        "user": {"company_id": {"id": 3}}} -- callers supply whatever
        fields they can determine; fields absent from context resolve to
        None ("cannot conclude"), never guessed.

        Returns (verdict, unresolved_fields):
          - verdict is True/False when every applied rule's domain_force
            fully resolves against context; None when at least one
            rule could not be conclusively evaluated -- per Kleene
            semantics, an unresolved leaf poisons an AND unless another
            leaf already forces False, and poisons an OR unless another
            leaf already forces True. Same three-valued combination
            evaluate_domain_force() already uses within a single domain,
            applied here one level up, across multiple rules.
          - unresolved_fields is the union of every leaf field name that
            contributed to a None verdict across all evaluated rules, so
            a caller can report e.g. "company_id could not be determined"
            explicitly instead of defaulting to allow.

        Deliberately does NOT replace can_view_amount() -- both coexist so
        existing callers relying on the bool-only signature are
        unaffected; callers that need the honest tri-state result (e.g. a
        rewritten evaluate_access() call site) opt in to this method
        explicitly.
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
        # evaluer_regles_enregistrement's group-membership check -- this
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
    evaluer_regles_enregistrement() and qui_a_acces_a() so an LLM tool call
    supplying an imprecise group name (short name, missing module prefix,
    or a bare business word like "regional" instead of any technical
    identifier) resolves consistently across every tool, not just the one
    that happened to be patched first.

    Real bug found via J4 benchmark analysis on Q6.1/Q6.2: the LLM's tool
    calls supplied plain words like "regional"/"national" or short names
    like "group_regional" instead of the fully-qualified group xml_id.
    Without this tolerant resolution, evaluer_regles_enregistrement and
    qui_a_acces_a silently disagreed with each other on the same question.

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


def evaluer_regles_enregistrement(
    G: nx.DiGraph,
    model_name: str,
    droit: str = "read",
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
    perm_attr = f"perm_{droit}" if droit in {"read", "write", "create", "unlink"} else "perm_read"

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
        Tolerant membership check between user-supplied group identifiers
        and a rule's group xml_ids.

        Tried in order, from most to least strict, per plan Bloc 1's rule
        against reimplementing Odoo's security engine by hand -- this only
        widens WHICH identifier counts as a match, it never touches the
        AND/OR combination algorithm itself:
          1. Exact match on the full xml_id (what Odoo itself uses).
          2. Short-name match (part after the last '.'), e.g. the LLM
             supplies "group_avoir_national" instead of the fully-qualified
             "custom_credit_note_visibility_rules.group_avoir_national".
          3. Fuzzy match against the group's human-readable display name
             (e.g. "Avoirs - Visibilite Nationale"), e.g. the LLM supplies
             a bare business word like "national" extracted straight from
             the user's question rather than any technical identifier.

        Real bug found via J4 benchmark analysis: the LLM populating
        user_groups_json in evaluer_regles_enregistrement's tool call
        supplied ["regional", "national"] verbatim from the question text
        for Q6.1/Q6.2 -- neither the xml_id nor its short name, just a
        paraphrase. Step 3 (fuzzy match against the group's display name)
        is what's needed to catch this specific case; steps 1-2 alone are
        insufficient. See test_group_membership_fuzzy_matches_display_name.
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
        # 2026-08-07 fix: include domain_force here too, same as the
        # applied-rules lines above -- omitting it silently hid the actual
        # scope/threshold (e.g. a 500000e regional cap) of a governance
        # rule the demandeur isn't a member of, even though the 2026-08-07
        # Bloc 7-bis revision (see authorization_gate.py / etat_reel.md)
        # explicitly decided this content is governance, not a bypass, and
        # must never be gated. Found via test_j23_24_authorization_gate.py::
        # test_ignored_group_rule_details_are_never_redacted actually being
        # run for the first time on 2026-08-07 (previously never executed
        # on this machine -- no execution access before that session).
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
    droit_demande: str
    allowed_groups: List[str] = field(default_factory=list)
    all_authenticated_access: bool = False
    active_rules: List[RuleDetail] = field(default_factory=list)
    client_side_checks: List[Dict[str, Any]] = field(default_factory=list)
    summary_text: str = ""


def _eval_single_droit(G: nx.DiGraph, model_name: str, droit: str, group_id: Optional[str] = None):
    model_node = f"model:{model_name}"
    perm_attr = f"perm_{droit}" if droit in {"read", "write", "create", "unlink"} else "perm_read"

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
                    )
                )

    return allowed_groups, all_authenticated, active_rules


def qui_a_acces_a(
    G: nx.DiGraph,
    model_name: str,
    droit: str = "read",
    group_id: Optional[str] = None
) -> AccessEvaluationResult:
    """
    Story B1.1: Evaluates access rights for a given model and permission type.
    Combines CSV ACLs, ir.rule domain_force expressions, res.groups implied hierarchy, and JS client checks.
    Supports droit='all' to evaluate all 4 permissions in a single pass.
    """
    model_node = f"model:{model_name}"

    if model_node not in G:
        return AccessEvaluationResult(
            model_name=model_name,
            droit_demande=droit,
            summary_text=f"Model '{model_name}' {NOT_FOUND_MARKER} (probable typo or missing model)."
        )

    if droit.lower() == "all":
        rights_summary = []
        all_allowed: Set[str] = set()
        all_rules: List[RuleDetail] = []
        all_auth = False

        for p in ["read", "write", "create", "unlink"]:
            grps, auth, rules = _eval_single_droit(G, model_name, p, group_id)
            all_allowed.update(grps)
            all_rules.extend(rules)
            if auth:
                all_auth = True
            
            grp_str = "All authenticated users" if auth else (", ".join(sorted(grps)) if grps else "None")
            rights_summary.append(f"[{p.upper()}]: {grp_str} (Rules: {len(rules)})")

        summary = f"Access Matrix for '{model_name}':\n" + "\n".join(rights_summary)

        return AccessEvaluationResult(
            model_name=model_name,
            droit_demande="all",
            allowed_groups=sorted(list(all_allowed)),
            all_authenticated_access=all_auth,
            active_rules=all_rules,
            summary_text=summary,
        )

    # Single permission evaluation
    allowed_groups, all_authenticated, active_rules = _eval_single_droit(G, model_name, droit, group_id)

    if group_id:
        resolved_group_id = resolve_group_identifier(G, group_id, list(allowed_groups)) if allowed_groups else None
        if resolved_group_id is None and not all_authenticated:
            # Distinguish "we could not identify this group at all" from
            # "this group was identified and does not have access" -- the
            # latter is a security decision, the former is an input
            # resolution failure and must never be silently reported as if
            # it were the former. Real bug found via J4 benchmark analysis:
            # qui_a_acces_a previously reported "DOES NOT HAVE access" for
            # imprecise group identifiers purely because of a strict
            # membership check, causing the LLM to synthesize a confidently
            # wrong final answer for Q6.1/Q6.2.
            summary = (
                f"Group identifier '{group_id}' could not be resolved against any group "
                f"with {droit.upper()} rules or ACLs on '{model_name}'. This does NOT mean "
                f"access is denied -- it means the identifier itself could not be matched. "
                f"Try lister_modules_impliques or resoudre_nom_technique to find the exact group xml_id."
            )
        else:
            has_access = all_authenticated or (resolved_group_id is not None)
            display_id = resolved_group_id or group_id
            summary = (
                f"Group '{display_id}' HAS {droit.upper()} access to '{model_name}'."
                if has_access
                else f"Group '{display_id}' DOES NOT HAVE {droit.upper()} access to '{model_name}'."
            )
    else:
        if all_authenticated:
            grp_str = "All authenticated users"
        elif allowed_groups:
            grp_str = ", ".join(sorted(allowed_groups))
        else:
            grp_str = "No groups explicitly granted"

        summary = f"Model '{model_name}' [{droit.upper()}]: Granted to {grp_str}. Active Rules: {len(active_rules)}."

    return AccessEvaluationResult(
        model_name=model_name,
        droit_demande=droit,
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


def impact_changement_champ(
    G: nx.DiGraph,
    field_name: str,
    model_name: str,
    max_depth: int = 10,
) -> FieldImpactResult:
    """
    Story B1.2: Analyzes upstream dependencies and downstream impact of modifying a field.
    Traces COMPUTED_BY, DEPENDS_ON, and RELATES_TO edges on the Knowledge Graph.

    Multi-hop BFS propagation (max_depth=10 by default): transitively discovers
    all downstream computed fields reachable through any chain of
    DEPENDS_ON / COMPUTED_BY edges, not just one hop.

    Reads the 'trigger_path' edge attribute on DEPENDS_ON edges to surface the
    full dotted @api.depends path (e.g. 'employee_id.department_id') in
    upstream_trigger_paths and summary_text.
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
    # "comment faire X" gating (Bloc 7 extension, 2026-08-07): whether the
    # REAL demandeur (never LLM-guessed, see rag/graph.py's
    # _override_user_groups_arg) can actually use this button, mirroring
    # what Odoo's own UI would already do (button invisible/greyed out for
    # a user outside required_groups). None when user_groups was not
    # supplied to chemin_execution_bouton() -- distinct from True/False,
    # since "unknown" must never be reported as "available".
    available_to_demandeur: Optional[bool] = None
    unavailable_reason: str = ""


def _demandeur_satisfies_required_groups(
    G: nx.DiGraph, required_groups: List[str], user_groups: List[str]
) -> bool:
    """
    True if the demandeur belongs to at least one of required_groups (Odoo
    button-level groups="..." is an OR condition across the listed groups,
    same semantics as an ACL's APPLIES_TO_GROUP set). No required_groups at
    all means the button carries no button-level restriction -- available
    to everyone, same convention as chemin_execution_bouton's own summary
    text ("No button-level group restriction specified").

    Reuses resolve_group_identifier (already used by qui_a_acces_a and
    evaluer_regles_enregistrement) so a required_groups entry supplied as a
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


def chemin_execution_bouton(
    G: nx.DiGraph,
    button_label_or_name: str,
    model_name: str,
    user_groups: Optional[List[str]] = None,
) -> ButtonExecutionPathResult:
    """
    Story B1.3: Traces step-by-step workflow execution path for a UI button click.
    Combines UI View Button -> Python Method -> Workflow State Transition -> Security Rules.

    user_groups (Bloc 7 extension, 2026-08-07): when supplied, also answers
    "comment faire X ?" honestly for the REAL demandeur -- if the button's
    required_groups don't include any group the demandeur belongs to, the
    action is reported as NOT available to them, mirroring what Odoo's own
    UI already enforces (invisible/greyed-out button), rather than walking
    them through a mechanism they cannot actually trigger. Optional and
    defaults to None (skip the check) so existing callers that don't pass
    it keep their prior behavior unchanged.
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

    available_to_demandeur: Optional[bool] = None
    unavailable_reason = ""
    if user_groups is not None:
        available_to_demandeur = _demandeur_satisfies_required_groups(G, sorted(required_groups), user_groups)
        if not available_to_demandeur:
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
        available_to_demandeur=available_to_demandeur,
        unavailable_reason=unavailable_reason,
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
    summary_text: str = ""


@dataclass
class WorkflowProcessResult:
    model_name: str
    status: QueryStatus = QueryStatus.NOT_FOUND
    states: List[str] = field(default_factory=list)
    transitions: List[Dict[str, Any]] = field(default_factory=list)
    summary_text: str = ""


def suivre_heritage_complet(
    G: nx.DiGraph,
    model_name: str
) -> InheritanceChainResult:
    """
    Story B.1.4: Traverses full inheritance chain distinguishing _inherit extension vs _inherits delegation.
    Handles 3-level error management (B.1.6).
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

    if not extension_parents and not delegation_parents:
        return InheritanceChainResult(
            model_name=model_name,
            status=QueryStatus.EMPTY,
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
        summary_text=summary,
    )


def quel_est_le_processus_de(
    G: nx.DiGraph,
    model_name: str
) -> WorkflowProcessResult:
    """
    Story B.1.5: Traverses WorkflowState -> TRANSITIONS_VIA -> WorkflowState edges.
    Handles 3-level error management (B.1.6).
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

    if not transitions:
        return WorkflowProcessResult(
            model_name=model_name,
            status=QueryStatus.EMPTY,
            states=sorted(list(states)),
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
