"""HTTP route extractor: `@http.route(...)` / `@route(...)` decorated controller methods, read with `ast`."""

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

_logger = logging.getLogger(__name__)

MODULE_LEVEL = "<module>"
DEFAULT_AUTH = "user"  # Odoo default when a route declares a path without `auth`


@dataclass
class OdooHttpRoute:
    controller: str
    method_name: str
    filepath: str
    lineno: int
    paths: List[str] = field(default_factory=list)
    route_type: str = ""
    auth: str = ""
    methods: List[str] = field(default_factory=list)
    website: Optional[bool] = None
    csrf: Optional[bool] = None
    overrides_parent: bool = False  # bare `@http.route()`: path and auth come from the parent route


def is_route_decorator(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else None
    return (isinstance(target, ast.Attribute) and target.attr == "route") or (
        isinstance(target, ast.Name) and target.id == "route"
    )


def _literal(node: Optional[ast.expr]):
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None


def _strings(value) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


def _route_from_decorator(decorator: ast.Call, controller: str, function, filepath: str) -> OdooHttpRoute:
    keywords = {kw.arg: kw.value for kw in decorator.keywords if kw.arg}
    pathNode = decorator.args[0] if decorator.args else keywords.get("route")
    paths = _strings(_literal(pathNode))
    auth = _literal(keywords.get("auth"))
    if "auth" not in keywords and pathNode is not None:
        auth = DEFAULT_AUTH
    routeType = _literal(keywords.get("type"))
    website, csrf = _literal(keywords.get("website")), _literal(keywords.get("csrf"))
    return OdooHttpRoute(
        controller=controller,
        method_name=function.name,
        filepath=filepath,
        lineno=function.lineno,
        paths=paths,
        route_type=routeType if isinstance(routeType, str) else "",
        auth=auth if isinstance(auth, str) else "",
        methods=_strings(_literal(keywords.get("methods"))),
        website=website if isinstance(website, bool) else None,
        csrf=csrf if isinstance(csrf, bool) else None,
        overrides_parent=pathNode is None,
    )


def parse_http_routes(
    filepath: Path,
    *,
    source: Optional[str] = None,
    tree: Optional[ast.Module] = None,
) -> List[OdooHttpRoute]:
    """Extract routes from a file or an already parsed AST. Non literal arguments stay empty."""
    if source is None:
        try:
            source = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            _logger.warning("Cannot read %s for routes: %s", filepath, error)
            return []
    if "route" not in source:
        return []
    if tree is None:
        try:
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError as error:
            _logger.warning("Cannot parse %s for routes: %s", filepath, error)
            return []

    routes: List[OdooHttpRoute] = []

    def visit(body, controller: str) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(node.body, node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and is_route_decorator(decorator):
                        routes.append(_route_from_decorator(decorator, controller, node, str(filepath)))

    visit(tree.body, MODULE_LEVEL)
    return routes
