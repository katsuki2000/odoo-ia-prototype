"""
code_intelligence/extractor/xml_models.py

Data models and parsing helpers for Odoo XML files.
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Set, Tuple, Union

_logger = logging.getLogger(__name__)


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
    action_type: str = "act_window"
    tag: str = ""
    res_model: str = ""
    view_mode: str = ""
    domain: str = ""
    groups_id: List[str] = field(default_factory=list)


@dataclass
class OdooReportRecord:
    """Represents an ir.actions.report record (printable report) extracted from XML data files."""
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model: str = ""  # technical model name (plain string field, not a ref)
    binding_model_id: str = ""
    report_type: str = ""
    report_name: str = ""
    print_report_name: str = ""
    groups_id: List[str] = field(default_factory=list)


@dataclass
class OdooMailTemplateRecord:
    """Represents a mail.template record extracted from XML data files (body_html is not kept)."""
    xml_id: str
    filepath: str
    lineno: int
    name: str = ""
    model_id: str = ""
    subject: str = ""
    description: str = ""
    email_from: str = ""
    email_to: str = ""
    partner_to: str = ""
    lang: str = ""
    report_template_ids: List[str] = field(default_factory=list)
    active: bool = True


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
    context: str = ""


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


def _read_and_parse_xml(
    filepath: Path,
    *,
    missing_message: Optional[str] = None,
    error_context: str = "",
) -> Optional[Tuple[str, ET.Element]]:
    """
    Shared boilerplate for the record-based XML parsers below: existence check,
    read + parse, and consistent error logging. Returns None (never raises) on
    any failure so callers can keep their original 'return []' short-circuit;
    returns (raw_content, root) on success for the rare caller (line-number
    estimation) that needs the raw text alongside the parsed tree.

    `missing_message` is logged at WARNING level if filepath does not exist;
    if None, the missing-file case is silent (matches parsers that return []
    without logging). `error_context` (e.g. "for actions") is spliced into the
    parse-failure log message to preserve each caller's distinct wording.
    """
    if not filepath.exists():
        if missing_message:
            _logger.warning(missing_message, filepath)
        return None

    try:
        content = filepath.read_text(encoding="utf-8")
        return content, ET.fromstring(content)
    except Exception as e:
        if error_context:
            _logger.error("Failed to parse XML file %s %s: %s", filepath, error_context, e)
        else:
            _logger.error("Failed to parse XML file %s: %s", filepath, e)
        return None


def parse_xml_root(
    filepath: Path,
    *,
    missing_message: Optional[str] = None,
    error_context: str = "",
) -> Optional[ET.Element]:
    """Like `_read_and_parse_xml`, but for the common case that only needs the parsed root."""
    result = _read_and_parse_xml(filepath, missing_message=missing_message, error_context=error_context)
    return result[1] if result else None


def parse_xml_document(
    filepath: Path,
    *,
    missing_message: Optional[str] = None,
    error_context: str = "",
) -> Optional[Tuple[str, ET.Element]]:
    """Read and parse an XML source once for use by multiple extractors."""
    return _read_and_parse_xml(
        filepath,
        missing_message=missing_message,
        error_context=error_context,
    )


def iter_records_by_model(
    root: ET.Element, model_names: Union[str, Set[str]]
) -> Iterator[Tuple[str, ET.Element]]:
    """Yield (xml_id, record) for every <record> whose model attribute matches."""
    names = {model_names} if isinstance(model_names, str) else model_names
    for record in root.findall(".//record"):
        if record.attrib.get("model") not in names:
            continue
        yield record.attrib.get("id", ""), record


def iter_field_attrs(
    record: ET.Element,
) -> Iterator[Tuple[str, str, Optional[str], Optional[str], ET.Element]]:
    """
    Yield (field_name, field_text, field_ref, field_eval, field_elem) for each named
    <field>. `field_text` is stripped; the raw `field_elem` is also yielded for the
    rare caller that needs the unstripped `.text` (e.g. preserving code whitespace).
    """
    for field_elem in record.findall("field"):
        field_name = field_elem.attrib.get("name")
        if not field_name:
            continue
        field_text = (field_elem.text or "").strip()
        field_ref = field_elem.attrib.get("ref")
        field_eval = field_elem.attrib.get("eval")
        yield field_name, field_text, field_ref, field_eval, field_elem
