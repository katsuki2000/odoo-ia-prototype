"""Hermetic tests for the access-right case generator."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.evaluation.oracles import access as ao, common
from core.evaluation import frozen_cases as fc
from core.evaluation import instances as ib
from core.evaluation import protocol_metrics as pm
from tests.eval_instance_helpers import make_env, make_module, make_spec

ROWS = [
    {"model": "sale.order", "label": "Sales Order", "module": "sale", "user": "base.user_demo",
     "operation": "read", "allowed": True},
    {"model": "sale.order", "label": "Sales Order", "module": "sale", "user": "base.user_demo",
     "operation": "unlink", "allowed": False},
]


def fake_runner(rows):
    calls = []

    def runner(command, stdin=None, env=None):
        calls.append((list(command), stdin))
        return SimpleNamespace(returncode=0, stdout="log\n" + ao.ORACLE_MARKER + json.dumps(rows), stderr="")

    runner.calls = calls
    return runner


def spec_for(language="en_US"):
    return make_spec(name="sales_purchase_stock", language=language)


def test_oracle_script_embeds_parameters_and_marker():
    script = ao.build_oracle_script({"models": ["sale.order"], "language": "fr_FR"})
    compile(script, "oracle", "exec")
    assert "sale.order" in script and ao.ORACLE_MARKER in script and "check_access_rights" in script


def test_query_runs_the_shell_subcommand_and_parses_rows(tmp_path):
    env = make_env(tmp_path)
    make_module(Path(env.core_addons), "sale")
    runner = fake_runner(ROWS)
    rows = ao.query_access_matrix(spec_for(), env, runner, models=["sale.order"], users=["base.user_demo"])
    assert rows == ROWS
    command, stdin = runner.calls[0]
    assert command[2] == "shell" and "base.user_demo" in stdin
    with pytest.raises(ValueError):
        ao.query_access_matrix(spec_for(), env, runner, operations=["fly"])


@pytest.mark.parametrize("language", ["en_US", "fr_FR"])
def test_generated_cases_are_valid_and_polarity_is_scored(language):
    cases = ao.rows_to_cases(spec_for(language), ROWS)
    parsed = fc.parse_cases(cases)
    allowed = next(case for case in parsed if case.case_id.endswith("_read"))
    denied = next(case for case in parsed if case.case_id.endswith("_unlink"))
    allow_text = {"en_US": "Yes, you can read a Sales Order.", "fr_FR": "Oui, vous pouvez lire une Sales Order."}[language]
    deny_text = {"en_US": "You cannot delete a Sales Order.", "fr_FR": "Vous ne pouvez pas supprimer une Sales Order."}[language]
    for case, good, bad in ((allowed, allow_text, deny_text), (denied, deny_text, allow_text)):
        claim = case.expected_claims[0]
        assert pm.claim_matched(claim, good)
        assert not pm.claim_matched(claim, bad)


def test_cases_use_external_ids_and_oracle_ground_truth():
    case = fc.parse_cases(ao.rows_to_cases(spec_for(), ROWS))[0]
    assert case.user_context.user == "base.user_demo"
    assert case.ground_truth.method == "odoo_oracle"
    assert case.split == "held_out" and case.expected_objects == ("model:sale.order",)


def test_unsupported_language_is_rejected():
    with pytest.raises(ValueError):
        ao.rows_to_cases(spec_for("de_DE"), ROWS)


def test_write_draft_round_trip(tmp_path):
    cases = ao.rows_to_cases(spec_for(), ROWS)
    path = common.write_draft(cases, tmp_path / "drafts" / "x.json")
    assert json.loads(path.read_text(encoding="utf-8")) == cases
    assert fc.freeze_dataset(cases, 1)["digest"]
