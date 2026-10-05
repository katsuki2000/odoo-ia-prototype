"""Hermetic tests for the evaluation instance builder."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.evaluation import instances as ib
from tests.eval_instance_helpers import make_env, make_module, make_spec


def fake_runner(inspection=None, install_code=0, dump_code=0):
    payload = inspection or {
        "modules": [{"name": "sale", "installed_version": "17.0.1.0", "state": "installed"}],
        "languages": ["fr_FR"],
        "version": "17.0",
    }
    calls = []

    def runner(command, stdin=None, env=None):
        calls.append(list(command))
        if "pg_dump" in command:
            if dump_code == 0:
                Path(command[command.index("-f") + 1]).write_bytes(b"dump")
            return SimpleNamespace(returncode=dump_code, stdout="", stderr="no role")
        if "shell" in command:
            return SimpleNamespace(returncode=0, stdout=ib.INSPECTION_MARKER + json.dumps(payload), stderr="")
        if "rev-parse" in command:
            return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
        return SimpleNamespace(returncode=install_code, stdout="", stderr="boom")

    runner.calls = calls
    return runner


def test_load_specs_rejects_unknown_split_and_duplicates(tmp_path):
    bad_split = tmp_path / "a.json"
    bad_split.write_text(json.dumps([{**vars_of(make_spec()), "split": "other"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        ib.load_specs(bad_split)
    duplicated = tmp_path / "b.json"
    duplicated.write_text(json.dumps([vars_of(make_spec()), vars_of(make_spec())]), encoding="utf-8")
    with pytest.raises(ValueError):
        ib.load_specs(duplicated)


def vars_of(spec: ib.InstanceSpec) -> dict:
    return {
        "name": spec.name,
        "split": spec.split,
        "modules": list(spec.modules),
        "language": spec.language,
        "with_demo": spec.with_demo,
        "addons": list(spec.addons),
    }


def test_shipped_specs_are_valid():
    specs = ib.load_specs(Path(__file__).resolve().parent.parent / "core/evaluation/protocol/instances.json")
    assert {spec.split for spec in specs} == {"calibration", "held_out"}


def test_resolve_roots_and_missing_directory(tmp_path):
    env = make_env(tmp_path, oca=True)
    roots = ib.resolve_addon_roots(make_spec(addons=["core", "oca/sale-workflow"]), env)
    assert list(roots) == ["core", "oca/sale-workflow"]
    with pytest.raises(FileNotFoundError):
        ib.resolve_addon_roots(make_spec(addons=["core", "oca/absent"]), env)
    with pytest.raises(ValueError):
        ib.resolve_addon_roots(make_spec(addons=["unknown"]), env)


def test_missing_modules(tmp_path):
    env = make_env(tmp_path)
    make_module(Path(env.core_addons), "sale")
    roots = ib.resolve_addon_roots(make_spec(modules=["sale", "ghost"]), env).values()
    assert ib.missing_modules(make_spec(modules=["sale", "ghost"]), roots) == ["ghost"]


def test_install_command_flags(tmp_path):
    env = make_env(tmp_path)
    roots = list(ib.resolve_addon_roots(make_spec(), env).values())
    command = ib.install_command(make_spec(with_demo=False), env, roots, "eval_demo")
    assert "--without-demo=all" in command
    assert "--load-language=fr_FR" in command
    assert "sale" in command[command.index("-i") + 1]
    assert "--without-demo=all" not in ib.install_command(make_spec(), env, roots, "eval_demo")
    assert "-c" not in command
    assert command[0] == "odoo-python"
    assert "--logfile=" in command


def test_inspect_command_puts_shell_subcommand_first(tmp_path):
    env = make_env(tmp_path)
    roots = list(ib.resolve_addon_roots(make_spec(), env).values())
    command = ib.inspect_command(env, roots, "eval_demo")
    assert command[2] == "shell"
    assert command[command.index("-d") + 1] == "eval_demo"


def test_parse_inspection():
    assert ib.parse_inspection("noise\n" + ib.INSPECTION_MARKER + '{"a": 1}\n') == {"a": 1}
    with pytest.raises(RuntimeError):
        ib.parse_inspection("nothing")


def test_directory_digest_tracks_content_and_ignores_bytecode(tmp_path):
    module = make_module(tmp_path, "m", "one")
    first = ib.directory_digest(module)
    (module / "__pycache__").mkdir()
    (module / "__pycache__" / "x.pyc").write_bytes(b"junk")
    assert ib.directory_digest(module) == first
    (module / "models.py").write_text("two", encoding="utf-8")
    assert ib.directory_digest(module) != first


def test_build_instance_pins_custom_modules_and_fingerprints(tmp_path):
    env = make_env(tmp_path)
    make_module(Path(env.core_addons), "sale")
    make_module(Path(env.custom_addons), "sale_custom")
    spec = make_spec(modules=["sale", "sale_custom"], addons=["core", "custom"])
    runner = fake_runner({
        "modules": [
            {"name": "sale", "installed_version": "17.0.1.0", "state": "installed"},
            {"name": "sale_custom", "installed_version": "17.0.1.0", "state": "installed"},
        ],
        "languages": ["fr_FR"],
        "version": "17.0",
    })
    entry = ib.build_instance(spec, env, runner)
    assert entry["database"] == "eval_demo"
    assert list(entry["pinned_modules"]) == ["custom"]
    assert "sale_custom" in entry["pinned_modules"]["custom"]
    assert entry["core_git_head"] == "abc123"
    assert len(entry["fingerprint_digest"]) == 64
    assert entry["dump"] is None


def test_build_instance_inspect_only_skips_install(tmp_path):
    env = make_env(tmp_path)
    make_module(Path(env.core_addons), "sale")
    runner = fake_runner()
    ib.build_instance(make_spec(), env, runner, install=False)
    assert not any("-i" in call for call in runner.calls)


def test_build_all_records_failures(tmp_path):
    env = make_env(tmp_path)
    make_module(Path(env.core_addons), "sale")
    manifest = ib.build_all([make_spec()], env, fake_runner(install_code=1))
    assert manifest["instances"] == []
    assert manifest["failures"][0]["name"] == "Demo"
    missing = ib.build_all([make_spec(name="Other", modules=["ghost"])], env, fake_runner())
    assert "ghost" in missing["failures"][0]["error"]


def test_write_manifest_merges_with_existing_entries(tmp_path):
    ib.write_manifest({"instances": [{"name": "a", "v": 1}], "failures": [{"name": "b", "error": "x"}]}, tmp_path)
    ib.write_manifest({"instances": [{"name": "b", "v": 2}], "failures": []}, tmp_path)
    merged = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [row["name"] for row in merged["instances"]] == ["a", "b"]
    assert merged["failures"] == []


def test_write_manifest_replaces_stale_entry_on_new_failure(tmp_path):
    ib.write_manifest({"instances": [{"name": "a", "v": 1}], "failures": []}, tmp_path)
    ib.write_manifest({"instances": [], "failures": [{"name": "a", "error": "x"}]}, tmp_path)
    merged = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert merged["instances"] == []
    assert merged["failures"][0]["name"] == "a"


def test_require_success_keeps_odoo_error_lines_and_writes_log(tmp_path):
    stderr = "noise\n2026-10-02 10:00:00 1 ERROR db odoo.modules.loading: broken\n(ERROR/3) docutils\nlate noise"
    result = SimpleNamespace(returncode=1, stdout="", stderr=stderr)
    log = tmp_path / "logs" / "x.log"
    with pytest.raises(RuntimeError) as error:
        ib.require_success(result, "install x", log)
    assert "odoo.modules.loading: broken" in str(error.value)
    assert "docutils" not in str(error.value)
    assert "late noise" in log.read_text(encoding="utf-8")


def test_postgres_environment_reads_connection_options(tmp_path):
    conf = tmp_path / "odoo.conf"
    conf.write_text("[options]\ndb_host = localhost\ndb_user = odoo\ndb_password = False\ndb_port = 5432\n", encoding="utf-8")
    assert ib.postgres_environment(str(conf)) == {"PGHOST": "localhost", "PGUSER": "odoo", "PGPORT": "5432"}
    assert ib.postgres_environment(None) == {}
    assert ib.postgres_environment(str(tmp_path / "absent.conf")) == {}


def test_dump_success_records_digest(tmp_path):
    env = make_env(tmp_path)
    make_module(Path(env.core_addons), "sale")
    entry = ib.build_instance(make_spec(), env, fake_runner(), dump=True)
    assert entry["dump"]["file"] == "Demo.dump"
    assert len(entry["dump"]["sha256"]) == 64


def test_dump_failure_keeps_instance_and_is_reported(tmp_path):
    env = make_env(tmp_path)
    make_module(Path(env.core_addons), "sale")
    manifest = ib.build_all([make_spec()], env, fake_runner(dump_code=1), dump=True)
    assert len(manifest["instances"]) == 1
    assert "error" in manifest["instances"][0]["dump"]
    assert manifest["failures"][0]["name"] == "Demo"
