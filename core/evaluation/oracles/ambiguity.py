"""Draft ambiguity cases: generic terms that designate several fields of an instance, Odoo being the oracle."""

from __future__ import annotations

from typing import Mapping, Sequence

from core.evaluation import instances as ib
from core.evaluation.oracles.common import DEFAULT_COMPANY, DEFAULT_USER, language_phrases, run_oracle, slug

ORACLE_MARKER = "AMBIGUITY_ORACLE:"
CROSS_MODULE = "cross_module"
IGNORED_FIELDS = ("id", "create_uid", "create_date", "write_uid", "write_date", "display_name", "__last_update")
SAMPLE_SIZE = 5
DEFAULT_MIN_MODULES = 3
DEFAULT_LIMIT = 10

PHRASES = {
    "fr": {"question": "Comment fonctionne « {term} » ?"},
    "en": {"question": "How does \"{term}\" work?"},
}

ORACLE_BODY = """
translated = env['ir.model'].with_context(lang=params['language'])
domains = {}
model_labels = set()
for record in translated.search([('transient', '=', False)]):
    if record.model not in env or env[record.model]._abstract:
        continue
    domains[record.model] = (record.modules or '').split(',')[0].strip()
    model_labels.add((record.name or '').strip())
fields = env['ir.model.fields'].with_context(lang=params['language']).search_read(
    [('model', 'in', list(domains)), ('name', 'not in', params['ignored_fields'])],
    ['model', 'field_description', 'modules'],
)
owners = {}
for row in fields:
    label = (row['field_description'] or '').strip()
    own = domains[row['model']] in (row['modules'] or '').replace(' ', '').split(',')
    if own and label and label not in model_labels:
        owners.setdefault(label, {})[row['model']] = domains[row['model']]
rows = []
for label, by_model in owners.items():
    modules = sorted(set(by_model.values()))
    if len(modules) >= params['min_modules']:
        rows.append({
            'label': label,
            'model_count': len(by_model),
            'module_count': len(modules),
            'models': sorted(by_model)[:params['sample_size']],
            'modules': modules[:params['sample_size']],
        })
print('__MARKER__' + json.dumps(rows))
"""


def query_ambiguous_terms(
    spec: ib.InstanceSpec,
    env: ib.BuildEnvironment,
    runner: ib.Runner = ib.run_command,
    min_modules: int = DEFAULT_MIN_MODULES,
) -> list:
    params = {
        "language": spec.language,
        "min_modules": min_modules,
        "ignored_fields": list(IGNORED_FIELDS),
        "sample_size": SAMPLE_SIZE,
    }
    return run_oracle(spec, env, runner, "ambiguity", ORACLE_BODY, ORACLE_MARKER, params)


def rank_terms(rows: Sequence[Mapping], limit: int) -> list:
    ranked = sorted(rows, key=lambda row: (-row["module_count"], -row["model_count"], row["label"]))
    picked, seen = [], set()
    for row in ranked:
        key = slug(row["label"])
        if key and key not in seen:
            seen.add(key)
            picked.append(row)
    return picked[:limit]


def case_from_term(spec: ib.InstanceSpec, row: Mapping, phrases: Mapping, user: str) -> dict:
    return {
        "case_id": slug("ambiguity", spec.name, row["label"]),
        "split": spec.split,
        "instance": spec.name,
        "user_context": {"user": user, "company": DEFAULT_COMPANY, "language": spec.language, "groups": []},
        "question": phrases["question"].format(term=row["label"]),
        "module": CROSS_MODULE,
        "expected_intent": "general_code_inquiry",
        "expected_sources": ["code"],
        "expected_objects": [],
        "acceptable_evidence": [],
        "expected_claims": [],
        "abstention_rule": "must_clarify",
        "ground_truth": {
            "author": "odoo_oracle",
            "method": "odoo_oracle",
            "reference": f"field label shared by {row['model_count']} models in {row['module_count']} modules",
        },
    }


def rows_to_cases(
    spec: ib.InstanceSpec, rows: Sequence[Mapping], limit: int = DEFAULT_LIMIT, user: str = DEFAULT_USER,
) -> list:
    phrases = language_phrases(PHRASES, spec.language)
    return [case_from_term(spec, row, phrases, user) for row in rank_terms(rows, limit)]
