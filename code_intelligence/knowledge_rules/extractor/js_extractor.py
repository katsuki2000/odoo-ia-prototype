"""
code_intelligence/extractor/js_extractor.py

JS and OWL client-side security check extractor for hasGroup patterns.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

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

# Ordered (pattern, pattern_type) pairs: OWL's t-if wrapper is more specific than the
# bare JS/session calls it can contain, so it is matched first to claim the group_id
# for that line before the generic patterns get a chance at the same substring.
CLIENT_GROUP_CHECK_PATTERNS = [
    (OWL_T_IF_HAS_GROUP_PATTERN, "owl_t_if_hasGroup"),
    (JS_HAS_GROUP_PATTERN, "js_hasGroup"),
    (SESSION_HAS_GROUP_PATTERN, "session_has_group"),
]


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

            for pattern, pattern_type in CLIENT_GROUP_CHECK_PATTERNS:
                for match in pattern.finditer(line):
                    group_id = match.group(1).strip()
                    if group_id and (lineno, group_id) not in seen_line_groups:
                        seen_line_groups.add((lineno, group_id))
                        checks.append(
                            OdooClientGroupCheck(
                                filepath=str(filepath),
                                lineno=lineno,
                                group_id=group_id,
                                pattern_type=pattern_type,
                                client_side_only=True,
                            )
                        )

    except Exception as e:
        _logger.error("Error parsing client group checks in %s: %s", filepath, e)

    return checks
