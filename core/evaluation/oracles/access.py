"""Draft access-right evaluation cases whose ground truth is Odoo itself, queried per demo user."""

from __future__ import annotations

from typing import Mapping, Sequence

from core.evaluation import instances as ib
from core.evaluation.oracles.common import DEFAULT_COMPANY, language_phrases, run_oracle, slug

ORACLE_MARKER = "ACCESS_ORACLE:"
OPERATIONS = ("read", "write", "create", "unlink")
DEFAULT_MODELS = (
    "sale.order", "purchase.order", "stock.picking", "account.move",
    "hr.employee", "hr.leave", "crm.lead", "project.task",
)

PHRASES = {
    "fr": {
        "question": "Puis-je {verb} les enregistrements du modèle « {model} » ?",
        "verbs": {"read": "consulter", "write": "modifier", "create": "créer", "unlink": "supprimer"},
        "operation_terms": {
            "read": ("lire", "lecture", "consulter", "consultation"),
            "write": ("modifier", "modification", "écrire", "écriture"),
            "create": ("créer", "création"),
            "unlink": ("supprimer", "suppression"),
        },
        "positive": ("vous pouvez", "oui", "autorisé", "accès"),
        "negative": (
            "ne pouvez pas", "ne peut pas", "n'avez pas accès", "n'avez pas le droit", "pas le droit",
            "pas d'accès", "aucun accès", "non autorisé", "pas autorisé", "interdit", "refus", "impossible",
        ),
    },
    "en": {
        "question": "Can I {verb} records of the model \"{model}\"?",
        "verbs": {"read": "read", "write": "edit", "create": "create", "unlink": "delete"},
        "operation_terms": {
            "read": ("read", "view", "access"),
            "write": ("write", "edit", "modify", "update"),
            "create": ("create",),
            "unlink": ("delete", "remove", "unlink"),
        },
        "positive": ("you can", "yes", "allowed", "access"),
        "negative": (
            "cannot", "can't", "not allowed", "not permitted", "denied", "no access", "no permission",
            "don't have access", "do not have access", "don't have permission", "do not have permission",
            "forbidden", "unable", "not able",
        ),
    },
}

ORACLE_BODY = """
rows = []
xmlids = {
    row.res_id: row.module + '.' + row.name
    for row in env['ir.model.data'].search([('model', '=', 'res.users')])
}
if params['users']:
    users = [(xmlid, env.ref(xmlid)) for xmlid in params['users']]
else:
    candidates = env['res.users'].search([('active', '=', True)])
    users = [(xmlids[user.id], user) for user in candidates if user.id in xmlids][:params['max_users']]
for model in params['models']:
    if model not in env:
        continue
    record = env['ir.model'].with_context(lang=params['language']).search([('model', '=', model)], limit=1)
    module = (record.modules or '').split(',')[0].strip()
    for xmlid, user in users:
        scoped = env[model].with_user(user)
        for operation in params['operations']:
            rows.append({
                'model': model,
                'label': record.name,
                'module': module,
                'user': xmlid,
                'operation': operation,
                'allowed': bool(scoped.check_access_rights(operation, raise_exception=False)),
            })
print('__MARKER__' + json.dumps(rows))
"""


def build_oracle_script(params: Mapping) -> str:
    return ib.build_shell_script(params, ORACLE_BODY, ORACLE_MARKER)


def query_access_matrix(
    spec: ib.InstanceSpec,
    env: ib.BuildEnvironment,
    runner: ib.Runner = ib.run_command,
    models: Sequence[str] = DEFAULT_MODELS,
    users: Sequence[str] = (),
    operations: Sequence[str] = OPERATIONS,
    max_users: int = 3,
) -> list:
    unknown = set(operations) - set(OPERATIONS)
    if unknown:
        raise ValueError(f"unknown operations: {sorted(unknown)}")
    params = {
        "models": list(models),
        "users": list(users),
        "operations": list(operations),
        "max_users": max_users,
        "language": spec.language,
    }
    return run_oracle(spec, env, runner, "access", ORACLE_BODY, ORACLE_MARKER, params)


def claim_for(row: Mapping, phrases: Mapping) -> dict:
    terms = [row["label"], row["model"]]
    verdict_terms = phrases["positive"] if row["allowed"] else phrases["negative"]
    return {
        "claim_id": "access_decision",
        "statement": f"{'Allowed' if row['allowed'] else 'Denied'}: {row['operation']} on {row['model']}",
        "any_of": [terms, list(phrases["operation_terms"][row["operation"]]), list(verdict_terms)],
        "none_of": list(phrases["negative"]) if row["allowed"] else [],
    }


def case_from_row(spec: ib.InstanceSpec, row: Mapping, phrases: Mapping) -> dict:
    return {
        "case_id": slug("access", spec.name, row["user"], row["model"], row["operation"]),
        "split": spec.split,
        "instance": spec.name,
        "user_context": {"user": row["user"], "company": DEFAULT_COMPANY, "language": spec.language, "groups": []},
        "question": phrases["question"].format(verb=phrases["verbs"][row["operation"]], model=row["label"]),
        "module": row["module"],
        "expected_intent": "governance_security",
        "expected_sources": ["code"],
        "expected_objects": [f"model:{row['model']}"],
        "acceptable_evidence": [{"kind": "graph", "source": f"model:{row['model']}"}],
        "expected_claims": [claim_for(row, phrases)],
        "abstention_rule": "none",
        "ground_truth": {"author": "odoo_oracle", "method": "odoo_oracle", "reference": "check_access_rights"},
    }


def rows_to_cases(spec: ib.InstanceSpec, rows: Sequence[Mapping]) -> list:
    phrases = language_phrases(PHRASES, spec.language)
    return [case_from_row(spec, row, phrases) for row in rows]
