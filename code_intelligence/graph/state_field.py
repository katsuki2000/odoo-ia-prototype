"""The lifecycle field of a model: Odoo's own `state`, else the field its action methods set as constants."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

from .workflow_extraction import selection_values, written_states

# Odoo gives this name to the lifecycle field: the `states=` attributes of fields and buttons are relative to it.
ODOO_STATE_FIELD = "state"


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


def lifecycle_field(decls: Iterable) -> Optional[str]:
    """`state` when the model declares it; otherwise the stored Selection field whose options its action methods set most."""
    decls = list(decls)
    if any(field.name == ODOO_STATE_FIELD for decl in decls for field in decl.fields):
        return ODOO_STATE_FIELD
    computed = {field.name for decl in decls for field in decl.fields if field.compute}
    names: List[str] = []
    for decl in decls:
        for field in decl.fields:
            if field.field_type == "Selection" and field.name not in computed and field.name not in names:
                names.append(field.name)
    best, best_count = None, 0
    for name in names:
        count = action_written_options(decls, name)
        if count > best_count:
            best, best_count = name, count
    return best


def lifecycle_fields(registry, modules_dict=None) -> Dict[str, str]:
    fields = {model: lifecycle_field(decls) for model, decls in registry.models.items()}
    return {model: field for model, field in fields.items() if field}
