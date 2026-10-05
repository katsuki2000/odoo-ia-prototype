"""Hermetic tests for the protocol runner and report."""

import json

import pytest

from core.evaluation import frozen_cases as fc
from core.evaluation import protocol_metrics as pm
from core.evaluation import protocol_report as pr
from core.evaluation import protocol_runner as runner
from tests.frozen_case_samples import make_case

PREREG = pm.Preregistration(0.8, 0.95, 100, 1, 2, 1, 0.1, True)


def dataset():
    rows = [make_case("a"), make_case("b", split="calibration", instance="adversarial_custom")]
    return fc.dataset_from_payload(fc.freeze_dataset(rows, 1))


def write_raw(directory, instance, rows):
    path = directory / f"{instance}.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_collect_results_maps_raw_rows(tmp_path):
    data = dataset()
    runner.prepare_run(data, tmp_path)
    write_raw(tmp_path, "sales_purchase_stock", [
        {"case_id": "a", "raw": {"answer": "A sales manager can read a quotation.", "route": "code_intelligence"}},
        {"case_id": "stale", "raw": {"answer": "ignored"}},
    ])
    results = runner.collect_results(data, tmp_path)
    assert [result.case_id for result in results] == ["a"]
    assert results[0].outcome == "answered" and results[0].sources_used == ("code",)


def test_raw_directory_is_bound_to_dataset_digest(tmp_path):
    data = dataset()
    runner.prepare_run(data, tmp_path)
    other = fc.dataset_from_payload(fc.freeze_dataset([make_case("a", question="Changed?")], 2))
    with pytest.raises(ValueError):
        runner.prepare_run(other, tmp_path)
    with pytest.raises(ValueError):
        runner.collect_results(other, tmp_path)
    with pytest.raises(ValueError):
        runner.collect_results(data, tmp_path / "empty")


def test_run_protocol_collects_failures_per_instance(tmp_path, monkeypatch):
    data = dataset()
    called = []

    def fake_run(spec, cases, env, raw_path, project_root):
        called.append(spec.name)
        if spec.name == "adversarial_custom":
            raise RuntimeError("down")

    monkeypatch.setattr(runner, "run_instance", fake_run)
    specs = fc_specs()
    failures = runner.run_protocol(data, specs, None, tmp_path, tmp_path)
    assert sorted(called) == ["adversarial_custom", "sales_purchase_stock"]
    assert failures == [{"name": "adversarial_custom", "error": "down"}]
    assert runner.run_protocol(data, specs, None, tmp_path, tmp_path, only=["sales_purchase_stock"]) == []


def fc_specs():
    from core.evaluation.instances import InstanceSpec

    def spec(name, split):
        return InstanceSpec.from_dict({
            "name": name, "split": split, "modules": ["sale"], "language": "en_US",
            "with_demo": True, "addons": ["core"],
        })

    return [spec("sales_purchase_stock", "held_out"), spec("adversarial_custom", "calibration"), spec("unused", "held_out")]


def test_report_rendering_and_writing(tmp_path):
    data = dataset()
    results = [pm.CaseResult("a", "answered", "A sales manager can read a quotation.")]
    report = pm.evaluate(data, results, PREREG)
    text = pr.render_markdown(report)
    assert "Split: held_out" in text and "Verdict:" in text and "n/a" in text
    json_path, markdown_path = pr.write_report(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["dataset"]["version"] == 1
    assert markdown_path.read_text(encoding="utf-8") == text


def test_load_ratings(tmp_path):
    assert runner.load_ratings(None) is None
    path = tmp_path / "ratings.json"
    path.write_text(json.dumps({"a": 1, "b": 0}), encoding="utf-8")
    assert runner.load_ratings(path) == {"a": True, "b": False}
