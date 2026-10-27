import subprocess
from pathlib import Path
from unittest.mock import patch

from code_intelligence.rules import data_constraints
from config import settings

RULES_DIR = Path(data_constraints.__file__).resolve().parent.parent / "semgrep_rules"
CONFIG = RULES_DIR / "sql_constraints.yaml"
TARGET = RULES_DIR / "sql_constraints.py"


def _run_with_captured_subprocess(targets=(TARGET,)):
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout='{"results": []}', stderr="")
    with patch.object(data_constraints.subprocess, "run", return_value=completed) as run:
        data_constraints.run_semgrep_analysis(list(targets), CONFIG, semgrep_bin="semgrep")
    return run


def test_semgrep_runs_without_telemetry_or_version_check():
    command = _run_with_captured_subprocess().call_args.args[0]
    assert "--metrics=off" in command
    assert "--disable-version-check" in command


def test_semgrep_timeout_uses_the_configured_constant():
    assert _run_with_captured_subprocess().call_args.kwargs["timeout"] == settings.SEMGREP_TIMEOUT_SECONDS


def test_semgrep_timeout_leaves_room_for_a_loaded_machine():
    assert settings.SEMGREP_TIMEOUT_SECONDS >= 120


def test_several_files_share_one_semgrep_process():
    other = RULES_DIR / "domain_relational.py"
    run = _run_with_captured_subprocess([TARGET, other])
    assert run.call_count == 1
    command = run.call_args.args[0]
    assert str(TARGET) in command and str(other) in command


def test_no_file_starts_no_semgrep_process():
    with patch.object(data_constraints.subprocess, "run") as run:
        assert data_constraints.run_semgrep_analysis([], CONFIG, semgrep_bin="semgrep") == []
    run.assert_not_called()
