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


# Regex patterns for security-relevant code constructs
_SUDO_PATTERN = re.compile(r"\.sudo\s*\(")
_HAS_GROUP_PATTERN = re.compile(r"\.has_group\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
_HARDCODED_ID_LIST_PATTERN = re.compile(
    r"\b[A-Z_]+\s*=\s*\[(\s*\d+(?:\s*,\s*\d+)*\s*)\]"
)
_GETATTR_PATTERN = re.compile(r"\bgetattr\s*\(")
_EVAL_PATTERN = re.compile(r"\beval\s*\(")
_EXEC_PATTERN = re.compile(r"\bexec\s*\(")


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

    # 1. Detect sudo() calls
    sudo_matches = _SUDO_PATTERN.findall(code)
    if sudo_matches:
        result.has_sudo = True
        result.security_warnings.append(
            f"⚠️ SUDO: L'action '{action_xml_id}' utilise sudo() ({len(sudo_matches)} appels). "
            f"Cela contourne les règles d'accès (ir.rule) et les ACL. "
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
                result.security_warnings.append(
                    f"⚠️ IDs EN DUR: L'action '{action_xml_id}' contient une liste d'IDs "
                    f"codés en dur: {ids}. Ces enregistrements bénéficient d'un traitement "
                    f"spécial non documenté dans les modèles Python. "
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
                f"⚠️ DISPATCH DYNAMIQUE: L'action '{action_xml_id}' utilise {name}(). "
                f"Impossible de déterminer statiquement le comportement exact. "
                f"[Confiance: FAIBLE - nécessite revue manuelle]"
            )

    # Build summary text
    lines = [
        f"Analyse du code de l'action serveur '{action_xml_id}' "
        f"[Confiance: FAIBLE - logique en données XML, modifiable à l'exécution]:"
    ]

    if result.has_sudo:
        lines.append(f"  - SUDO détecté: Contournement des droits d'accès via sudo()")

    if result.has_hardcoded_ids:
        for id_list in result.hardcoded_id_lists:
            lines.append(f"  - IDs en dur: {id_list} → traitement privilégié non documenté")

    if result.has_group_checks:
        lines.append(f"  - Vérifications de groupes: {', '.join(result.has_group_checks)}")

    if result.has_dynamic_dispatch:
        lines.append(
            f"  - Dispatch dynamique: {', '.join(result.dynamic_dispatch_patterns)} "
            f"→ comportement non classifiable statiquement"
        )

    if not result.security_warnings:
        lines.append("  - Aucun pattern de sécurité détecté dans le code.")

    result.summary_text = "\n".join(lines)
    return result
