"""
code_intelligence/server_action_analyzer.py

Story S2.4: Static analysis of ir.actions.server 'code' fields.
Detects security-relevant patterns:
  - sudo() calls (privilege escalation)
  - has_group() checks (group-based conditional logic)
  - Hardcoded ID lists (partner/user IDs, bypasses)
  - eval/exec/getattr (dynamic dispatch, high uncertainty)

All results are tagged with confidence='low' because server action code
is data-driven (not traditional Python source) and may be modified at runtime.
"""

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

import logging

_logger = logging.getLogger(__name__)


@dataclass
class ServerActionCodeAnalysis:
    """Result of analyzing an ir.actions.server code field."""
    action_xml_id: str
    has_sudo: bool = False
    has_hardcoded_ids: bool = False
    hardcoded_id_lists: List[List[int]] = field(default_factory=list)
    has_group_checks: List[str] = field(default_factory=list)
    has_dynamic_dispatch: bool = False
    dynamic_dispatch_patterns: List[str] = field(default_factory=list)
    security_warnings: List[str] = field(default_factory=list)
    confidence: str = "low"
    summary_text: str = ""

    # J8 -- bounded LLM interpretation layer, kept as SEPARATE fields from
    # the static `confidence` above. Never merge or overwrite the static
    # value: an LLM misjudging risk (e.g. reporting "high" confidence on
    # code it actually misunderstood) must never silently replace or hide
    # the conservative static safety net. None means the LLM pass was
    # skipped (no warnings to interpret) or failed/was rejected.
    llm_summary: Optional[str] = None
    llm_confidence: Optional[str] = None

    # Bloc 9 gap (2026-08-10, module 6/8, custom_automation_traps / Q5.1):
    # sudo()/hardcoded-ID detection previously reported flat, unlinked
    # facts with no record of the enclosing `if` condition that actually
    # scopes them -- same "extraction loses the guard" class of bug already
    # fixed once in semgrep_locks_analyzer.py (module 1/8's super() capture,
    # module 5/8's exception_conditions), a third location this time. On
    # the real ground truth (`FOURNISSEURS_PRIVILEGIES = [42, 108, 231];
    # if rec.move_type == 'in_refund' and rec.partner_id.id in
    # FOURNISSEURS_PRIVILEGIES: rec.sudo().action_post()`), the tool could
    # say "sudo() detected" and "hardcoded IDs detected" but never state
    # that the bypass is conditional at all, let alone on WHAT -- exactly
    # the fact Q5.1 needs ("est-ce que TOUS les avoirs suivent les mêmes
    # règles ?" -> NON, only in_refund moves from those 3 partners).
    trigger_conditions: List[str] = field(default_factory=list)


# Regex patterns for security-relevant code constructs
_SUDO_PATTERN = re.compile(r"\.sudo\s*\(")
_HAS_GROUP_PATTERN = re.compile(r"\.has_group\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
_HARDCODED_ID_LIST_PATTERN = re.compile(
    r"\b[A-Z_]+\s*=\s*\[(\s*\d+(?:\s*,\s*\d+)*\s*)\]"
)
_GETATTR_PATTERN = re.compile(r"\bgetattr\s*\(")
_EVAL_PATTERN = re.compile(r"\beval\s*\(")
_EXEC_PATTERN = re.compile(r"\bexec\s*\(")
_IF_LINE_PATTERN = re.compile(r"^if\s+(.+):\s*$")


def _line_number_of(code: str, char_offset: int) -> int:
    """1-indexed line number containing char_offset in code."""
    return code.count("\n", 0, char_offset) + 1


def _find_enclosing_if_condition(code_lines: List[str], line_no: int) -> Optional[str]:
    """
    Best-effort, indentation-based scan backward from line_no (1-indexed)
    for the nearest enclosing `if ...:` statement whose body contains this
    line. Deliberately NOT a full AST parse (unlike semgrep_locks_analyzer's
    guard-capturing visitors, which operate on real Python module source) --
    ir.actions.server `code` is a free-text data field that may be partial
    or unusual, and this whole file's design already accepts regex-level,
    'low confidence' analysis over full parsing (see module docstring).
    Fails safe: returns None (scoping caveat simply omitted, never a wrong
    one shown) if indentation doesn't resolve cleanly or no enclosing `if`
    is found before reaching column 0.
    """
    if line_no - 1 >= len(code_lines) or line_no - 1 < 0:
        return None
    target_indent = len(code_lines[line_no - 1]) - len(code_lines[line_no - 1].lstrip())
    for i in range(line_no - 2, -1, -1):
        line = code_lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent < target_indent:
            match = _IF_LINE_PATTERN.match(stripped)
            if match:
                return match.group(1).strip()
            target_indent = indent
            if indent == 0:
                return None
    return None


def analyze_server_action_code(
    code: str,
    action_xml_id: str,
) -> ServerActionCodeAnalysis:
    """
    Analyze an ir.actions.server code field for security-relevant patterns.

    Returns a ServerActionCodeAnalysis with detected patterns, warnings,
    and a human-readable summary. Confidence is always 'low' because
    server action code is data-driven and can be modified at runtime.
    """
    result = ServerActionCodeAnalysis(action_xml_id=action_xml_id)

    if not code or not code.strip():
        result.summary_text = f"Action '{action_xml_id}': No code to analyze."
        return result

    code_lines = code.splitlines()

    # 1. Detect sudo() calls
    sudo_matches = list(_SUDO_PATTERN.finditer(code))
    if sudo_matches:
        result.has_sudo = True
        # Capture enclosing if-conditions for each sudo() occurrence
        for m in sudo_matches:
            line_no = _line_number_of(code, m.start())
            cond = _find_enclosing_if_condition(code_lines, line_no)
            if cond and cond not in result.trigger_conditions:
                result.trigger_conditions.append(cond)
        cond_clause = ""
        if result.trigger_conditions:
            cond_clause = (
                f" Conditionné par: {'; '.join(result.trigger_conditions)}."
            )
        result.security_warnings.append(
            f" SUDO: L'action '{action_xml_id}' utilise sudo() ({len(sudo_matches)} appels). "
            f"Cela contourne les règles d'accès (ir.rule) et les ACL."
            f"{cond_clause} "
            f"[Confiance: FAIBLE - logique stockée en données XML]"
        )

    # 2. Detect has_group() checks
    group_matches = _HAS_GROUP_PATTERN.findall(code)
    if group_matches:
        result.has_group_checks = list(set(group_matches))

    # 3. Detect hardcoded ID lists (e.g. FOURNISSEURS_PRIVILEGIES = [42, 108, 231])
    id_list_matches = _HARDCODED_ID_LIST_PATTERN.finditer(code)
    for match in id_list_matches:
        raw_ids = match.group(1)
        try:
            ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
            if ids:
                result.has_hardcoded_ids = True
                result.hardcoded_id_lists.append(ids)
                # The list definition itself sits at top-level, but the
                # meaningful guard is on the *usage* site (the sudo() call
                # inside the if-block that references this list).  We
                # already captured that in step 1 above, so we just echo
                # the same trigger_conditions rather than re-scanning the
                # declaration line (which is typically unguarded).
                cond_clause = ""
                if result.trigger_conditions:
                    cond_clause = (
                        f" Conditionné par: {'; '.join(result.trigger_conditions)}."
                    )
                result.security_warnings.append(
                    f" IDs EN DUR: L'action '{action_xml_id}' contient une liste d'IDs "
                    f"codés en dur: {ids}. Ces enregistrements bénéficient d'un traitement "
                    f"spécial non documenté dans les modèles Python."
                    f"{cond_clause} "
                    f"[Confiance: FAIBLE - logique stockée en données XML]"
                )
        except ValueError:
            pass

    # 4. Detect dynamic dispatch (getattr, eval, exec)
    for pattern, name in [
        (_GETATTR_PATTERN, "getattr"),
        (_EVAL_PATTERN, "eval"),
        (_EXEC_PATTERN, "exec"),
    ]:
        if pattern.search(code):
            result.has_dynamic_dispatch = True
            result.dynamic_dispatch_patterns.append(name)
            result.security_warnings.append(
                f" DISPATCH DYNAMIQUE: L'action '{action_xml_id}' utilise {name}(). "
                f"Impossible de déterminer statiquement le comportement exact. "
                f"[Confiance: FAIBLE - nécessite revue manuelle]"
            )

    # Build summary text
    from code_intelligence.utils import SENSITIVE_BYPASS_MARKER
    lines = [
        f"Analyse du code de l'action serveur '{action_xml_id}' "
        f"[Confiance: FAIBLE - logique en données XML, modifiable à l'exécution]:"
    ]

    if result.has_sudo:
        # Bloc 7 (J23-24, revised): sudo() is a genuine bypass of ir.rule/ACL,
        # not ordinary governance info -- marked for source-level redaction.
        lines.append(f"  - {SENSITIVE_BYPASS_MARKER} SUDO détecté: Contournement des droits d'accès via sudo()")

    if result.has_hardcoded_ids:
        for id_list in result.hardcoded_id_lists:
            # Bloc 7 (J23-24, revised): hardcoded ID lists grant undocumented
            # special treatment outside the normal ACL/ir.rule system -- same
            # bypass category as sudo(), marked identically.
            lines.append(f"  - {SENSITIVE_BYPASS_MARKER} IDs en dur: {id_list} → traitement privilégié non documenté")

    if result.trigger_conditions:
        lines.append(
            f"  - ⚡ Condition(s) de déclenchement: "
            + "; ".join(result.trigger_conditions)
        )

    if result.has_group_checks:
        # NOT marked: has_group() is Odoo's normal, documented access-control
        # mechanism -- legitimate governance info, not a bypass.
        lines.append(f"  - Vérifications de groupes: {', '.join(result.has_group_checks)}")

    if result.has_dynamic_dispatch:
        # NOT marked: this is a confidence/uncertainty caveat ("can't be sure
        # statically"), not itself a disclosed bypass mechanism.
        lines.append(
            f"  - Dispatch dynamique: {', '.join(result.dynamic_dispatch_patterns)} "
            f"→ comportement non classifiable statiquement"
        )

    if not result.security_warnings:
        lines.append("  - Aucun pattern de sécurité détecté dans le code.")

    result.summary_text = "\n".join(lines)
    return result


_LLM_CONFIDENCE_CLOSED_SET = {"high", "medium", "low"}

_INTERPRETATION_SYSTEM_PROMPT = (
    "Tu es un analyste de sécurité pour du code Odoo ir.actions.server (server actions). "
    "Un premier passage automatique (regex) a déjà détecté des patterns de sécurité dans ce "
    "code -- ta tâche est UNIQUEMENT d'interpréter et résumer en une phrase ce que fait "
    "concrètement ce code du point de vue métier/sécurité, et d'indiquer ta confiance dans "
    "cette interprétation. Réponds STRICTEMENT en JSON, sans aucun texte avant ou après, "
    'au format exact: {"summary": "...", "confidence": "high"|"medium"|"low"}. '
    "N'utilise JAMAIS une autre valeur de confidence que high, medium, ou low."
)


def _build_interpretation_prompt(analysis: "ServerActionCodeAnalysis", code: str) -> str:
    detected = "\n".join(f"- {w}" for w in analysis.security_warnings)
    return (
        f"Code de l'action serveur '{analysis.action_xml_id}':\n"
        f"```python\n{code}\n```\n\n"
        f"Patterns déjà détectés par analyse statique (regex):\n{detected}\n\n"
        "Résume en une phrase claire ce que fait ce code du point de vue métier/sécurité, "
        "et indique ta confiance dans cette interprétation."
    )


def interpret_server_action_with_llm(
    analysis: "ServerActionCodeAnalysis",
    code: str,
    llm,
) -> "ServerActionCodeAnalysis":
    """
    J8: Bounded LLM interpretation layer on top of the existing regex-based
    static analysis. COMPLEMENTS, never replaces, the static analysis --
    the static `confidence` field ('low', fixed) and `security_warnings`
    (regex-detected facts) are returned completely unchanged.

    Only invoked when the static pass already found something worth
    interpreting (`analysis.security_warnings` non-empty) -- this keeps the
    LLM call bounded rather than run on every server action unconditionally,
    per the plan's "lecture LLM bornée" requirement.

    The LLM must respond in a fixed JSON shape with confidence restricted to
    a closed set {"high", "medium", "low"}; any malformed response, any
    confidence value outside that set, an LLM call failure, or llm=None all
    degrade gracefully to leaving llm_summary/llm_confidence as None --
    never crashes, never guesses, never silently trusts an out-of-spec
    response (same closed-list discipline as the business term resolver's
    bounded LLM arbitration).

    Args:
        analysis: the ServerActionCodeAnalysis already produced by
            analyze_server_action_code() (static regex pass).
        code: the raw ir.actions.server code field, passed for the LLM's
            own reading -- the static analysis alone is a set of detected
            patterns, not the code itself.
        llm: a LangChain-compatible chat model already instantiated by the
            caller, or None to skip the LLM pass entirely.

    Returns:
        The same ServerActionCodeAnalysis object, with llm_summary and
        llm_confidence populated if the LLM pass succeeded, left as None
        otherwise. All other fields are untouched.
    """
    if not analysis.security_warnings:
        return analysis

    if llm is None:
        return analysis

    try:
        from langchain_core.messages import SystemMessage, HumanMessage

        prompt = _build_interpretation_prompt(analysis, code)
        response = llm.invoke([
            SystemMessage(content=_INTERPRETATION_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        raw = (response.content or "").strip()
    except Exception as e:
        _logger.warning(
            "LLM interpretation call failed for action=%r: %s", analysis.action_xml_id, e
        )
        return analysis

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        _logger.warning(
            "LLM interpretation returned non-JSON response for action=%r: %r",
            analysis.action_xml_id, raw,
        )
        return analysis

    if not isinstance(parsed, dict):
        return analysis

    summary = parsed.get("summary")
    confidence = parsed.get("confidence")

    if confidence not in _LLM_CONFIDENCE_CLOSED_SET:
        _logger.warning(
            "LLM interpretation returned out-of-set confidence for action=%r: %r",
            analysis.action_xml_id, confidence,
        )
        return analysis

    if not summary or not isinstance(summary, str):
        return analysis

    analysis.llm_summary = summary
    analysis.llm_confidence = confidence

    from code_intelligence.utils import SENSITIVE_BYPASS_MARKER
    llm_tag = (
        f"{SENSITIVE_BYPASS_MARKER} "
        if (analysis.has_sudo or analysis.has_hardcoded_ids)
        else ""
    )

    analysis.summary_text += (
        f"\n  -> {llm_tag}Interprétation LLM [confiance: {confidence.upper()}, distincte de la "
        f"confiance statique ci-dessus]: {summary}"
    )

    return analysis
