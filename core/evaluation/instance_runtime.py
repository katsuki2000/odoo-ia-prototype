"""Credentials, server and worker environment for running the system on one evaluation instance."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from typing import Callable, Mapping, Optional, Sequence
from urllib import request
from urllib.error import URLError

from core.evaluation import instances as ib

CREDENTIALS_MARKER = "EVAL_CREDENTIALS:"
KEY_NAME = "eval_protocol"
READY_PATH = "/web/webclient/version_info"
CREDENTIALS_BODY = """
credentials = {}
for xmlid in params['users']:
    user = env.ref(xmlid)
    key = env['res.users.apikeys'].with_user(user)._generate(None, params['key_name'])
    credentials[xmlid] = {'uid': user.id, 'api_key': key, 'groups': user.groups_id.ids}
env.cr.commit()
print('__MARKER__' + json.dumps(credentials))
"""


def provision_credentials(
    spec: ib.InstanceSpec,
    env: ib.BuildEnvironment,
    users: Sequence[str],
    runner: ib.Runner = ib.run_command,
) -> dict:
    roots = list(ib.resolve_addon_roots(spec, env).values())
    script = ib.build_shell_script({"users": list(users), "key_name": KEY_NAME}, CREDENTIALS_BODY, CREDENTIALS_MARKER)
    result = ib.require_success(
        runner(ib.inspect_command(env, roots, ib.database_name(spec, env.db_prefix)), script),
        f"credentials {spec.name}",
        env.output_dir / "logs" / f"{spec.name}_credentials.log",
    )
    return ib.parse_marked_json(result.stdout, CREDENTIALS_MARKER)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_until_ready(
    base_url: str,
    process,
    timeout: float = 180.0,
    interval: float = 1.0,
    opener: Callable = request.urlopen,
    sleep: Callable = time.sleep,
) -> None:
    deadline = time.monotonic() + timeout
    payload = json.dumps({"jsonrpc": "2.0", "method": "call", "params": {}}).encode("utf-8")
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("odoo server exited before becoming ready")
        probe = request.Request(base_url + READY_PATH, data=payload, headers={"Content-Type": "application/json"})
        try:
            with opener(probe, timeout=5) as response:
                if response.status == 200:
                    return
        except (URLError, OSError):
            pass
        sleep(interval)
    raise TimeoutError(f"odoo server not ready after {timeout} seconds")


@contextmanager
def serve_instance(
    spec: ib.InstanceSpec,
    env: ib.BuildEnvironment,
    port: int,
    popen: Callable = subprocess.Popen,
    wait_ready: Callable = wait_until_ready,
):
    roots = list(ib.resolve_addon_roots(spec, env).values())
    log = env.output_dir / "logs" / f"{spec.name}_server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    command = ib.odoo_command(env, roots) + [
        "-d", ib.database_name(spec, env.db_prefix),
        f"--http-port={port}", "--workers=0", "--max-cron-threads=0", f"--logfile={log}",
    ]
    process = popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base_url = f"http://127.0.0.1:{port}"
    try:
        wait_ready(base_url, process)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()


def worker_environment(
    spec: ib.InstanceSpec,
    env: ib.BuildEnvironment,
    base_url: str,
    base_env: Optional[Mapping[str, str]] = None,
) -> dict:
    return {
        **(os.environ if base_env is None else base_env),
        "ODOO_URL": base_url,
        "ODOO_DB": ib.database_name(spec, env.db_prefix),
        "GRAPH_CACHE_PATH": str(env.output_dir / "graphs" / f"{spec.name}.json"),
    }
