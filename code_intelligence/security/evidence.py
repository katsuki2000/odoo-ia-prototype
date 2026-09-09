"""
code_intelligence/semgrep_locks_evidence.py

Evidence production, text summary formatting, and site-level security constraint extraction.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import logging

from core.evidence import Evidence, EvidenceSourceType, make_evidence

if TYPE_CHECKING:
    from code_intelligence.security.analyzer import PythonSecurityLockAnalysis

logger = logging.getLogger(__name__)


def build_security_lock_evidence(
    filepath: str,
    hardcoded_logins: List[str],
    exception_messages: List[str],
    exception_conditions: List[str],
    exception_guard_fields: List[str],
    exception_linenos: List[int],
    required_groups: List[str],
    required_group_methods: List[str],
    required_group_linenos: List[int],
    dynamic_dispatch_types: List[str],
) -> List[Evidence]:
    """Produce structured Evidence objects for security locks and uncertainties."""
    evidence: List[Evidence] = []

    # 1. hardcoded_logins
    if hardcoded_logins:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"File '{filepath}' contains hardcoded privileged login(s)/"
                f"email(s): {hardcoded_logins}"
            ),
            source=f"security_lock:{filepath}:hardcoded_logins",
            value=hardcoded_logins,
            confidence="HIGH",
            scope={},
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"File '{filepath}' contains no hardcoded login/email",
            source=f"security_lock:{filepath}:hardcoded_logins",
            value=None,
            confidence="HIGH",
            scope={},
        ))

    # 2. exception_messages
    if exception_messages:
        conditions = exception_conditions or [""] * len(exception_messages)
        guard_fields = exception_guard_fields or [""] * len(exception_messages)
        linenos = exception_linenos or [0] * len(exception_messages)
        for i, (message, condition, guard_field, lineno) in enumerate(
            zip(exception_messages, conditions, guard_fields, linenos)
        ):
            claim = f"File '{filepath}' raises UserError/ValidationError \"{message}\""
            if condition:
                claim += f" (condition: {condition})"
            if guard_field:
                claim += f" (link-guarded on '{guard_field}')"
            scope: Dict[str, Any] = {}
            if lineno:
                scope["lineno"] = lineno
            disambiguator = lineno if lineno else i
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=claim,
                source=f"security_lock:{filepath}:exception:{disambiguator}",
                value=message,
                confidence="HIGH",
                scope=scope,
            ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"File '{filepath}' raises no UserError/ValidationError with "
                f"an extractable message"
            ),
            source=f"security_lock:{filepath}:exception",
            value=None,
            confidence="HIGH",
            scope={},
        ))

    # 3. required_groups
    if required_groups:
        methods = required_group_methods or [""] * len(required_groups)
        linenos = required_group_linenos or [0] * len(required_groups)
        for group_xmlid, method_name, lineno in zip(required_groups, methods, linenos):
            claim = f"File '{filepath}' requires group '{group_xmlid}' via has_group()"
            if method_name:
                claim += f" in method '{method_name}()'"
            scope: Dict[str, Any] = {}
            if method_name:
                scope["method"] = method_name
            if lineno:
                scope["lineno"] = lineno
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=claim,
                source=f"security_lock:{filepath}:group:{group_xmlid}",
                value=group_xmlid,
                confidence="HIGH",
                scope=scope,
            ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"File '{filepath}' contains no has_group() requirement",
            source=f"security_lock:{filepath}:group",
            value=None,
            confidence="HIGH",
            scope={},
        ))

    # 4. dynamic_dispatch
    if dynamic_dispatch_types:
        for pattern_name in dynamic_dispatch_types:
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=(
                    f"File '{filepath}' uses dynamic dispatch via {pattern_name}(), "
                    f"not statically classifiable"
                ),
                source=f"security_lock:{filepath}:dynamic_dispatch:{pattern_name}",
                value=pattern_name,
                confidence="LOW",
                scope={},
            ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"File '{filepath}' uses no dynamic dispatch (getattr/eval/exec)",
            source=f"security_lock:{filepath}:dynamic_dispatch",
            value=None,
            confidence="HIGH",
            scope={},
        ))

    return evidence


def format_security_locks_summary(
    analysis: Any,
    code: str,
    filepath: str,
) -> str:
    """Format human-readable summary text for PythonSecurityLockAnalysis."""
    from code_intelligence.utils import (
        SENSITIVE_BYPASS_MARKER,
        format_file_link,
        format_xml_id_citation,
    )

    line_count = max(1, len(code.splitlines()))
    file_link = format_file_link(filepath, 1, line_count)

    _confidence_label = "FAIBLE" if analysis.confidence == "low" else analysis.confidence.upper()
    lines = [f"Analyse des verrous Python ({file_link}) [Confiance: {_confidence_label}]:"]

    if analysis.has_hardcoded_logins:
        lines.append(f"  - {SENSITIVE_BYPASS_MARKER} Logins/Emails privilégies en dur: {analysis.hardcoded_logins}")

    if analysis.exception_messages:
        lines.append(f"  - Security lock messages (UserError/ValidationError):")
        conditions = analysis.exception_conditions or [""] * len(analysis.exception_messages)
        guard_fields = analysis.exception_guard_fields or [""] * len(analysis.exception_messages)
        for msg, condition, guard_field in zip(analysis.exception_messages, conditions, guard_fields):
            if condition:
                lines.append(f"    * \"{msg}\" (condition : {condition})")
            else:
                lines.append(f"    * \"{msg}\"")
            if guard_field:
                lines.append(
                    f"      [GARDE DE LIEN: si '{guard_field}' est vide/absent (aucun "
                    f"enregistrement lie), cette condition est FAUSSE par court-circuit "
                    f"Python (evaluation de gauche a droite d'un 'and') -- la regle ci-dessus "
                    f"NE S'APPLIQUE PAS dans ce cas, quel que soit le reste de la condition.]"
                )

    if analysis.required_groups:
        methods = analysis.required_group_methods or [""] * len(analysis.required_groups)
        action_groups = [g for g, m in zip(analysis.required_groups, methods) if m]
        if action_groups:
            groups_joined = ', '.join(action_groups)
            lines.append(f"  - Groupe(s) technique(s) requis detecte(s) (has_group): {groups_joined}")
            for group_xmlid, method_name in zip(analysis.required_groups, methods):
                if method_name:
                    citation = format_xml_id_citation(group_xmlid)
                    lines.append(
                        f"    * has_group('{group_xmlid}') se trouve dans la methode '{method_name}()' -- "
                        f"ne pas l'attribuer a une autre methode sans le verifier explicitement dans le code source. ({citation})"
                    )
        for group_xmlid, method_name in zip(analysis.required_groups, methods):
            if not method_name:
                citation = format_xml_id_citation(group_xmlid)
                lines.append(
                    f"  - has_group('{group_xmlid}') se trouve hors de toute methode (niveau module, "
                    f"ex: valeur par defaut d'un champ UI) -- NE PAS interpreter comme un verrou d'acces ou de modification du modele. ({citation})"
                )

    if analysis.static_filters:
        for f_name, f_val, s_line, e_line in analysis.static_filters:
            link = format_file_link(filepath, s_line, e_line)
            lines.append(f"  - Filtre d'exclusion statique '{f_name}' ({link}): {f_val}")

    if analysis.has_dynamic_dispatch:
        lines.append(f"  - Incertitude dynamique ({', '.join(analysis.dynamic_dispatch_types)}): revue manuelle recommandée")

    if not analysis.security_warnings and not analysis.exception_messages and not analysis.static_filters:
        lines.append("  - Aucun verrou spécifique ni incertitude dynamique détecté.")

    return "\n".join(lines)


def extract_method_security_constraints(
    analysis: Any, lineno: int, end_lineno: int
) -> List[str]:
    """Filter file-level security findings down to [lineno, end_lineno] range."""
    constraints: List[str] = []

    for group_xmlid, method_name, group_lineno in zip(
        analysis.required_groups,
        analysis.required_group_methods,
        analysis.required_group_linenos,
    ):
        if group_lineno and lineno <= group_lineno <= end_lineno:
            location = f"dans '{method_name}()'" if method_name else "a cette ligne"
            constraints.append(
                f"VERROU RATTACHE AU SITE: has_group('{group_xmlid}') requis {location}."
            )

    exception_conditions = analysis.exception_conditions or [""] * len(analysis.exception_messages)
    exception_guard_fields = analysis.exception_guard_fields or [""] * len(analysis.exception_messages)
    for message, condition, guard_field, exc_lineno in zip(
        analysis.exception_messages,
        exception_conditions,
        exception_guard_fields,
        analysis.exception_linenos,
    ):
        if exc_lineno and lineno <= exc_lineno <= end_lineno:
            text = f'VERROU RATTACHE AU SITE: "{message}"'
            if condition:
                text += f" (condition : {condition})"
            if guard_field:
                text += (
                    f" [GARDE DE LIEN: si '{guard_field}' est vide/absent, cette "
                    f"condition est FAUSSE par court-circuit Python -- la regle NE "
                    f"S'APPLIQUE PAS dans ce cas.]"
                )
            constraints.append(text)

    return constraints
