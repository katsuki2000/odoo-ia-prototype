"""Resolve model references against names present in the parsed corpus."""

from collections.abc import Iterable, Mapping


def build_model_xmlref_index(modelNames: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Index technical names and generated Odoo model XML-ID suffixes."""
    buckets = {}
    for modelName in sorted(set(modelNames)):
        if not modelName:
            continue
        xmlId = 'model_' + modelName.replace('.', '_')
        for reference in (modelName, xmlId):
            buckets.setdefault(reference, set()).add(modelName)
    return {reference: tuple(sorted(names)) for reference, names in buckets.items()}


def resolve_model_ref(rawRef: str | None, modelIndex: Mapping[str, tuple[str, ...]]) -> str | None:
    """Return a unique indexed target, never infer a name from underscores."""
    if not isinstance(rawRef, str) or not rawRef.strip():
        return None
    reference = rawRef.strip()
    candidates = set(modelIndex.get(reference, ()))
    if '.' in reference:
        localRef = reference.split('.', 1)[1]
        if localRef.startswith('model_'):
            candidates.update(modelIndex.get(localRef, ()))
    return next(iter(candidates)) if len(candidates) == 1 else None
