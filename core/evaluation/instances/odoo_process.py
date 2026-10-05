"""Odoo command lines, subprocess execution and shell output parsing."""

from __future__ import annotations

import configparser
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Sequence

from core.evaluation.instances.environment import BuildEnvironment
from core.evaluation.instances.spec import InstanceSpec

INSPECTION_MARKER = "INSTANCE_INSPECTION:"
INSPECTION_SCRIPT = (
    "import json\n"
    "from odoo import release\n"
    "rows = env['ir.module.module'].search_read("
    "[('state', '!=', 'uninstalled')], ['name', 'installed_version', 'state'])\n"
    "languages = env['res.lang'].search([('active', '=', True)]).mapped('code')\n"
    f"print('{INSPECTION_MARKER}' + json.dumps("
    "{'modules': rows, 'languages': languages, 'version': release.version}))\n"
)
ERROR_TAIL_CHARS = 500
ERROR_LINES_KEPT = 3
ODOO_ERROR_LINE = re.compile(r"\b(?:ERROR|CRITICAL)\b \S+ odoo\.")
PG_CONF_KEYS = {"db_host": "PGHOST", "db_port": "PGPORT", "db_user": "PGUSER", "db_password": "PGPASSWORD"}

Runner = Callable[..., subprocess.CompletedProcess]


def run_command(
    command: Sequence[str], stdin: Optional[str] = None, env: Optional[Mapping[str, str]] = None,
) -> subprocess.CompletedProcess:
    merged = {**os.environ, **env} if env else None
    return subprocess.run(command, input=stdin, capture_output=True, text=True, check=False, env=merged)


def postgres_environment(conf_path: Optional[str]) -> dict:
    if not conf_path or not Path(conf_path).is_file():
        return {}
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(conf_path, encoding="utf-8")
    options = parser["options"] if parser.has_section("options") else {}
    return {
        variable: options[key]
        for key, variable in PG_CONF_KEYS.items()
        if options.get(key) not in (None, "", "False")
    }


def require_success(
    result: subprocess.CompletedProcess, action: str, log_path: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    if result.returncode == 0:
        return result
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    lines = [line.strip() for line in output.splitlines() if ODOO_ERROR_LINE.search(line)][-ERROR_LINES_KEPT:]
    detail = " | ".join(lines) or output[-ERROR_TAIL_CHARS:]
    message = f"{action} failed (exit {result.returncode}): {detail}"
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output, encoding="utf-8")
        message += f" [log: {log_path}]"
    raise RuntimeError(message)


def odoo_command(env: BuildEnvironment, roots: Iterable[Path], subcommand: Optional[str] = None) -> list:
    command = [env.odoo_python, env.odoo_bin]
    if subcommand:
        command.append(subcommand)
    if env.odoo_conf:
        command += ["-c", env.odoo_conf]
    command += ["--logfile=", f"--addons-path={','.join(str(root) for root in roots)}"]
    return command


def install_command(spec: InstanceSpec, env: BuildEnvironment, roots: Iterable[Path], database: str) -> list:
    command = odoo_command(env, roots) + [
        "-d", database,
        "-i", ",".join(spec.modules),
        f"--load-language={spec.language}",
        "--no-http",
        "--stop-after-init",
    ]
    if not spec.with_demo:
        command.append("--without-demo=all")
    return command


def inspect_command(env: BuildEnvironment, roots: Iterable[Path], database: str) -> list:
    return odoo_command(env, roots, "shell") + ["-d", database, "--no-http"]


def build_shell_script(params: Mapping, body: str, marker: str) -> str:
    header = f"import json\nparams = json.loads({json.dumps(json.dumps(params))})\n"
    return header + body.replace("__MARKER__", marker)


def parse_marked_json(output: str, marker: str) -> dict:
    for line in output.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker):])
    raise RuntimeError(f"{marker} output missing")


def parse_inspection(output: str) -> dict:
    return parse_marked_json(output, INSPECTION_MARKER)
