"""
code_intelligence/deterministic/domain_parser.py

Safe AST parser and normalizer for Odoo ir.rule domain_force expressions.
Converts Python domain expressions into prefix-notation token streams
without ever executing arbitrary code.
"""

import ast
from typing import Any, List

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
