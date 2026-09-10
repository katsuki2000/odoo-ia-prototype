import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from core.evidence import Evidence, EvidenceSourceType, make_evidence
from core.confidence_tags import confidence_label
from code_intelligence.data_constraints import runner
from code_intelligence.data_constraints.runner import SemgrepMatch
from code_intelligence.utils import format_file_link


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
    summary_text, formatted via core.confidence_tags -- section 629). check_id (e.g. odoo-sql-constraints-declaration vs
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
    from code_intelligence.ci_agent_node.agent_tools import _is_custom_module_filepath
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

    config_dir defaults to code_intelligence/semgrep_rules -- this module
    lives one level deeper (code_intelligence/data_constraints/), hence the
    extra parent hop versus the pre-move path.
    """
    if config_dir is None:
        config_dir = Path(__file__).resolve().parent.parent / "semgrep_rules"

    all_matches: List[SemgrepMatch] = []
    for fp in sorted(filepaths):
        p = Path(fp)
        if not p.exists():
            continue
        all_matches.extend(runner.run_semgrep_analysis(p, config_dir))
        all_matches.extend(_extract_static_exclusion_filters(p))

    return DataConstraintsAnalysis(
        model_name=model_name,
        matches=all_matches,
        summary_text=_compose_data_constraints_summary(model_name, all_matches),
        evidence=_build_data_constraints_evidence(all_matches),
    )
