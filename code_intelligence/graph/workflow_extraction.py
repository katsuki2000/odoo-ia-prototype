"""Workflow states and transitions derived from the parsed code, never from constants."""

from __future__ import annotations

import ast
import re
from typing import Iterable, List, Optional, Sequence, Set


MAX_CALL_DEPTH = 3


def state_predicate(field_name: str):
    return re.compile(rf"^{re.escape(field_name)}\s+(==|!=|not\s+in|in)\s+(.+)$")


def selection_values(decls: Iterable, field_name: str) -> Optional[List[str]]:
    values: List[str] = []
    for decl in decls:
        for field in decl.fields:
            if field.name == field_name:
                values.extend(value for value in (field.selection or []) + (field.selection_add or []) if value not in values)
    return values or None


def returned_states(decls: Sequence, method_name: str, field_name: str) -> List[str]:
    states: List[str] = []
    for decl in decls:
        for method in decl.methods:
            if method.name == method_name:
                states.extend(state for state in method.returned_values.get(field_name, []) if state not in states)
    return states


WILDCARD_FLAG = "*"


def context_flags_of_text(text: str) -> Set[str]:
    """Keys a view `context` attribute sets; the wildcard when it cannot be read."""
    text = (text or "").strip()
    if not text:
        return set()
    try:
        tree = ast.parse(text, mode="eval").body
    except SyntaxError:
        return {WILDCARD_FLAG}
    if not isinstance(tree, ast.Dict) or not all(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in tree.keys):
        return {WILDCARD_FLAG}
    return {key.value for key in tree.keys}


def write_reachable(method, field_name: str, state: str, context_flags: Optional[Set[str]]) -> bool:
    """A guarded write is reachable only when every flag of one of its occurrences is set on the path."""
    if context_flags is None or WILDCARD_FLAG in context_flags:
        return True
    occurrences = getattr(method, "written_guards", {}).get(field_name, {}).get(state)
    return not occurrences or any(set(flags) <= context_flags for flags in occurrences)


def written_states(decls: Sequence, method_name: str, field_name: str, depth: int = MAX_CALL_DEPTH, seen: Optional[Set] = None,
                   context_flags: Optional[Set[str]] = None) -> List[str]:
    """States a method may write, following its calls; `context_flags` = flags set on the path so far (None: unfiltered)."""
    seen = set() if seen is None else seen
    visit_key = (method_name, None if context_flags is None else frozenset(context_flags))
    if depth < 0 or visit_key in seen:
        return []
    seen.add(visit_key)
    states: List[str] = []
    for decl in decls:
        for method in decl.methods:
            if method.name != method_name:
                continue
            for state in method.written_values.get(field_name, []):
                if state not in states and write_reachable(method, field_name, state, context_flags):
                    states.append(state)
            for helper in method.write_argument_methods:
                for state in returned_states(decls, helper, field_name):
                    if state not in states:
                        states.append(state)
            for callee in method.called_self_methods:
                callee_flags = None if context_flags is None else context_flags | set(getattr(method, "call_context_flags", {}).get(callee, ()))
                for state in written_states(decls, callee, field_name, depth - 1, seen, callee_flags):
                    if state not in states:
                        states.append(state)
    return states


def workflow_transition_records(edge_data: dict) -> List[dict]:
    records = edge_data.get("button_transitions")
    if isinstance(records, list):
        return [record for record in records if isinstance(record, dict)]
    if not edge_data.get("method_name"):
        return []
    return [{
        "method_name": edge_data.get("method_name", ""),
        "label_bouton": edge_data.get("label_bouton", ""),
        "groupe_requis": edge_data.get("groupe_requis", []),
        "alternative": bool(edge_data.get("alternative", False)),
    }]


def encloses_whole(text: str) -> bool:
    depth = 0
    for index, char in enumerate(text):
        depth += (char == "(") - (char == ")")
        if depth == 0 and index < len(text) - 1:
            return False
    return depth == 0


def strip_outer_parentheses(text: str) -> str:
    text = text.strip()
    while text.startswith("(") and text.endswith(")") and encloses_whole(text):
        text = text[1:-1].strip()
    return text


def split_on_or(expression: str) -> List[str]:
    parts: List[str] = []
    depth = 0
    quote = ""
    current = ""
    index = 0
    while index < len(expression):
        char = expression[index]
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif depth == 0 and re.match(r"\s+or\s+", expression[index:]):
            parts.append(current)
            current = ""
            index += re.match(r"\s+or\s+", expression[index:]).end()
            continue
        current += char
        index += 1
    parts.append(current)
    return parts


def string_set(value) -> Optional[Set[str]]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set)) and all(isinstance(item, str) for item in value):
        return set(value)
    return None


def literal_strings(text: str) -> Optional[Set[str]]:
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None
    return string_set(value)


def origin_states(states_attr: str, invisible: str, selection: Optional[Sequence[str]], field_name: str) -> Optional[List[str]]:
    allowed: Optional[Set[str]] = None
    forbidden: Set[str] = set()
    predicate = state_predicate(field_name)
    if states_attr:
        allowed = {item.strip() for item in states_attr.split(",") if item.strip()}
    for part in split_on_or(invisible or ""):
        match = predicate.match(strip_outer_parentheses(part))
        values = literal_strings(match.group(2)) if match else None
        if values is None:
            continue
        operator = re.sub(r"\s+", " ", match.group(1))
        if operator in ("!=", "not in"):
            allowed = values if allowed is None else allowed & values
        else:
            forbidden |= values
    if allowed is None and forbidden and selection:
        allowed = set(selection)
    if allowed is None:
        return None
    allowed -= forbidden
    if selection:
        allowed &= set(selection)
        ordered = [state for state in selection if state in allowed]
    else:
        ordered = sorted(allowed)
    return ordered or None


def state_admitted_by_domain(domain_terms: Sequence, state: str, field_name: str) -> bool:
    for term in domain_terms:
        if not (isinstance(term, (tuple, list)) and len(term) == 3 and term[0] == field_name):
            continue
        _, operator, value = term
        values = string_set(value)
        if values is None:
            continue
        if operator in ("=", "in") and state not in values:
            return False
        if operator in ("!=", "not in") and state in values:
            return False
    return True


def domain_admits_any_state(domain_text: str, states: Sequence[str], field_name: Optional[str]) -> bool:
    if not domain_text or not states or not field_name:
        return True
    try:
        terms = ast.literal_eval(domain_text.strip())
    except (ValueError, SyntaxError):
        return True
    if not isinstance(terms, list) or any(term in ("|", "!") for term in terms if isinstance(term, str)):
        return True
    return any(state_admitted_by_domain(terms, state, field_name) for state in states)
