"""
code_intelligence/js_extractor.py

JS and OWL client-side security check extractor.
Implements Story A1.4: Task A1.4.1 (extraction of hasGroup and OWL t-if user.hasGroup patterns).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List
import logging

_logger = logging.getLogger(__name__)


@dataclass
class OdooClientGroupCheck:
    filepath: str
    lineno: int
    group_id: str
    pattern_type: str
    client_side_only: bool = True


# Patterns to match client-side JS and OWL group checks
JS_HAS_GROUP_PATTERN = re.compile(
    r"(?:this\.env\.)?user\.hasGroup\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
    re.IGNORECASE
)
SESSION_HAS_GROUP_PATTERN = re.compile(
    r"session\.has_group\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
    re.IGNORECASE
)
OWL_T_IF_HAS_GROUP_PATTERN = re.compile(
    r"t-if=[\"'][^\"']*(?:user\.hasGroup|hasGroup)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)[^\"']*[\"']",
    re.IGNORECASE
)


def parse_client_group_checks(filepath: Path) -> List[OdooClientGroupCheck]:
    """
    Parse a JS or XML/OWL file and extract all client-side group permission checks.
    All extracted checks carry client_side_only=True.
    """
    if not filepath.exists():
        _logger.warning("File does not exist for JS group check parsing: %s", filepath)
        return []

    checks: List[OdooClientGroupCheck] = []

    try:
        content = filepath.read_text(encoding="utf-8")
        lines = content.splitlines()

        for idx, line in enumerate(lines):
            lineno = idx + 1
            if not line.strip() or line.strip().startswith("//"):
                continue

            seen_line_groups = set()

            # 1. OWL t-if="user.hasGroup(...)" (more specific pattern first)
            for match in OWL_T_IF_HAS_GROUP_PATTERN.finditer(line):
                group_id = match.group(1).strip()
                if group_id and (lineno, group_id) not in seen_line_groups:
                    seen_line_groups.add((lineno, group_id))
                    checks.append(
                        OdooClientGroupCheck(
                            filepath=str(filepath),
                            lineno=lineno,
                            group_id=group_id,
                            pattern_type="owl_t_if_hasGroup",
                            client_side_only=True,
                        )
                    )

            # 2. JS user.hasGroup(...)
            for match in JS_HAS_GROUP_PATTERN.finditer(line):
                group_id = match.group(1).strip()
                if group_id and (lineno, group_id) not in seen_line_groups:
                    seen_line_groups.add((lineno, group_id))
                    checks.append(
                        OdooClientGroupCheck(
                            filepath=str(filepath),
                            lineno=lineno,
                            group_id=group_id,
                            pattern_type="js_hasGroup",
                            client_side_only=True,
                        )
                    )

            # 3. Session has_group(...)
            for match in SESSION_HAS_GROUP_PATTERN.finditer(line):
                group_id = match.group(1).strip()
                if group_id and (lineno, group_id) not in seen_line_groups:
                    seen_line_groups.add((lineno, group_id))
                    checks.append(
                        OdooClientGroupCheck(
                            filepath=str(filepath),
                            lineno=lineno,
                            group_id=group_id,
                            pattern_type="session_has_group",
                            client_side_only=True,
                        )
                    )

    except Exception as e:
        _logger.error("Error parsing client group checks in %s: %s", filepath, e)

    return checks
