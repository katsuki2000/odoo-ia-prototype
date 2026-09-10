"""
code_intelligence/extractor/xml_models.py

Data models and parsing helpers for Odoo XML files.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class OdooRuleRecord:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model_id: str = ""
    domain_force: str = ""
    groups_id: List[str] = field(default_factory=list)
    perm_read: bool = True
    perm_write: bool = True
    perm_create: bool = True
    perm_unlink: bool = True
    active: bool = True


@dataclass
class OdooGroupRecord:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    category_id: str = ""
    implied_ids: List[str] = field(default_factory=list)
    comment: str = ""


@dataclass
class OdooActionRecord:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    res_model: str = ""
    view_mode: str = ""
    groups_id: List[str] = field(default_factory=list)


@dataclass
class OdooServerActionRecord:
    """Represents an ir.actions.server or ir.cron record extracted from XML data files."""
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model_id: str = ""
    state: str = "code"
    code: str = ""
    groups_id: List[str] = field(default_factory=list)
    action_type: str = "server_action"  # 'server_action' or 'cron'
    user_id: str = ""
    interval_number: int = 1
    interval_type: str = ""


@dataclass
class OdooBaseAutomationRecord:
    """Represents a base.automation record extracted from XML data files."""
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model_id: str = ""
    trigger: str = ""
    action_server_ids: List[str] = field(default_factory=list)


@dataclass
class OdooXmlFieldRecord:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model: str = ""
    field_description: str = ""
    ttype: str = ""
    relation: str = ""


@dataclass
class OdooMenuItemRecord:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    parent: str = ""
    action: str = ""
    sequence: int = 10
    groups: List[str] = field(default_factory=list)


@dataclass
class OdooFormButton:
    name: str
    string: str
    type: str = "object"
    states: str = ""
    groups: List[str] = field(default_factory=list)
    invisible: str = ""


@dataclass
class OdooViewRecord:
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model: str = ""
    view_type: str = "form"
    buttons: List[OdooFormButton] = field(default_factory=list)


def parse_eval_bool(eval_attr: Optional[str], text_content: Optional[str], default: bool = True) -> bool:
    """Parse boolean value for Odoo permissions from eval attribute or text content."""
    if eval_attr is not None:
        eval_str = eval_attr.strip()
        if eval_str in {"0", "False", "0.0"}:
            return False
        elif eval_str in {"1", "True", "1.0"}:
            return True

    if text_content is not None and text_content.strip():
        text_str = text_content.strip()
        if text_str in {"0", "False"}:
            return False
        elif text_str in {"1", "True"}:
            return True

    return default


def extract_refs_from_eval(eval_str: str) -> List[str]:
    """Extract all ref('xml_id') values from an eval string."""
    if not eval_str:
        return []
    # Pattern to match ref('xml_id') or ref("xml_id")
    pattern = r"ref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"
    return re.findall(pattern, eval_str)
