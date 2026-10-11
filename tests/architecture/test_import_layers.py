"""Import direction between the shared kernel, the orchestration layer and the engines.

Engines (code_intelligence, document_rag, erp_data) depend on the kernel only.
The kernel depends on neither the engines nor the orchestration layer.
KNOWN_VIOLATIONS lists the imports still to be removed; the test fails when a new
violation appears or when a listed one has been fixed, so the list only shrinks.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ENGINES = ("code_intelligence", "document_rag", "erp_data")
KERNEL = ("core.llm", "core.session", "core.schemas", "core.output", "core.evidence")
ORCHESTRATION = ("core.graph", "core.routing", "core.verification", "core.evaluation")

KNOWN_VIOLATIONS = frozenset({
    ("code_intelligence.agent.access_guards", "core.verification.extractors"),
    ("core.evidence.evidence_check", "code_intelligence.agent.matching"),
    ("core.evidence.evidence_sufficiency", "code_intelligence.rules.common"),
    ("core.schemas", "core.verification.claims"),
    ("document_rag.verification", "core.evaluation.oracles.documentation"),
    ("document_rag.verification", "core.evaluation.protocol_metrics"),
})


def _is_under(module, prefixes):
    return any(module == prefix or module.startswith(prefix + ".") for prefix in prefixes)


def _module_name(path):
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_modules(path):
    package = _module_name(path).split(".")
    if path.name != "__init__.py":
        package.pop()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            if module == "core":
                yield from (f"core.{alias.name}" for alias in node.names)
            else:
                yield module


def _source_files():
    for package in ("core", *ENGINES):
        for path in sorted((ROOT / package).rglob("*.py")):
            if "tests" not in path.parts and not path.name.startswith("test_"):
                yield path


def _forbidden_targets(source):
    if _is_under(source, ENGINES):
        return ORCHESTRATION
    if _is_under(source, KERNEL):
        return ENGINES + ORCHESTRATION
    return ()


def _current_violations():
    found = set()
    for path in _source_files():
        source = _module_name(path)
        forbidden = _forbidden_targets(source)
        for module in _imported_modules(path):
            if _is_under(module, forbidden):
                found.add((source, module))
    return found


def test_no_new_layer_violation():
    assert _current_violations() - KNOWN_VIOLATIONS == set()


def test_known_violations_are_still_present():
    assert KNOWN_VIOLATIONS - _current_violations() == set()
