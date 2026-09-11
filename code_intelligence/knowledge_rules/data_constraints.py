"""
code_intelligence/knowledge_rules/data_constraints.py

Semgrep-backed detection of _sql_constraints and relational domain=
declarations (Evidence tool 10/24). Regroupe (todo/contexte.txt, chantier
de reduction du nombre de sous-paquets de knowledge_rules/) les anciens
runner.py/analyzer.py de l'ex-paquet data_constraints/ en un seul module
plat, sans changement de logique. Les fixtures/regles Semgrep elles-memes
(donnees, pas du code Python importable) vivent desormais a cote, dans
knowledge_rules/data_constraints_semgrep_rules/ (deplace depuis l'ex
semgrep_rules/, seul consommateur).
"""

import ast
import os
import sys
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional
import logging

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence
from core.output import confidence_label
from code_intelligence.utils import format_file_link

_logger = logging.getLogger(__name__)

# === runner (ex data_constraints/runner.py) =================================

# Subprocess-based Semgrep runner for Odoo Code Intelligence.
# Executes Semgrep rules in --json mode and extracts structured findings
# including exact file paths, line numbers, check_ids, and matching code lines.


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
    candidate = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "semgrep"
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
        _logger.error("Error executing data_constraints runner: %s", e)
        return []


# === analyzer (ex data_constraints/analyzer.py) =============================


@dataclass
class DataConstraintsAnalysis:
    """Result of analyzing a model's source files for _sql_constraints and
    relational domain= declarations via Semgrep."""
    model_name: str
    matches: List[SemgrepMatch] = field(default_factory=list)
    summary_text: str = ""
    evidence: List[Evidence] = field(default_factory=list)


def _build_data_constraints_evidence(matches: List[SemgrepMatch]) -> List[Evidence]:
    """
    One Evidence per real SemgrepMatch, confidence=HIGH (static deterministic
    pattern match, consistent with the [Confiance: ÉLEVÉE] tag shown in
    summary_text, formatted via core.output -- section 629). check_id (e.g. odoo-sql-constraints-declaration vs
    odoo-relational-domain-declaration) already carries the SQL-constraint
    vs domain= distinction -- no separate classification is rebuilt here,
    per todo/contexte.txt section 463/464 decision.

    No negative Evidence for an empty match list -- see module docstring.
    """
    evidence: List[Evidence] = []
    for match in matches:
        claim = (
            f"File '{match.filepath}' has a {match.check_id} finding at "
            f"line {match.start_line}: {match.message}"
        )
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=claim,
            source=f"data_constraints:{match.filepath}:{match.check_id}:{match.start_line}",
            value=match.lines,
            confidence="HIGH",
            scope={"lineno": match.start_line, "end_lineno": match.end_line},
        ))
    return evidence


def _compose_data_constraints_summary(model_name: str, matches: List[SemgrepMatch]) -> str:
    """Build summary_text exactly as ci_agent_tools.py's previous inline
    implementation did -- text contract strictly unchanged."""
    if not matches:
        return (
            f"No _sql_constraints or relational domain= patterns detected for "
            f"model '{model_name}' [Confiance: {confidence_label('high')} -- static pattern match, "
            f"deterministic]."
        )

    lines = [
        f"Analyse des contraintes de données (Semgrep) pour '{model_name}' "
        f"[Confiance: {confidence_label('high')} -- correspondance de motif statique, déterministe]:"
    ]
    from code_intelligence.agent.ci_agent_node.context.tool_helpers import _is_custom_module_filepath
    def _constraint_priority(m: SemgrepMatch) -> tuple:
        is_custom = _is_custom_module_filepath(m.filepath)
        has_constrain = (
            "constrain" in m.check_id
            or "selection" in m.check_id
            or "exception" in m.check_id
            or "filter" in m.check_id
        )
        return (not is_custom, not has_constrain)

    sorted_matches = sorted(matches, key=_constraint_priority)
    for match in sorted_matches:
        link = format_file_link(match.filepath, match.start_line, match.end_line)
        lines.append(f"  - {link} ({match.check_id}): {match.message}")
        if match.lines:
            lines.append(f"    ```\n    {match.lines}\n    ```")

    return "\n".join(lines)


def _extract_static_exclusion_filters(filepath: Path) -> List[SemgrepMatch]:
    """Extract static exclusion dictionaries/lists/sets (blacklist, whitelist, exclude, etc.)
    defined at class or module level, returning them as structured SemgrepMatch objects."""
    matches: List[SemgrepMatch] = []
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content)
        source_lines = content.splitlines()
    except Exception:
        return []

    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.Module)):
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            name = target.id
                            name_lower = name.lower()
                            if any(k in name_lower for k in ("blacklist", "whitelist", "exclude", "excluded", "sensitive")):
                                try:
                                    evaluated_val = ast.literal_eval(stmt.value)
                                except Exception:
                                    try:
                                        evaluated_val = ast.unparse(stmt.value)
                                    except Exception:
                                        evaluated_val = "..."
                                start_l = stmt.lineno
                                end_l = getattr(stmt, "end_lineno", start_l)
                                code_slice = "\n".join(source_lines[start_l - 1 : end_l])
                                class_prefix = f"{node.name}." if isinstance(node, ast.ClassDef) else ""
                                matches.append(
                                    SemgrepMatch(
                                        filepath=str(filepath),
                                        start_line=start_l,
                                        end_line=end_l,
                                        check_id="odoo-static-exclusion-filter",
                                        message=f"Static exclusion filter '{class_prefix}{name}': {repr(evaluated_val)}",
                                        lines=code_slice,
                                    )
                                )
    return matches


def analyze_data_constraints_from_filepaths(
    model_name: str,
    filepaths: Iterable[str],
    config_dir: Optional[Path] = None,
) -> DataConstraintsAnalysis:
    """
    Run Semgrep across the given (already-resolved) filepaths and build both
    summary_text and Evidence in a single pass over the collected matches --
    no duplicated composition loop.

    config_dir defaults to knowledge_rules/data_constraints_semgrep_rules/
    (single parent hop -- this module is now a flat file directly inside
    knowledge_rules/, not nested one level deeper as data_constraints/ was).
    """
    if config_dir is None:
        config_dir = Path(__file__).resolve().parent / "data_constraints_semgrep_rules"

    all_matches: List[SemgrepMatch] = []
    for fp in sorted(filepaths):
        p = Path(fp)
        if not p.exists():
            continue
        all_matches.extend(run_semgrep_analysis(p, config_dir))
        all_matches.extend(_extract_static_exclusion_filters(p))

    return DataConstraintsAnalysis(
        model_name=model_name,
        matches=all_matches,
        summary_text=_compose_data_constraints_summary(model_name, all_matches),
        evidence=_build_data_constraints_evidence(all_matches),
    )


__all__ = [
    "SemgrepMatch",
    "run_semgrep_analysis",
    "DataConstraintsAnalysis",
    "analyze_data_constraints_from_filepaths",
]
