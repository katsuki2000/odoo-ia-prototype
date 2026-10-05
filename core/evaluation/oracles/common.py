"""Shared building blocks of the oracle-based case generators."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Mapping, Sequence

from core.evaluation import instances as ib

DEFAULT_COMPANY = "base.main_company"
DEFAULT_USER = "base.user_admin"


def run_oracle(
    spec: ib.InstanceSpec,
    env: ib.BuildEnvironment,
    runner: ib.Runner,
    kind: str,
    body: str,
    marker: str,
    params: Mapping,
) -> list:
    roots = list(ib.resolve_addon_roots(spec, env).values())
    command = ib.inspect_command(env, roots, ib.database_name(spec, env.db_prefix))
    result = ib.require_success(
        runner(command, ib.build_shell_script(params, body, marker)),
        f"{kind} oracle {spec.name}",
        env.output_dir / "logs" / f"{spec.name}_{kind}_oracle.log",
    )
    return ib.parse_marked_json(result.stdout, marker)


def language_phrases(table: Mapping, language: str) -> Mapping:
    prefix = language.split("_")[0]
    if prefix not in table:
        raise ValueError(f"no question phrasing for language '{language}'")
    return table[prefix]


def slug(*parts: str) -> str:
    folded = unicodedata.normalize("NFKD", " ".join(parts)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", folded.lower()).strip("_")


def write_draft(cases: Sequence[Mapping], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(cases), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
