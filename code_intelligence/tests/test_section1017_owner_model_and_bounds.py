"""
Section 1017: model attribution of file-scoped Semgrep matches and
deterministic bounds facts for chained-comparison @api.constrains guards.
"""

from __future__ import annotations

import textwrap

from code_intelligence.rules import data_constraints as dc
from code_intelligence.rules.data_constraints import (
    SemgrepMatch,
    _annotate_owner_models,
    _bounds_facts,
    _compose_data_constraints_summary,
    backfill_missing_bounds_facts,
)

MULTI_MODEL_SOURCE = textwrap.dedent(
    '''\
    from odoo import models


    class Equipment(models.Model):
        _name = 'demo.equipment'

        _sql_constraints = [
            ('serial_no', 'unique(serial_no)', "Duplicate serial"),
        ]


    class Request(models.Model):
        _name = 'demo.request'

        @api.constrains('repeat_interval')
        def _check_repeat_interval(self):
            for record in self:
                if record.repeat_interval < 1:
                    raise ValidationError("too small")


    class RequestExtension(models.Model):
        _inherit = 'demo.request'

        note = fields.Char()
    '''
)

RANGE_SOURCE = textwrap.dedent(
    '''\
    class Order(models.Model):
        _name = 'demo.order'

        @api.constrains('percent')
        def _check_percent(self):
            for order in self:
                if order.require_payment and not (0 < order.percent <= 1.0):
                    raise ValidationError("bad percent")
    '''
)


def _match(path, start, end, check_id, lines=""):
    return SemgrepMatch(
        filepath=str(path),
        start_line=start,
        end_line=end,
        check_id=check_id,
        message="m",
        lines=lines,
    )


def test_owner_model_resolved_per_enclosing_class(tmp_path):
    source = tmp_path / "demo.py"
    source.write_text(MULTI_MODEL_SOURCE)
    lines = MULTI_MODEL_SOURCE.splitlines()
    sql_line = next(i for i, l in enumerate(lines, 1) if "serial_no" in l)
    constrains_line = next(i for i, l in enumerate(lines, 1) if "api.constrains" in l)
    inherit_line = next(i for i, l in enumerate(lines, 1) if "note = " in l)
    matches = [
        _match(source, sql_line, sql_line, "odoo-sql-constraints-declaration"),
        _match(source, constrains_line, constrains_line + 4, "odoo-api-constrains-declaration"),
        _match(source, inherit_line, inherit_line, "odoo-selection-constraint-declaration"),
    ]
    _annotate_owner_models(matches)
    assert matches[0].owner_models == ("demo.equipment",)
    assert matches[1].owner_models == ("demo.request",)
    assert matches[2].owner_models == ("demo.request",)


def test_summary_shows_owner_model_next_to_each_finding(tmp_path):
    source = tmp_path / "demo.py"
    source.write_text(MULTI_MODEL_SOURCE)
    match = _match(source, 7, 9, "odoo-sql-constraints-declaration")
    _annotate_owner_models([match])
    summary = _compose_data_constraints_summary("demo.request", [match])
    assert "[model: demo.equipment]" in summary


def test_unparseable_file_leaves_owner_empty(tmp_path):
    source = tmp_path / "broken.py"
    source.write_text("class :\n")
    match = _match(source, 1, 1, "x")
    _annotate_owner_models([match])
    assert match.owner_models == ()


def test_bounds_fact_states_excluded_and_included_bounds(tmp_path):
    source = tmp_path / "order.py"
    source.write_text(RANGE_SOURCE)
    lines = RANGE_SOURCE.splitlines()
    start = next(i for i, l in enumerate(lines, 1) if "api.constrains" in l)
    match = _match(source, start, len(lines), "odoo-api-constrains-declaration")
    facts = _bounds_facts(match)
    assert len(facts) == 1
    assert "`0 < order.percent <= 1.0`" in facts[0]
    assert "lower bound 0 is excluded" in facts[0]
    assert "upper bound 1.0 is included" in facts[0]
    assert "`order.require_payment`" in facts[0]


def test_bounds_fact_falls_back_to_match_lines_when_file_missing(tmp_path):
    body = "\n".join(RANGE_SOURCE.splitlines()[3:])
    match = _match(tmp_path / "absent.py", 1, 1, "odoo-api-constrains-declaration", lines=body.strip())
    assert any("lower bound 0 is excluded" in fact for fact in _bounds_facts(match))


def test_no_bounds_fact_for_single_sided_comparison(tmp_path):
    source = tmp_path / "single.py"
    source.write_text(MULTI_MODEL_SOURCE)
    lines = MULTI_MODEL_SOURCE.splitlines()
    start = next(i for i, l in enumerate(lines, 1) if "api.constrains" in l)
    match = _match(source, start, start + 4, "odoo-api-constrains-declaration")
    assert _bounds_facts(match) == []


def test_bounds_fact_ignored_for_non_constrains_matches(tmp_path):
    source = tmp_path / "order.py"
    source.write_text(RANGE_SOURCE)
    assert _bounds_facts(_match(source, 1, 8, "odoo-sql-constraints-declaration")) == []


def test_backfill_appends_exclusion_when_answer_omits_it():
    observation = (
        "[BOUNDS LOGIC] `order.percent` is accepted only when `0 < order.percent <= 1.0`: "
        "the lower bound 0 is excluded and the upper bound 1.0 is included. "
        "Any value outside this range raises the error."
    )
    answer = "Le pourcentage doit etre compris entre 0 % et 100 % inclus."
    result = backfill_missing_bounds_facts(answer, observation, question="quelle contrainte valide le pourcentage ?")
    assert "borne basse 0 exclue" in result
    assert "borne haute 1.0 incluse" in result


def test_backfill_keeps_answer_that_already_signals_exclusion():
    observation = (
        "[BOUNDS LOGIC] `x` is accepted only when `0 < x <= 1`: "
        "the lower bound 0 is excluded and the upper bound 1 is included."
    )
    answer = "La valeur doit etre strictement superieure a 0 et au plus 1."
    assert backfill_missing_bounds_facts(answer, observation) == answer


def test_backfill_skips_unrelated_questions():
    observation = (
        "[BOUNDS LOGIC] `x` is accepted only when `0 < x <= 1`: "
        "the lower bound 0 is excluded and the upper bound 1 is included."
    )
    answer = "Reponse sans rapport."
    assert backfill_missing_bounds_facts(answer, observation, question="qui peut confirmer ?") == answer


def test_public_helpers_exported_from_module():
    assert callable(dc.backfill_missing_bounds_facts)
