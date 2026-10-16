"""Models reached by OWL client actions: registry tag -> literal ORM models of the registering file and its local imports."""

import logging
import re
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Set

import tree_sitter_javascript
from tree_sitter import Language, Node, Parser

logger = logging.getLogger(__name__)

SOURCE_DIR = Path("static") / "src"
MUTATING_ORM_METHODS = frozenset({"create", "write", "unlink"})
MODEL_NAME = re.compile(r"[a-z_]\w*(?:\.\w+)+")
PARSER = Parser(Language(tree_sitter_javascript.language()))


class JsFacts(NamedTuple):
    tags: List[str]
    models: Set[str]
    imports: List[str]


def _walk(root: Node) -> Iterator[Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def _text(node: Optional[Node]) -> str:
    return node.text.decode("utf-8") if node is not None else ""


def _literal(node: Optional[Node]) -> Optional[str]:
    if node is None:
        return None
    if node.type == "string" or (
        node.type == "template_string" and all(child.type != "template_substitution" for child in node.children)
    ):
        return _text(node)[1:-1]
    return None


def _first_argument(call: Node) -> Optional[str]:
    arguments = call.child_by_field_name("arguments")
    return _literal(arguments.named_children[0]) if arguments is not None and arguments.named_children else None


def _callee(call: Node) -> Optional[Node]:
    callee = call.child_by_field_name("function")
    return callee if callee is not None and callee.type == "member_expression" else None


def _is_actions_registry(node: Optional[Node]) -> bool:
    if node is None or node.type != "call_expression":
        return False
    callee = _callee(node)
    return (
        callee is not None
        and _text(callee.child_by_field_name("object")) == "registry"
        and _text(callee.child_by_field_name("property")) == "category"
        and _first_argument(node) == "actions"
    )


def _is_orm(node: Optional[Node]) -> bool:
    if node is None:
        return False
    if node.type == "identifier":
        return _text(node) == "orm"
    if node.type != "member_expression":
        return False
    member = _text(node.child_by_field_name("property"))
    return member == "orm" or (member == "silent" and _is_orm(node.child_by_field_name("object")))


def _is_actions_receiver(node: Optional[Node], aliases: Set[str]) -> bool:
    return _is_actions_registry(node) or (node is not None and node.type == "identifier" and _text(node) in aliases)


def parse_js_facts(content: str) -> JsFacts:
    nodes = list(_walk(PARSER.parse(content.encode("utf-8")).root_node))
    aliases = {
        _text(node.child_by_field_name("name")) for node in nodes
        if node.type == "variable_declarator" and _is_actions_registry(node.child_by_field_name("value"))
    }
    facts = JsFacts([], set(), [])
    for node in nodes:
        if node.type == "import_statement":
            source = _literal(node.child_by_field_name("source"))
            if source:
                facts.imports.append(source)
        elif node.type == "call_expression":
            callee, argument = _callee(node), _first_argument(node)
            if callee is None or argument is None:
                continue
            method, receiver = _text(callee.child_by_field_name("property")), callee.child_by_field_name("object")
            if method == "add" and _is_actions_receiver(receiver, aliases):
                facts.tags.append(argument)
            elif method not in MUTATING_ORM_METHODS and _is_orm(receiver) and MODEL_NAME.fullmatch(argument):
                facts.models.add(argument)
    return facts


def _resolve_import(source: str, importer: Path, addonDir: Path) -> Optional[Path]:
    if source.startswith("."):
        target = importer.parent / source
    elif source.startswith(f"@{addonDir.name}/"):
        target = addonDir / SOURCE_DIR / source.removeprefix(f"@{addonDir.name}/")
    else:
        return None
    return (target if target.suffix == ".js" else target.with_name(target.name + ".js")).resolve()


def _reachable_models(entry: Path, facts: Dict[Path, JsFacts], addonDir: Path) -> Set[str]:
    models: Set[str] = set()
    pending, seen = [entry], set()
    while pending:
        current = pending.pop()
        if current in seen or current not in facts:
            continue
        seen.add(current)
        models |= facts[current].models
        pending.extend(
            resolved for source in facts[current].imports
            if (resolved := _resolve_import(source, current, addonDir)) is not None
        )
    return models


def parse_client_action_models(addonDir: Path) -> Dict[str, List[str]]:
    """Map each client action tag registered by the addon to the literal ORM models its code reaches."""
    resolvedAddon = addonDir.resolve()
    sourceRoot = resolvedAddon / SOURCE_DIR
    if not sourceRoot.is_dir():
        return {}
    facts: Dict[Path, JsFacts] = {}
    for jsFile in sourceRoot.rglob("*.js"):
        try:
            facts[jsFile.resolve()] = parse_js_facts(jsFile.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as error:
            logger.warning("Cannot read %s for client action models: %s", jsFile, error)
    tagModels: Dict[str, Set[str]] = {}
    for jsFile, fileFacts in facts.items():
        for tag in fileFacts.tags:
            tagModels.setdefault(tag, set()).update(_reachable_models(jsFile, facts, resolvedAddon))
    return {tag: sorted(models) for tag, models in tagModels.items()}
