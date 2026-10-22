"""The lifecycle field of each model, found from its form-view buttons and its action methods, never by name."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Sequence

from .workflow_extraction import literal_strings, selection_values, split_on_or, strip_outer_parentheses, written_states

FIELD_PREDICATE = re.compile(r"^(\w+)\s+(==|!=|not\s+in|in)\s+(.+)$")


def selection_fields(decls: Iterable) -> List[str]:
    names: List[str] = []
    for decl in decls:
        for field in decl.fields:
            if field.field_type == "Selection" and field.name not in names:
                names.append(field.name)
    return names


def button_references(decls: Sequence, buttons: Iterable) -> Counter:
    """How many buttons hide themselves on a state of each Selection field of the model."""
    options = {name: set(selection_values(decls, name) or ()) for name in selection_fields(decls)}
    counts: Counter = Counter()
    for button in buttons:
        referenced = set()
        for part in split_on_or(button.invisible or ""):
            match = FIELD_PREDICATE.match(strip_outer_parentheses(part))
            if not match or match.group(1) not in options:
                continue
            values = literal_strings(match.group(3))
            known = options[match.group(1)]
            if values is not None and (not known or values <= known):
                referenced.add(match.group(1))
        counts.update(referenced)
    return counts


def is_action_method(method) -> bool:
    return not method.name.startswith("_") and not method.decorators


def action_written_options(decls: Sequence, field_name: str) -> int:
    options = set(selection_values(decls, field_name) or ())
    written = set()
    for decl in decls:
        for method in decl.methods:
            if is_action_method(method):
                written.update(written_states(decls, method.name, field_name))
    return len(options & written)


def written_options(decls: Sequence, field_name: str) -> int:
    """Options of the field that some method sets as a constant, whatever the method."""
    options = set(selection_values(decls, field_name) or ())
    written = set()
    for decl in decls:
        for method in decl.methods:
            written.update(method.written_values.get(field_name, ()))
            written.update(method.returned_values.get(field_name, ()))
    return len(options & written) if options else len(written)


def lifecycle_field(decls: Iterable, buttons: Iterable = ()) -> Optional[str]:
    """Selection field that buttons hide on and methods set (most of both); else the one action methods set most."""
    decls = list(decls)
    names = selection_fields(decls)
    counts = button_references(decls, buttons)
    best, best_count = None, 0
    for name in names:
        score = counts[name] * written_options(decls, name)
        if score > best_count:
            best, best_count = name, score
    if best:
        return best
    computed = {field.name for decl in decls for field in decl.fields if field.compute}
    for name in names:
        if name in computed:
            continue
        count = action_written_options(decls, name)
        if count > best_count:
            best, best_count = name, count
    return best


def lifecycle_fields(registry, modules_dict) -> Dict[str, str]:
    buttons: Dict[str, list] = defaultdict(list)
    for module in modules_dict.values():
        for view in module.views:
            buttons[view.model].extend(view.buttons)
    fields = {model: lifecycle_field(decls, buttons.get(model, ())) for model, decls in registry.models.items()}
    return {model: field for model, field in fields.items() if field}
