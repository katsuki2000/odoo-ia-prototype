"""AST static analysis check for unchecked relational field chains in method overrides."""

import ast
import logging
from pathlib import Path
from typing import List, Optional

import networkx as nx

from code_intelligence.knowledge_rules.overrides.types import resolve_method_override_chain
from code_intelligence.knowledge_rules.overrides.unguarded_super import detect_unguarded_super
from core.confidence_tags import confidence_label

_logger = logging.getLogger(__name__)

_RELATIONAL_CHAIN_MIN_DEPTH = 4


def _attribute_chain_depth(node: ast.Attribute) -> int:
    depth = 0
    cur = node
    while isinstance(cur, ast.Attribute):
        depth += 1
        cur = cur.value
    return depth


def _attribute_chain_names(node: ast.Attribute) -> List[str]:
    names = []
    cur = node
    while isinstance(cur, ast.Attribute):
        names.append(cur.attr)
        cur = cur.value
    return list(reversed(names))


class _UncheckedRelationalChainVisitor(ast.NodeVisitor):
    def __init__(self):
        self.checked_names: set = set()
        self.long_chains: List[tuple] = []

    def visit_If(self, node: ast.If):
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Attribute):
                self.checked_names.add(sub.attr)
            elif isinstance(sub, ast.Name):
                self.checked_names.add(sub.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        depth = _attribute_chain_depth(node)
        if depth >= _RELATIONAL_CHAIN_MIN_DEPTH:
            names = _attribute_chain_names(node)
            self.long_chains.append((node.lineno, ".".join(names), names))
        for child in ast.iter_child_nodes(node):
            if child is not node.value:
                self.visit(child)


def _find_guarding_condition_for_helper_call(
    func: ast.FunctionDef, helper_name: str
) -> Optional[str]:
    result: Optional[str] = None

    class _GuardFinder(ast.NodeVisitor):
        def __init__(self):
            self._if_test_stack: List[ast.expr] = []

        def visit_If(self, node: ast.If):
            self._if_test_stack.append(node.test)
            self.generic_visit(node)
            self._if_test_stack.pop()

        def visit_Call(self, node: ast.Call):
            nonlocal result
            if (
                result is None
                and self._if_test_stack
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == helper_name
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                try:
                    result = ast.unparse(self._if_test_stack[-1])
                except Exception:
                    result = None
            self.generic_visit(node)

    _GuardFinder().visit(func)
    return result


def detect_unchecked_relational_chain(
    source: str, filepath: str, method_name: str, target_lineno: int, module: str = ""
) -> Optional[str]:
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError as e:
        _logger.warning("Could not parse %s for relational-chain analysis: %s", filepath, e)
        return None

    target_func = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == method_name
            and node.lineno == target_lineno
        ):
            target_func = node
            break

    if target_func is None:
        return None

    candidates = [target_func]
    called_helper_names = {
        n.func.attr
        for n in ast.walk(target_func)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "self"
    }
    if called_helper_names:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in called_helper_names:
                candidates.append(node)

    findings = []
    for func in candidates:
        guarding_condition = None
        if func is not target_func:
            guarding_condition = _find_guarding_condition_for_helper_call(
                target_func, func.name
            )
        visitor = _UncheckedRelationalChainVisitor()
        visitor.visit(func)
        for lineno, dotted, names in visitor.long_chains:
            if not any(n in visitor.checked_names for n in names):
                findings.append((func.name, lineno, dotted, guarding_condition))

    if not findings:
        return None

    detail_parts = []
    for fn, ln, path, condition in findings:
        part = f"{fn}() L{ln}: `{path}`"
        if condition:
            part += f" (atteint si `{condition}`)"
        detail_parts.append(part)
    detail = "; ".join(detail_parts)
    return (
        "CHAINE RELATIONNELLE NON V\u00c9RIFI\u00c9E (R\u00e8gle 3): "
        f"'{method_name}' (module '{module}') d\u00e9pend d'une cha\u00eene de champs "
        f"Many2one encha\u00een\u00e9s sans v\u00e9rification d'existence -- {detail}. Si un "
        "maillon interm\u00e9diaire est vide, l'expression compl\u00e8te s'\u00e9value "
        "silencieusement \u00e0 False/un recordset vide, sans erreur -- risque r\u00e9el "
        "que la personne cens\u00e9e \u00eatre notifi\u00e9e/valider ne le soit jamais, sans "
        f"signal d'erreur. [Confiance: {confidence_label('low')} -- heuristique statique, ne "
        "v\u00e9rifie pas si un garde est exprim\u00e9 ailleurs dans l'appelant]"
    )


def find_methods_with_override_risk_findings(
    G: nx.DiGraph, model_name: str, method_names: List[str]
) -> List[str]:
    hits: List[str] = []
    for method_name in method_names:
        sites = resolve_method_override_chain(G, model_name, method_name)
        for site in sites:
            p = Path(site.filepath)
            if not p.exists():
                continue
            try:
                source = p.read_text(encoding="utf-8")
            except OSError:
                continue
            if detect_unguarded_super(
                source, site.filepath, method_name, site.lineno, module=site.module
            ) or detect_unchecked_relational_chain(
                source, site.filepath, method_name, site.lineno, module=site.module
            ):
                hits.append(method_name)
                break
    return hits


find_methods_with_unguarded_super_and_relational_risk = find_methods_with_override_risk_findings
find_methods_with_unguarded_super = find_methods_with_override_risk_findings
