"""Inventory of the Odoo artefacts present in one module directory, read straight from the source files."""

import ast
import csv
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Set

from code_intelligence.extractor.csv import ACCESS_CONTROL_CSV_NAME
from code_intelligence.extractor.js_client_actions import SOURCE_DIR, parse_js_facts
from code_intelligence.extractor.xml_models import parse_xml_root

logger = logging.getLogger(__name__)

XML_TAG_KINDS = {
    "menuitem": "ir.ui.menu",
    "template": "qweb_template",
    "report": "ir.actions.report",
    "act_window": "ir.actions.act_window",
}
ACCESS_KIND = "ir.model.access"


@dataclass
class ModuleInventory:
    xmlIds: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    counts: Counter = field(default_factory=Counter)

    def add(self, kind: str, xmlId: str = "") -> None:
        self.counts[kind] += 1
        if xmlId:
            self.xmlIds[kind].add(xmlId)


def _qualified(xmlId: str, module: str) -> str:
    return xmlId if "." in xmlId else f"{module}.{xmlId}"


def _scan_xml(path: Path, moduleDir: Path, inventory: ModuleInventory) -> None:
    root = parse_xml_root(path)
    if root is None:
        return
    isStatic = "static" in path.relative_to(moduleDir).parts
    for element in root.iter():
        xmlId = element.get("id", "")
        kind = element.get("model") if element.tag == "record" else XML_TAG_KINDS.get(element.tag)
        if kind:
            inventory.add(kind, _qualified(xmlId, moduleDir.name) if xmlId else "")
        elif isStatic and element.get("t-name"):
            inventory.add("owl_template")


def _scan_access_csv(path: Path, moduleDir: Path, inventory: ModuleInventory) -> None:
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("id"):
                inventory.add(ACCESS_KIND, _qualified(row["id"].strip(), moduleDir.name))


def _is_route_decorator(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else None
    return (isinstance(target, ast.Attribute) and target.attr == "route") or (
        isinstance(target, ast.Name) and target.id == "route"
    )


def _scan_python(path: Path, moduleName: str, inventory: ModuleInventory) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))

    def visit(body, owner: str) -> None:
        # Only classes and functions reachable from the module body count: a controller declared inside a
        # function (test fixtures) is not a route of the addon.
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(node.body, node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if _is_route_decorator(decorator):
                        inventory.add("http_route", f"{moduleName}.{owner}.{node.name}")

    visit(tree.body, "<module>")


def _scan_javascript(path: Path, inventory: ModuleInventory) -> None:
    inventory.add("js_file")
    for tag in parse_js_facts(path.read_text(encoding="utf-8")).tags:
        inventory.add("js_client_action_tag", tag)


def _scan_safely(scan, path: Path, *arguments) -> None:
    try:
        scan(path, *arguments)
    except (OSError, UnicodeDecodeError, SyntaxError, csv.Error) as error:
        logger.warning("Cannot inventory %s: %s", path, error)


def inventory_module(moduleDir: Path) -> ModuleInventory:
    inventory = ModuleInventory()
    for path in moduleDir.rglob("*.xml"):
        _scan_safely(_scan_xml, path, moduleDir, inventory)
    for path in moduleDir.rglob(ACCESS_CONTROL_CSV_NAME):
        _scan_safely(_scan_access_csv, path, moduleDir, inventory)
    for path in moduleDir.rglob("*.py"):
        _scan_safely(_scan_python, path, moduleDir.name, inventory)
    sourceRoot = moduleDir / SOURCE_DIR
    for path in sourceRoot.rglob("*.js") if sourceRoot.is_dir() else ():
        _scan_safely(_scan_javascript, path, inventory)
    return inventory
