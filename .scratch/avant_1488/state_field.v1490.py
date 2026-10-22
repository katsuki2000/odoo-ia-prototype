"""The lifecycle field of a model: Odoo's own `state`, else the field its action methods set as constants."""

from __future__ import annotations

from typing import Iterable, List, Optional

# Odoo gives this name to the lifecycle field: the `states=` attributes of fields and buttons are relative to it.
ODOO_STATE_FIELD = "state"


def selection_options(decls: Iterable, field_name: str) -> List[str]:
    options: List[str] = []
    for decl in decls:
        for field in decl.fields:
            if field.name == field_name:
                options.extend(value for value in (field.selection or []) + (field.selection_add or []) if value not in options)
    return options


def is_action_method(method) -> bool:
    return not method.name.startswith("_") and not method.decorators


def written_constants(decls: Iterable, field_name: str, *, action_methods_only: bool = False) -> List[str]:
    constants: List[str] = []
    for decl in decls:
        for method in decl.methods:
            if action_methods_only and not is_action_method(method):
                continue
            for bucket in (method.written_values, method.returned_values):
                constants.extend(value for value in bucket.get(field_name, []) if value not in constants)
    return constants


def lifecycle_field(decls: Iterable) -> Optional[str]:
    """`state` when the model declares it; otherwise the stored Selection field whose options its action methods set most."""
    decls = list(decls)
    if any(field.name == ODOO_STATE_FIELD for decl in decls for field in decl.fields):
        return ODOO_STATE_FIELD
    computed = {field.name for decl in decls for field in decl.fields if field.compute}
    candidates: List[str] = []
    for decl in decls:
        for field in decl.fields:
            if field.field_type == "Selection" and field.name not in computed and field.name not in candidates:
                candidates.append(field.name)
    best, best_count = None, 0
    for name in candidates:
        options = set(selection_options(decls, name))
        count = len(options.intersection(written_constants(decls, name, action_methods_only=True)))
        if count > best_count:
            best, best_count = name, count
    return best
