"""Build the "Check in Odoo" link of an ERP answer from the evidence dossier only.

Pure function, no Odoo import: the link is derived from what the agent actually read
(`scope.request` of the last row read), never from the text written by the LLM.
"""

# Methods whose `scope.request` carries a domain, and `read`, which carries ids.
DOMAIN_METHODS = ('search', 'search_read', 'search_count', 'read_group')
IDS_METHOD = 'read'
# Schema lookups are not data reads: they are skipped when looking for the last read.
SCHEMA_METHODS = ('fields_get', 'list_models', 'get_available_models')


def _clean_domain(domain):
    """Return the domain as a JSON-friendly list, or None when it is not a list."""
    if not isinstance(domain, (list, tuple)):
        return None
    return [list(item) if isinstance(item, tuple) else item for item in domain]


def _clean_ids(ids):
    if not isinstance(ids, (list, tuple)):
        return None
    cleaned = [value for value in ids if type(value) is int]
    if not cleaned or len(cleaned) != len(ids):
        return None
    return cleaned


def _last_data_read(evidence_dossier):
    for item in reversed(evidence_dossier):
        if not isinstance(item, dict):
            continue
        scope = item.get('scope')
        if not isinstance(scope, dict) or scope.get('method') in SCHEMA_METHODS:
            continue
        if isinstance(scope.get('model'), str) and isinstance(scope.get('request'), dict):
            return scope
    return None


def verify_link(evidence_dossier):
    """Return {'model': str, 'domain': list} for the last successful data read, or None."""
    if not isinstance(evidence_dossier, (list, tuple)):
        return None
    scope = _last_data_read(evidence_dossier)
    if scope is None:
        return None
    method = scope.get('method')
    model = scope['model']
    request = scope['request']
    if method in DOMAIN_METHODS:
        domain = _clean_domain(request.get('domain'))
        if domain is None:
            return None
        return {'model': model, 'domain': domain}
    if method == IDS_METHOD:
        ids = _clean_ids(request.get('ids'))
        if ids is None:
            return None
        return {'model': model, 'domain': [['id', 'in', ids]]}
    return None
