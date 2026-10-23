import subprocess
from pathlib import Path
from unittest.mock import patch

from code_intelligence.rules import data_constraints
from config import settings

RULES_DIR = Path(data_constraints.__file__).resolve().parent.parent / "semgrep_rules"
CONFIG = RULES_DIR / "sql_constraints.yaml"
TARGET = RULES_DIR / "sql_constraints.py"


def _run_with_captured_subprocess():
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout='{"results": []}', stderr="")
    with patch.object(data_constraints.subprocess, "run", return_value=completed) as run:
        data_constraints.run_semgrep_analysis(TARGET, CONFIG, semgrep_bin="semgrep")
    return run.call_args


def test_semgrep_runs_without_telemetry_or_version_check():
    command = _run_with_captured_subprocess().args[0]
    assert "--metrics=off" in command
    assert "--disable-version-check" in command


def test_semgrep_timeout_uses_the_configured_constant():
    assert _run_with_captured_subprocess().kwargs["timeout"] == settings.SEMGREP_TIMEOUT_SECONDS


def test_semgrep_timeout_leaves_room_for_a_loaded_machine():
    assert settings.SEMGREP_TIMEOUT_SECONDS >= 120
