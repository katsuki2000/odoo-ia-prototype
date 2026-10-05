"""Hermetic tests for the instance runtime helpers."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.evaluation import instances as ib
from core.evaluation import instance_runtime as ir
from tests.eval_instance_helpers import make_env, make_module, make_spec


def test_provision_credentials_parses_marker_and_passes_users(tmp_path):
    env = make_env(tmp_path)
    make_module(Path(env.core_addons), "sale")
    payload = {"base.user_demo": {"uid": 6, "api_key": "k", "groups": [1]}}
    seen = []

    def runner(command, stdin=None, env=None):
        seen.append((list(command), stdin))
        return SimpleNamespace(returncode=0, stdout=ir.CREDENTIALS_MARKER + json.dumps(payload), stderr="")

    assert ir.provision_credentials(make_spec(), env, ["base.user_demo"], runner) == payload
    command, script = seen[0]
    assert command[2] == "shell" and "base.user_demo" in script and "_generate" in script
    compile(script, "credentials", "exec")


def test_free_port_is_usable():
    assert 1024 <= ir.free_port() <= 65535


class FakeProcess:
    def __init__(self, exited=False):
        self.exited = exited
        self.terminated = False

    def poll(self):
        return 1 if self.exited else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


def test_wait_until_ready_succeeds_when_server_answers():
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    ir.wait_until_ready("http://x", FakeProcess(), opener=lambda probe, timeout: Response(), sleep=lambda s: None)


def test_wait_until_ready_fails_when_process_exits_or_times_out():
    with pytest.raises(RuntimeError):
        ir.wait_until_ready("http://x", FakeProcess(exited=True), sleep=lambda s: None)

    def refuse(probe, timeout):
        raise OSError("refused")

    with pytest.raises(TimeoutError):
        ir.wait_until_ready("http://x", FakeProcess(), timeout=0.0, opener=refuse, sleep=lambda s: None)


def test_serve_instance_terminates_the_server(tmp_path):
    env = make_env(tmp_path)
    make_module(Path(env.core_addons), "sale")
    process = FakeProcess()
    commands = []

    def popen(command, **kwargs):
        commands.append(command)
        return process

    with ir.serve_instance(make_spec(), env, 8099, popen=popen, wait_ready=lambda url, proc: None) as url:
        assert url == "http://127.0.0.1:8099"
    assert process.terminated
    assert "--http-port=8099" in commands[0] and "--max-cron-threads=0" in commands[0]
    assert any(part.startswith("--logfile=") and len(part) > len("--logfile=") for part in commands[0])


def test_worker_environment_overrides_instance_settings(tmp_path):
    env = make_env(tmp_path)
    values = ir.worker_environment(make_spec(), env, "http://127.0.0.1:1", {"KEEP": "1"})
    assert values["KEEP"] == "1"
    assert values["ODOO_URL"] == "http://127.0.0.1:1"
    assert values["ODOO_DB"] == ib.database_name(make_spec(), env.db_prefix)
    assert values["GRAPH_CACHE_PATH"].endswith("graphs/Demo.json")
