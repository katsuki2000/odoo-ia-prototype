"""
code_intelligence/data_constraints/runner.py

Subprocess-based Semgrep runner for Odoo Code Intelligence.
Executes Semgrep rules in --json mode and extracts structured findings
including exact file paths, line numbers, check_ids, and matching code lines.
"""

import os
import sys
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import logging

_logger = logging.getLogger(__name__)


@dataclass
class SemgrepMatch:
    filepath: str
    start_line: int
    end_line: int
    check_id: str
    message: str
    lines: str


def _find_semgrep_binary() -> str:
    """Locate semgrep binary in .venv or system PATH."""
    venv_semgrep = Path(sys.executable).parent / "semgrep"
    if venv_semgrep.exists():
        return str(venv_semgrep)
    candidate = Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "semgrep"
    if candidate.exists():
        return str(candidate)
    which_semgrep = shutil.which("semgrep")
    if which_semgrep:
        return which_semgrep
    return "semgrep"


def run_semgrep_analysis(
    target_path: Path,
    config_path: Path,
    semgrep_bin: Optional[str] = None,
) -> List[SemgrepMatch]:
    """
    Run Semgrep on target_path using config_path and return structured SemgrepMatch items.
    """
    if not target_path.exists():
        _logger.warning("Target path does not exist for Semgrep analysis: %s", target_path)
        return []

    if not config_path.exists():
        _logger.warning("Config path does not exist for Semgrep analysis: %s", config_path)
        return []

    binary = semgrep_bin or _find_semgrep_binary()

    cmd = [
        binary,
        "--config",
        str(config_path),
        "--json",
        str(target_path),
    ]

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if res.returncode not in (0, 1):
            _logger.error("Semgrep execution failed (code %d): %s", res.returncode, res.stderr)
            return []

        data = json.loads(res.stdout)
        results = data.get("results", [])

        matches: List[SemgrepMatch] = []
        for item in results:
            path = item.get("path", str(target_path))
            start_l = item.get("start", {}).get("line", 1)
            end_l = item.get("end", {}).get("line", start_l)
            check_id = item.get("check_id", "")
            extra = item.get("extra", {})
            message = extra.get("message", "")
            lines = extra.get("lines", "")

            # If Semgrep CLI returns 'requires login' or empty lines, slice from file on disk
            if not lines or "requires login" in lines.lower():
                try:
                    f_path = Path(path)
                    if f_path.exists():
                        file_lines = f_path.read_text(encoding="utf-8").splitlines()
                        lines = "\n".join(file_lines[max(0, start_l - 1):end_l])
                except Exception:
                    pass

            matches.append(
                SemgrepMatch(
                    filepath=path,
                    start_line=start_l,
                    end_line=end_l,
                    check_id=check_id,
                    message=message,
                    lines=lines.strip(),
                )
            )
        return matches

    except Exception as e:
        _logger.error("Error executing data_constraints.runner: %s", e)
        return []
