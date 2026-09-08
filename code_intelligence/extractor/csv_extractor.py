"""
code_intelligence/extractor/csv_extractor.py

CSV ACL extractor for ir.model.access.csv files.
CSV ACL parsing and empty group_id all_authenticated handling.
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import logging

_logger = logging.getLogger(__name__)


@dataclass
class OdooAccessEntry:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model_id: str = ""
    group_id: Optional[str] = None
    all_authenticated: bool = False
    perm_read: bool = False
    perm_write: bool = False
    perm_create: bool = False
    perm_unlink: bool = False


def _parse_perm(val: Optional[str]) -> bool:
    """Parse permission integer flag ('1'/'0' or 1/0) to boolean."""
    if val is None:
        return False
    clean_val = str(val).strip()
    return clean_val in {"1", "True", "true"}


def parse_access_control_csv(filepath: Path) -> List[OdooAccessEntry]:
    """
    Parse an ir.model.access.csv file and extract all ACL entries.
    Handles empty group_id as all_authenticated=True 
    """
    if not filepath.exists():
        _logger.warning("ACL CSV file does not exist: %s", filepath)
        return []

    entries: List[OdooAccessEntry] = []

    try:
        content = filepath.read_text(encoding="utf-8")
        lines = content.splitlines()
        if not lines:
            return []

        reader = csv.DictReader(lines)
        lineno = 1

        for row in reader:
            lineno += 1
            if not row:
                continue

            xml_id = (row.get("id") or "").strip()
            name = (row.get("name") or "").strip()

            # Handle header variations: model_id:id, model_id/id, model_id
            model_id = (
                row.get("model_id:id") or row.get("model_id/id") or row.get("model_id") or ""
            ).strip()

            # Handle header variations: group_id:id, group_id/id, group_id
            raw_group_id = (
                row.get("group_id:id") or row.get("group_id/id") or row.get("group_id") or ""
            ).strip()

            if raw_group_id:
                group_id = raw_group_id
                all_authenticated = False
            else:
                group_id = None
                all_authenticated = True

            perm_read = _parse_perm(row.get("perm_read"))
            perm_write = _parse_perm(row.get("perm_write"))
            perm_create = _parse_perm(row.get("perm_create"))
            perm_unlink = _parse_perm(row.get("perm_unlink"))

            if xml_id or name or model_id:
                entries.append(
                    OdooAccessEntry(
                        xml_id=xml_id,
                        filepath=str(filepath),
                        lineno=lineno,
                        name=name,
                        model_id=model_id,
                        group_id=group_id,
                        all_authenticated=all_authenticated,
                        perm_read=perm_read,
                        perm_write=perm_write,
                        perm_create=perm_create,
                        perm_unlink=perm_unlink,
                    )
                )

    except Exception as e:
        _logger.error("Error parsing ACL CSV %s: %s", filepath, e)

    return entries


__all__ = [
    "OdooAccessEntry",
    "_parse_perm",
    "parse_access_control_csv",
]

