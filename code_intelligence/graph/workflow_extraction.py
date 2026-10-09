"""Workflow states and transitions derived from the parsed code, never from constants."""

from __future__ import annotations

import ast
import re
from typing import Iterable, List, Optional, Sequence, Set

from code_intelligence.extractor.python import STATE_FIELD

MAX_CALL_DEPTH = 3
STATE_PREDICATE = re.compile(r"^state\s+(==|!=|not\s+in|in)\s+(.+)$")


def selection_values(decls: Iterable) -> Optional[List[str]]:
    values: List[str] = []
    known = False
    for decl in decls:
        for field in decl.fields:
            if field.name != STATE_FIELD:
                continue
            for value in (field.selection or []) + (field.selection_add or []):
                known = True
                if value not in values:
                    values.append(value)
    return values if known else None


def returned_states(decls: Sequence, method_name: str) -> List[str]:
    states: List[str] = []
    for decl in decls:
        for method in decl.methods:
            if method.name == method_name:
                states.extend(state for state in method.returned_states if state not in states)
    return states


def written_states(decls: Sequence, method_name: str, depth: int = MAX_CALL_DEPTH, seen: Optional[Set[str]] = None) -> List[str]:
    seen = set() if seen is None else seen
    if depth < 0 or method_name in seen:
        return []
    seen.add(method_name)
    states: List[str] = []
    for decl in decls:
        for method in decl.methods:
            if method.name != method_name:
                continue
            for state in method.written_states:
                if state not in states:
                    states.append(state)
            for helper in method.write_argument_methods:
                for state in returned_states(decls, helper):
                    if state not in states:
                        states.append(state)
            for callee in method.called_self_methods:
                for state in written_states(decls, callee, depth - 1, seen):
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


def origin_states(states_attr: str, invisible: str, selection: Optional[Sequence[str]]) -> Optional[List[str]]:
    allowed: Optional[Set[str]] = None
    forbidden: Set[str] = set()
    if states_attr:
        allowed = {item.strip() for item in states_attr.split(",") if item.strip()}
    for part in split_on_or(invisible or ""):
        match = STATE_PREDICATE.match(strip_outer_parentheses(part))
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


def state_admitted_by_domain(domain_terms: Sequence, state: str) -> bool:
    for term in domain_terms:
        if not (isinstance(term, (tuple, list)) and len(term) == 3 and term[0] == STATE_FIELD):
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


def domain_admits_any_state(domain_text: str, states: Sequence[str]) -> bool:
    if not domain_text or not states:
        return True
    try:
        terms = ast.literal_eval(domain_text.strip())
    except (ValueError, SyntaxError):
        return True
    if not isinstance(terms, list) or any(term in ("|", "!") for term in terms if isinstance(term, str)):
        return True
    return any(state_admitted_by_domain(terms, state) for state in states)
