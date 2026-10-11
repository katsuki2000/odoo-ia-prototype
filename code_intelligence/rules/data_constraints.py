"""
code_intelligence/knowledge_rules/data_constraints.py

Semgrep-backed detection of _sql_constraints and relational domain=
declarations (Evidence tool 10/24). Regroupe (todo/contexte.txt, chantier
de reduction du nombre de sous-paquets de knowledge_rules/) les anciens
runner.py/analyzer.py de l'ex-paquet data_constraints/ en un seul module
plat, sans changement de logique. Les fixtures/regles Semgrep elles-memes
(donnees, pas du code Python importable) vivent dans code_intelligence/
semgrep_rules/ (dossier plat frere depuis l'aplatissement Option C,
seul consommateur).
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
import re
import textwrap

from core.evidence.evidence import Evidence, EvidenceSourceType, make_evidence
from core.output import confidence_label
from code_intelligence.utils import format_file_link, _TRUNCATION_MARKER

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
    owner_models: tuple = ()


SEMGREP_TIMEOUT_SECONDS = int(os.getenv("SEMGREP_TIMEOUT_SECONDS", "120"))


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
        raise FileNotFoundError(f"Semgrep target path does not exist: {target_path}")

    if not config_path.exists():
        raise FileNotFoundError(f"Semgrep configuration path does not exist: {config_path}")

    binary = semgrep_bin or _find_semgrep_binary()

    cmd = [
        binary,
        "--metrics=off",
        "--disable-version-check",
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
            timeout=SEMGREP_TIMEOUT_SECONDS,
        )
        if res.returncode not in (0, 1):
            raise RuntimeError(f"Semgrep failed with exit code {res.returncode}: {res.stderr.strip()}")

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
        raise RuntimeError(f"Semgrep analysis failed for '{target_path}': {e}") from e


def _string_constants(node: ast.AST) -> List[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [
            item.value
            for item in node.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
    return []


def _declared_model(class_node: ast.ClassDef) -> Optional[str]:
    declared = {}
    for stmt in class_node.body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if isinstance(target, ast.Name) and target.id in ("_name", "_inherit"):
            declared[target.id] = _string_constants(stmt.value)
    if declared.get("_name"):
        return declared["_name"][0]
    if declared.get("_inherit"):
        return declared["_inherit"][0]
    return None


def _model_spans(filepath: str) -> List[tuple]:
    try:
        tree = ast.parse(Path(filepath).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            model = _declared_model(node)
            if model:
                spans.append((node.lineno, node.end_lineno or node.lineno, model))
    return spans


def _annotate_owner_models(matches: List[SemgrepMatch]) -> None:
    """Semgrep runs per file, and one Odoo file often holds several models:
    tag every match with the model of its innermost enclosing class."""
    spans_by_file: dict = {}
    for match in matches:
        if match.filepath not in spans_by_file:
            spans_by_file[match.filepath] = _model_spans(match.filepath)
        enclosing = [
            span
            for span in spans_by_file[match.filepath]
            if span[0] <= match.start_line <= span[1]
        ]
        if enclosing:
            match.owner_models = (min(enclosing, key=lambda s: s[1] - s[0])[2],)


# === analyzer (ex data_constraints/analyzer.py) =============================


@dataclass
class DataConstraintsAnalysis:
    """Result of analyzing a model's source files for _sql_constraints and
    relational domain= declarations via Semgrep."""
    model_name: str
    matches: List[SemgrepMatch] = field(default_factory=list)
    summary_text: str = ""
    evidence: List[Evidence] = field(default_factory=list)
    analysis_errors: List[str] = field(default_factory=list)


def _strip_outer_parentheses(expression: str) -> str:
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        depth = 0
        balanced = True
        for index, char in enumerate(expression):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(expression) - 1:
                    balanced = False
                    break
        if not balanced or depth != 0:
            break
        expression = expression[1:-1].strip()
    return expression


def _split_top_level_or(expression: str) -> Optional[tuple[str, str]]:
    depth = 0
    quote = None
    index = 0
    while index < len(expression) - 1:
        char = expression[index]
        if quote:
            if char == quote:
                if index + 1 < len(expression) and expression[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and expression[index:index + 2].upper() == "OR":
            before = expression[index - 1] if index else " "
            after = expression[index + 2] if index + 2 < len(expression) else " "
            if before.isspace() and after.isspace():
                return expression[:index].strip(), expression[index + 2:].strip()
        index += 1
    return None


def _negate_sql_predicate(predicate: str) -> str:
    """Return the common SQL negation needed to explain a CHECK guard."""
    normalized = predicate.strip()
    upper = normalized.upper()
    if upper.endswith(" IS NOT NULL"):
        return normalized[: -len(" IS NOT NULL")] + " IS NULL"
    if upper.endswith(" IS NULL"):
        return normalized[: -len(" IS NULL")] + " IS NOT NULL"
    return f"NOT ({normalized})"


def _extract_check_expressions(sql_text: str) -> List[str]:
    marker = "CHECK("
    upper_text = sql_text.upper()
    expressions: List[str] = []
    search_start = 0
    while True:
        start = upper_text.find(marker, search_start)
        if start < 0:
            return expressions
        expression_start = start + len(marker)
        depth = 1
        quote = None
        for index in range(expression_start, len(sql_text)):
            char = sql_text[index]
            if quote:
                if char == quote:
                    if index + 1 < len(sql_text) and sql_text[index + 1] == quote:
                        continue
                    quote = None
                continue
            if char in "'\"":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    expressions.append(sql_text[expression_start:index].strip())
                    search_start = index + 1
                    break
        else:
            return expressions


def _extract_check_expression(sql_text: str) -> Optional[str]:
    expressions = _extract_check_expressions(sql_text)
    return expressions[0] if expressions else None


def _conditional_check_fact(expression: str) -> Optional[str]:
    parts = _split_top_level_or(expression)
    if not parts:
        return None
    guard, required_condition = (_strip_outer_parentheses(part) for part in parts)
    guard_false = _negate_sql_predicate(guard)
    return (
        "[CHECK LOGIC] Exact branch mapping: this SQL CHECK is satisfied when "
        f"either `{guard}` is true, or `{required_condition}` is true. "
        f"Therefore, when `{guard_false}` (that is, `{guard}` is false), "
        f"`{required_condition}` must be true. Do not swap these branches."
    )


def _conditional_check_facts(match: SemgrepMatch) -> List[str]:
    if "sql-constraints" not in match.check_id:
        return []
    return [
        fact
        for expression in _extract_check_expressions(match.lines)
        if (fact := _conditional_check_fact(expression)) is not None
    ]


def _match_source_tree(match: SemgrepMatch) -> Optional[ast.AST]:
    candidates = []
    try:
        file_lines = Path(match.filepath).read_text(encoding="utf-8").splitlines()
        candidates.append("\n".join(file_lines[match.start_line - 1:match.end_line]))
    except (OSError, UnicodeDecodeError):
        pass
    first, _, rest = match.lines.partition("\n")
    candidates.append(first + "\n" + textwrap.dedent(rest))
    for source in candidates:
        try:
            return ast.parse(textwrap.dedent(source))
        except SyntaxError:
            continue
    return None


def _numeric_literal(node: ast.AST) -> Optional[float]:
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _chained_bounds(compare: ast.Compare) -> Optional[dict]:
    if len(compare.ops) != 2:
        return None
    first, second = compare.ops
    ascending = isinstance(first, (ast.Lt, ast.LtE)) and isinstance(second, (ast.Lt, ast.LtE))
    descending = isinstance(first, (ast.Gt, ast.GtE)) and isinstance(second, (ast.Gt, ast.GtE))
    if not (ascending or descending):
        return None
    outer_a, subject, outer_b = compare.left, compare.comparators[0], compare.comparators[1]
    if _numeric_literal(outer_a) is None or _numeric_literal(outer_b) is None:
        return None
    if ascending:
        low, low_op, high, high_op = outer_a, first, outer_b, second
    else:
        low, low_op, high, high_op = outer_b, second, outer_a, first
    return {
        "subject": ast.unparse(subject),
        "low": ast.unparse(low),
        "high": ast.unparse(high),
        "low_included": isinstance(low_op, (ast.LtE, ast.GtE)),
        "high_included": isinstance(high_op, (ast.LtE, ast.GtE)),
        "chain": ast.unparse(compare),
    }


def _bounds_fact(test: ast.expr) -> Optional[str]:
    operands = test.values if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And) else [test]
    for operand in operands:
        negated = isinstance(operand, ast.UnaryOp) and isinstance(operand.op, ast.Not)
        inner = operand.operand if negated else operand
        if not isinstance(inner, ast.Compare):
            continue
        bounds = _chained_bounds(inner)
        if bounds is None:
            continue
        others = [ast.unparse(o) for o in operands if o is not operand]
        scope = f" This check applies only when `{' and '.join(others)}`." if others else ""
        low_state = "included" if bounds["low_included"] else "excluded"
        high_state = "included" if bounds["high_included"] else "excluded"
        if negated:
            return (
                f"[BOUNDS LOGIC] `{bounds['subject']}` is accepted only when `{bounds['chain']}`: "
                f"the lower bound {bounds['low']} is {low_state} and the upper bound "
                f"{bounds['high']} is {high_state}. Any value outside this range raises "
                f"the error. Do not widen or round these bounds.{scope}"
            )
        return (
            f"[BOUNDS LOGIC] The error is raised when `{bounds['chain']}` holds: "
            f"the lower bound {bounds['low']} is {low_state} and the upper bound "
            f"{bounds['high']} is {high_state} within the rejected range.{scope}"
        )
    return None


def _bounds_facts(match: SemgrepMatch) -> List[str]:
    if "constrains" not in match.check_id:
        return []
    tree = _match_source_tree(match)
    if tree is None:
        return []
    facts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and any(isinstance(s, ast.Raise) for s in node.body):
            fact = _bounds_fact(node.test)
            if fact:
                facts.append(fact)
    return facts


_BOUNDS_FACT_PATTERN = re.compile(
    r"\[BOUNDS LOGIC\] `(?P<subject>[^`]+)` is accepted only when `(?P<chain>[^`]+)`: "
    r"the lower bound (?P<low>\S+) is (?P<low_state>included|excluded) and the upper bound "
    r"(?P<high>\S+) is (?P<high_state>included|excluded)"
)


def backfill_missing_bounds_facts(
    final_answer: str,
    scoped_tool_output: str,
    question: str = "",
) -> str:
    """Append the exact numeric bounds of a Python range constraint whose
    excluded bound the synthesis did not signal."""
    if question and not re.search(
        r"\b(?:contrainte|constrain|valid|borne|pourcentage|intervalle|plage)",
        question,
        flags=re.IGNORECASE,
    ):
        return final_answer
    signals_exclusion = re.search(r"exclu|strict", final_answer, flags=re.IGNORECASE) is not None
    missing = []
    for found in _BOUNDS_FACT_PATTERN.finditer(scoped_tool_output):
        has_excluded = "excluded" in (found["low_state"], found["high_state"])
        if has_excluded and not signals_exclusion:
            missing.append(
                f"Selon le code, `{found['subject']}` doit satisfaire `{found['chain']}` "
                f"(borne basse {found['low']} {'exclue' if found['low_state'] == 'excluded' else 'incluse'}, "
                f"borne haute {found['high']} {'exclue' if found['high_state'] == 'excluded' else 'incluse'})."
            )
    if not missing:
        return final_answer
    return final_answer.rstrip() + "\n\nPrécision issue du code :\n- " + "\n- ".join(dict.fromkeys(missing))


def enforce_sql_constraint_fidelity(
    final_answer: str,
    constraint_observation: str,
    question: str = "",
) -> str:
    """Prefer the actual constraint evidence when synthesis omits its declarations."""
    if not re.search(
        r"\b(?:sql|contraintes?|constraints?|check|unicité|unique)\b",
        question,
        flags=re.IGNORECASE,
    ):
        return final_answer
    if "odoo-sql-constraints-declaration" not in constraint_observation:
        return final_answer

    names = list(dict.fromkeys(re.findall(
        r"""['"]([A-Za-z][A-Za-z0-9_]*)['"]\s*,\s*['"]\s*(?:CHECK|UNIQUE|FOREIGN\s+KEY|EXCLUDE)\b""",
        constraint_observation,
        flags=re.IGNORECASE,
    )))
    if not names or all(name.lower() in final_answer.lower() for name in names):
        return final_answer

    _logger.warning(
        "SQL constraint synthesis omitted declarations %s; returning source evidence instead.",
        [name for name in names if name.lower() not in final_answer.lower()],
    )
    if _TRUNCATION_MARKER in constraint_observation:
        preface = (
            "La synthèse ne reprend pas fidèlement les contraintes SQL extraites. "
            "L'observation étant tronquée, cet extrait ne garantit pas l'exhaustivité :"
        )
    else:
        preface = (
            "La synthèse ne reprend pas fidèlement les contraintes SQL extraites. "
            "Voici la preuve source, sans ajouter de règle non observée :"
        )
    return f"{preface}\n\n{constraint_observation.strip()}"


_SQL_KEYWORDS = frozenset({"is", "null", "and", "or", "not", "true", "false"})


def _sql_identifiers(expression: str) -> set:
    return set(re.findall(r"\b[a-z][a-z0-9_]*\b", expression.lower())) - _SQL_KEYWORDS


def _drop_paraphrased_check_blocks(answer: str, branches: List[tuple]) -> str:
    """Remove prose blocks that paraphrase a CHECK by naming its guard column
    together with the guarded columns: the exact predicates replace them, so
    the answer never carries an inverted paraphrase next to the correct one."""
    guard_columns = set().union(*(_sql_identifiers(guard) for guard, _ in branches))
    guarded_columns = set().union(*(_sql_identifiers(cond) for _, cond in branches))
    kept = []
    for block in re.split(r"\n\s*\n", answer):
        tokens = set(re.findall(r"\b[a-z][a-z0-9_]*\b", block.lower()))
        paraphrase = (
            not block.lstrip().startswith("#")
            and tokens & guard_columns
            and tokens & (guarded_columns - guard_columns)
        )
        if not paraphrase:
            kept.append(block)
    return "\n\n".join(kept)


def backfill_missing_conditional_check_facts(
    final_answer: str,
    scoped_tool_output: str,
    question: str = "",
) -> str:
    """Append SQL CHECK branches whose distinctive fields were omitted."""
    if question and not re.search(
        r"\b(?:sql|check|pr[eé]dicat|branche(?:s)?|condition exacte)\b",
        question,
        flags=re.IGNORECASE,
    ):
        return final_answer
    facts = re.findall(
        r"\[CHECK LOGIC\].*?when `([^`]+)`.*?`([^`]+)` must be true",
        scoped_tool_output,
        flags=re.DOTALL,
    )
    if not facts:
        facts = []
        for expression in _extract_check_expressions(scoped_tool_output):
            fact = _conditional_check_fact(expression)
            if fact:
                match = re.search(
                    r"when `([^`]+)`.*?`([^`]+)` must be true",
                    fact,
                    flags=re.DOTALL,
                )
                if match:
                    facts.append(match.groups())
    answer_tokens = set(re.findall(r"\b[a-z][a-z0-9_]*\b", final_answer.lower()))
    missing_facts = []
    missing_branches = []
    for guard_false, condition in facts:
        fields = _sql_identifiers(condition)
        if fields and (not fields.issubset(answer_tokens) or condition not in final_answer):
            missing_branches.append((guard_false, condition))
            missing_facts.append(
                f"Selon la preuve SQL, lorsque `{guard_false}`, "
                f"la condition `{condition}` doit être vraie."
            )
    if not missing_facts:
        return final_answer
    final_answer = _drop_paraphrased_check_blocks(final_answer, missing_branches)
    clarification = ""
    if len(missing_facts) > 1:
        clarification = (
            "\n- Les branches sont indépendantes : ne pas appliquer les champs "
            "ou opérateurs d'une branche à l'autre. Les prédicats SQL exacts "
            "ci-dessus prévalent sur toute paraphrase générale."
        )
    return (
        final_answer.rstrip()
        + "\n\nPrécision issue de la preuve SQL :\n- "
        + "\n- ".join(missing_facts)
        + clarification
    )


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


def _compose_data_constraints_summary(
    model_name: str,
    matches: List[SemgrepMatch],
    analysis_errors: Optional[List[str]] = None,
) -> str:
    """Render findings without treating a failed scan as a negative result."""
    analysis_errors = analysis_errors or []
    if not matches and analysis_errors:
        return (
            f"Data-constraint analysis for '{model_name}' is incomplete. "
            "No conclusion about the absence of _sql_constraints or relational "
            f"domain patterns is possible. Errors: {'; '.join(analysis_errors)}"
        )
    if not matches:
        return (
            f"No _sql_constraints or relational domain= patterns detected for "
            f"model '{model_name}' [Confiance: {confidence_label('high')} -- static pattern match, "
            f"deterministic]."
        )

    lines = [
        f"Analyse des contraintes de données pour '{model_name}' "
        f"[Confiance: {confidence_label('high')} -- correspondance de motif statique, déterministe]:"
    ]
    if analysis_errors:
        lines.append(
            "WARNING: This analysis is incomplete; some Semgrep scans failed. "
            "The findings below do not establish that other constraints are absent. "
            f"Errors: {'; '.join(analysis_errors)}"
        )
    from code_intelligence.agent.tool_helpers import _is_custom_module_filepath
    def _constraint_priority(m: SemgrepMatch) -> tuple:
        is_custom = _is_custom_module_filepath(m.filepath)
        has_constrain = (
            "constrain" in m.check_id
            or "selection" in m.check_id
            or "exception" in m.check_id
            or "filter" in m.check_id
            # "unique" couvre odoo-raw-sql-unique-index /
            # odoo-create-unique-index-helper (todo/contexte.txt section
            # 812) : le mecanisme SQL brut le plus souvent recherche par
            # les questions d'unicite doit sortir en tete, pas se noyer
            # en fin d'un long document et risquer la troncature (budget
            # cumulatif MAX_TOTAL_OBSERVATION_CHARS, section 811).
            or "unique" in m.check_id
        )
        return (not is_custom, not has_constrain)

    sorted_matches = sorted(matches, key=_constraint_priority)
    for match in sorted_matches:
        link = format_file_link(match.filepath, match.start_line, match.end_line)
        owner = f" [model: {', '.join(match.owner_models)}]" if match.owner_models else ""
        lines.append(f"  - {link} ({match.check_id}){owner}: {match.message}")
        if match.lines:
            lines.append(f"    ```\n    {match.lines}\n    ```")
        lines.extend(f"    {fact}" for fact in _conditional_check_facts(match))
        lines.extend(f"    {fact}" for fact in _bounds_facts(match))

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

    config_dir defaults to code_intelligence/semgrep_rules/ (sibling flat
    folder, single parent hop from this file's own package dir).
    """
    if config_dir is None:
        config_dir = Path(__file__).resolve().parent.parent / "semgrep_rules"

    all_matches: List[SemgrepMatch] = []
    analysis_errors: List[str] = []
    for fp in sorted(filepaths):
        p = Path(fp)
        if not p.exists():
            analysis_errors.append(f"Source file is unavailable: {fp}")
            continue
        try:
            all_matches.extend(run_semgrep_analysis(p, config_dir))
        except (OSError, RuntimeError, ValueError) as error:
            analysis_errors.append(str(error))
        all_matches.extend(_extract_static_exclusion_filters(p))

    _annotate_owner_models(all_matches)
    return DataConstraintsAnalysis(
        model_name=model_name,
        matches=all_matches,
        summary_text=_compose_data_constraints_summary(
            model_name, all_matches, analysis_errors,
        ),
        evidence=_build_data_constraints_evidence(all_matches),
        analysis_errors=analysis_errors,
    )


__all__ = [
    "SemgrepMatch",
    "run_semgrep_analysis",
    "DataConstraintsAnalysis",
    "analyze_data_constraints_from_filepaths",
]
