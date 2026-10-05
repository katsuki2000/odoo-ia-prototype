"""Hermetic tests for the ambiguity case generator."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.evaluation import frozen_cases as fc
from core.evaluation import protocol_metrics as pm
from core.evaluation.oracles import ambiguity as am
from core.evaluation.oracles import common
from tests.eval_instance_helpers import make_env, make_module, make_spec

ROWS = [
    {"label": "Notes", "model_count": 6, "module_count": 4, "models": ["sale.order"], "modules": ["sale"]},
    {"label": "Reference", "model_count": 9, "module_count": 5, "models": ["sale.order"], "modules": ["sale"]},
    {"label": "Référence", "model_count": 3, "module_count": 3, "models": ["hr.leave"], "modules": ["hr"]},
    {"label": "Reference!", "model_count": 2, "module_count": 3, "models": ["crm.lead"], "modules": ["crm"]},
    {"label": "???", "model_count": 4, "module_count": 3, "models": ["x.y"], "modules": ["x"]},
]


def fake_runner(rows):
    calls = []

    def runner(command, stdin=None, env=None):
        calls.append((list(command), stdin))
        return SimpleNamespace(returncode=0, stdout="log\n" + am.ORACLE_MARKER + json.dumps(rows), stderr="")

    runner.calls = calls
    return runner


def test_oracle_script_is_valid_python_with_parameters_and_marker():
    params = {"language": "fr_FR", "min_modules": 3, "ignored_fields": list(am.IGNORED_FIELDS), "sample_size": 5}
    script = common.ib.build_shell_script(params, am.ORACLE_BODY, am.ORACLE_MARKER)
    compile(script, "oracle", "exec")
    assert am.ORACLE_MARKER in script and "field_description" in script and "min_modules" in script


def test_query_runs_the_shell_subcommand_and_parses_rows(tmp_path):
    env = make_env(tmp_path)
    make_module(Path(env.core_addons), "sale")
    runner = fake_runner(ROWS)
    assert am.query_ambiguous_terms(make_spec(), env, runner, min_modules=4) == ROWS
    command, stdin = runner.calls[0]
    assert command[2] == "shell" and 'min_modules\\": 4' in stdin


def test_ranking_is_deterministic_and_drops_unusable_or_duplicate_labels():
    ranked = am.rank_terms(ROWS, limit=10)
    assert [row["label"] for row in ranked] == ["Reference", "Notes"]
    assert am.rank_terms(list(reversed(ROWS)), limit=10) == ranked
    assert len(am.rank_terms(ROWS, limit=2)) == 2


@pytest.mark.parametrize("language", ["en_US", "fr_FR"])
def test_generated_cases_are_valid_clarification_cases(language):
    cases = am.rows_to_cases(make_spec(language=language), ROWS)
    parsed = fc.parse_cases(cases)
    assert {case.abstention_rule for case in parsed} == {"must_clarify"}
    assert all(case.expected_claims == () and case.expected_objects == () for case in parsed)
    assert all(case.module == am.CROSS_MODULE and case.ground_truth.method == "odoo_oracle" for case in parsed)
    assert all(any(label in case.question for label in ("Reference", "Notes")) for case in parsed)


def test_clarification_is_correct_and_a_default_answer_is_not():
    case = fc.parse_cases(am.rows_to_cases(make_spec(), ROWS))[0]
    assert pm.is_correct(case, pm.CaseResult(case.case_id, "clarification"))
    assert not pm.is_correct(case, pm.CaseResult(case.case_id, "answered", answer="It computes the order total."))


def test_unsupported_language_is_rejected():
    with pytest.raises(ValueError):
        am.rows_to_cases(make_spec(language="de_DE"), ROWS)


def test_drafts_freeze_into_a_dataset(tmp_path):
    cases = am.rows_to_cases(make_spec(), ROWS)
    path = common.write_draft(cases, tmp_path / "drafts" / "x.json")
    assert json.loads(path.read_text(encoding="utf-8")) == cases
    assert fc.freeze_dataset(cases, 1)["digest"]
