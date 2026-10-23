"""
Safe AST parser, normalizer, and evaluator for Odoo ir.rule domain_force expressions.
Converts Python domain expressions into prefix-notation token streams and evaluates
them safely using Kleene three-valued logic (True / False / None) without executing arbitrary code.
"""

import ast
import logging
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)

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


def _resolve_dynamic_ref(ref: _DynamicRef, context: Dict[str, Any]) -> Any:
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
