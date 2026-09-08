"""
code_intelligence/deterministic/domain_evaluator.py

Safe evaluator for Odoo ir.rule domain_force expressions using Kleene
three-valued logic (True / False / None).
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from code_intelligence.deterministic.domain_parser import (
    _DomainParseError,
    _DynamicRef,
    _normalize_domain_tokens,
    _parse_domain_ast,
)

_logger = logging.getLogger(__name__)


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
