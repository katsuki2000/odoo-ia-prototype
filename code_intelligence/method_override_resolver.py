"""
method_override_resolver.py

Resolves method overrides and applies structural checks (unguarded super, 
unchecked relational chains). Uses AST for deterministic checks and an optional 
LLM layer for interpretation.
"""

import ast
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import networkx as nx

from code_intelligence.utils import format_file_link
from code_intelligence.semgrep_locks_analyzer import (
    analyze_python_security_locks,
    extract_method_security_constraints,
)
from core.evidence import Evidence, EvidenceSourceType, make_evidence

_logger = logging.getLogger(__name__)


@dataclass
class MethodOverrideSite:
    """One module's override of a given method in execution order."""
    module: str
    filepath: str
    lineno: int
    end_lineno: Optional[int] = None


@dataclass
class MethodOverrideChainResult:
    """
    Composed override-chain analysis: summary_text is byte-for-byte what
    analyze_method_override_chain() has always returned (str contract
    unchanged for the existing wrapper/tests), plus structured Evidence
    covering the facts this function itself computes (override sites,
    unguarded-super / unchecked-relational-chain findings per site).

    Security-lock findings (has_group/exception constraints) surfaced
    inline in summary_text via extract_method_security_constraints() are
    deliberately NOT duplicated here as Evidence -- they are already
    emitted by semgrep_locks_analyzer.analyze_python_security_locks()'s own
    Evidence when analyze_security_locks() runs on the same file; re-
    emitting them here would produce two Evidence objects for one fact.
    """
    summary_text: str
    evidence: List[Evidence] = field(default_factory=list)


def resolve_method_override_chain(
    G: nx.DiGraph, model_name: str, method_name: str
) -> List[MethodOverrideSite]:
    """Return every module overriding the given method in execution order."""
    method_node_id = f"method:{model_name}.{method_name}"
    if method_node_id not in G:
        return []

    raw_sites = G.nodes[method_node_id].get("override_sites", [])
    sites = [
        MethodOverrideSite(
            module=s.get("module", "unknown"),
            filepath=s.get("filepath", ""),
            lineno=s.get("lineno", 0),
            end_lineno=s.get("end_lineno"),
        )
        for s in raw_sites
    ]
    return list(reversed(sites))


def _branch_returns_or_raises(stmts: List[ast.stmt]) -> bool:
    """True if the last statement of a branch body is a Return or Raise."""
    if not stmts:
        return False
    return isinstance(stmts[-1], (ast.Return, ast.Raise))


_STATE_MUTATING_CALL_NAMES = {"write", "update", "unlink"}


def _branch_mutates_record_state(stmts: List[ast.stmt]) -> bool:
    """True if the branch mutates record state (attribute assignments or mutation calls)."""
    for stmt in stmts:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Attribute) for t in targets):
                    return True
            elif isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in _STATE_MUTATING_CALL_NAMES
                ):
                    return True
    return False


class _UnguardedSuperVisitor(ast.NodeVisitor):
    """
    Walks a single method body looking for unguarded super calls.
    Checks for a super() call occurring unconditionally after a conditional branch
    which mutated state without returning. Supports recordset-subtraction guards.
    """

    def __init__(self, method_name: str):
        self.method_name = method_name
        self._if_depth = 0
        self._for_loop_stack: List[str] = []
        self.non_returning_conditionals: List[tuple] = []
        self.unconditional_super_calls: List[tuple] = []

    def visit_For(self, node: ast.For):
        loop_var = self._filtered_source_name(node.iter)
        if loop_var:
            self._for_loop_stack.append(loop_var)
        self.generic_visit(node)
        if loop_var:
            self._for_loop_stack.pop()

    def visit_If(self, node: ast.If):
        if not _branch_returns_or_raises(node.body) and _branch_mutates_record_state(
            node.body
        ):
            condition_source = self._safe_unparse(node.test)
            loop_var = self._for_loop_stack[-1] if self._for_loop_stack else None
            self.non_returning_conditionals.append((node.lineno, condition_source, loop_var))
        self._if_depth += 1
        self.generic_visit(node)
        self._if_depth -= 1

    def visit_Call(self, node: ast.Call):
        if self._if_depth == 0 and self._is_super_call(node):
            excluded_var = self._extract_excluded_recordset_name(node.func.value)
            self.unconditional_super_calls.append((node.lineno, excluded_var))
        self.generic_visit(node)

    @staticmethod
    def _safe_unparse(node: ast.expr) -> str:
        try:
            return ast.unparse(node)
        except Exception:
            return "?"

    @staticmethod
    def _filtered_source_name(node: ast.expr) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        return None

    @staticmethod
    def _extract_excluded_recordset_name(super_call: ast.Call) -> Optional[str]:
        if len(super_call.args) < 2:
            return None
        expr = super_call.args[1]
        if (
            isinstance(expr, ast.BinOp)
            and isinstance(expr.op, ast.Sub)
            and isinstance(expr.left, ast.Name)
            and expr.left.id == "self"
            and isinstance(expr.right, ast.Name)
        ):
            return expr.right.id
        return None

    def _is_super_call(self, node: ast.Call) -> bool:
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != self.method_name:
            return False
        value = func.value
        return (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "super"
        )

    @staticmethod
    def _is_guarded_pairing(loop_var: Optional[str], excluded_var: Optional[str]) -> bool:
        return loop_var is not None and loop_var == excluded_var

    @property
    def has_pattern(self) -> bool:
        return any(
            super_ln > cond_ln and not self._is_guarded_pairing(loop_var, excluded_var)
            for cond_ln, _, loop_var in self.non_returning_conditionals
            for super_ln, excluded_var in self.unconditional_super_calls
        )

    def get_matching_conditions(self) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for cond_ln, cond_text, loop_var in self.non_returning_conditionals:
            genuinely_unguarded = any(
                super_ln > cond_ln and not self._is_guarded_pairing(loop_var, excluded_var)
                for super_ln, excluded_var in self.unconditional_super_calls
            )
            if genuinely_unguarded and cond_text not in seen:
                seen.add(cond_text)
                ordered.append(cond_text)
        return ordered


UNGUARDED_SUPER_WARNING_TEMPLATE = (
    "SUPER() NON GARD\u00c9: '{method_name}' (module '{module}') contient une "
    "branche conditionnelle (`{condition}`) qui modifie l'\u00e9tat sans `return` "
    "explicite, suivie d'un appel `super().{method_name}(...)` inconditionnel plus "
    "loin dans la m\u00e9thode. La logique de la classe parente va se r\u00e9appliquer sur "
    "TOUS les enregistrements, y compris ceux couverts par cette condition -- "
    "risque r\u00e9el qu'elle soit silencieusement annul\u00e9e. "
    "[Confiance: FAIBLE -- heuristique statique sur la forme exacte du contr\u00f4le de "
    "flux, ne d\u00e9tecte pas les gardes formul\u00e9es autrement]"
)


def detect_unguarded_super(
    source: str, filepath: str, method_name: str, target_lineno: int, module: str = ""
) -> Optional[str]:
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError as e:
        _logger.warning(
            "Could not parse %s for override-chain analysis: %s", filepath, e
        )
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

    visitor = _UnguardedSuperVisitor(method_name)
    for stmt in target_func.body:
        visitor.visit(stmt)

    if visitor.has_pattern:
        conditions = visitor.get_matching_conditions()
        condition_text = " / ".join(conditions) if conditions else "?"
        return UNGUARDED_SUPER_WARNING_TEMPLATE.format(
            method_name=method_name, module=module or "?", condition=condition_text
        )
    return None


_RELATIONAL_CHAIN_MIN_DEPTH = 4


def _attribute_chain_depth(node: ast.Attribute) -> int:
    """Count chained `.attr` accesses ending at this Attribute node."""
    depth = 0
    cur = node
    while isinstance(cur, ast.Attribute):
        depth += 1
        cur = cur.value
    return depth


def _attribute_chain_names(node: ast.Attribute) -> List[str]:
    """Collect every attribute name in a chain, base to tip."""
    names = []
    cur = node
    while isinstance(cur, ast.Attribute):
        names.append(cur.attr)
        cur = cur.value
    return list(reversed(names))


class _UncheckedRelationalChainVisitor(ast.NodeVisitor):

    def __init__(self):
        self.checked_names: set = set()
        self.long_chains: List[tuple] = []  # (lineno, dotted_path, names)

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
        _logger.warning(
            "Could not parse %s for relational-chain analysis: %s", filepath, e
        )
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
        "signal d'erreur. [Confiance: FAIBLE -- heuristique statique, ne "
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


def _build_override_chain_evidence_no_sites(model_name: str, method_name: str) -> List[Evidence]:
    return [make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=(
            f"Method '{model_name}.{method_name}' is not overridden across "
            f"multiple modules (single declaration, or method not found in "
            f"the graph)"
        ),
        source=f"override_chain:{model_name}:{method_name}:no_sites",
        value=0,
        confidence="HIGH",
        scope={},
    )]


def _build_override_chain_site_evidence(
    model_name: str, method_name: str, idx: int, total: int, site: MethodOverrideSite
) -> Evidence:
    scope: Dict[str, Any] = {}
    if site.lineno:
        scope["lineno"] = site.lineno
    return make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=(
            f"Method '{model_name}.{method_name}' is overridden by module "
            f"'{site.module}' (execution order position {idx}/{total})"
        ),
        source=f"override_chain:{model_name}:{method_name}:site:{site.module}",
        value=site.module,
        confidence="HIGH",
        scope=scope,
    )


def _build_override_chain_check_evidence(
    model_name: str, method_name: str, site: MethodOverrideSite,
    check_name: str, warning: Optional[str],
) -> Evidence:
    scope: Dict[str, Any] = {}
    if site.lineno:
        scope["lineno"] = site.lineno
    if warning:
        return make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"Module '{site.module}' override of "
                f"'{model_name}.{method_name}' has a {check_name} finding"
            ),
            source=f"override_chain:{model_name}:{method_name}:{check_name}:{site.module}",
            value=warning,
            confidence="LOW",
            scope=scope,
        )
    return make_evidence(
        source_type=EvidenceSourceType.CODE,
        claim=(
            f"Module '{site.module}' override of "
            f"'{model_name}.{method_name}' has no {check_name} finding"
        ),
        source=f"override_chain:{model_name}:{method_name}:{check_name}:{site.module}",
        value=None,
        confidence="HIGH",
        scope=scope,
    )


def _compose_compute_methods_overview(
    G: nx.DiGraph, model_name: str, llm=None
) -> MethodOverrideChainResult:
    """Compose an overview of all computed methods (_compute_*) on model_name
    and related sub-models (e.g. line model), prioritizing custom/extending modules
    that override or declare them, their execution chains, and source code links."""
    from collections import defaultdict

    methods_by_mod = defaultdict(list)
    line_model = f"{model_name}.line"
    evidence: List[Evidence] = []

    for n, d in G.nodes(data=True):
        if d.get("node_type") != "Method":
            continue
        m = d.get("model", "")
        name = d.get("name", "")
        if m in (model_name, line_model) and name.startswith("_compute_"):
            sites = d.get("override_sites", [])
            for s in sites:
                mod = s.get("module", "unknown")
                if mod not in ("base", "sale", "purchase", "account", "stock") or len(sites) > 1:
                    methods_by_mod[mod].append((m, name, s, sites))

    if not methods_by_mod:
        text = f"Aucune méthode calculée (_compute_*) surchargée trouvée pour '{model_name}'."
        return MethodOverrideChainResult(
            summary_text=text,
            evidence=_build_override_chain_evidence_no_sites(model_name, "compute"),
        )

    def _mod_sort_key(mod_name):
        items = methods_by_mod[mod_name]
        is_custom = any("/addons/" not in s.get("filepath", "") or "oca" in s.get("filepath", "") for _, _, s, _ in items)
        return (0 if is_custom else 1, mod_name)

    sorted_mods = sorted(methods_by_mod.keys(), key=_mod_sort_key)
    lines = [f"Méthodes calculées (_compute_*) surchargées ou définies pour '{model_name}' :"]

    for mod in sorted_mods:
        items = methods_by_mod[mod]
        model_items = [item for item in items if item[0] == model_name]
        if model_items:
            lines_with_nos = [s.get("lineno", 0) for _, _, s, _ in model_items if s.get("lineno")]
            end_lines = [s.get("end_lineno", s.get("lineno", 0)) for _, _, s, _ in model_items if s.get("end_lineno") or s.get("lineno")]
            min_line = min(lines_with_nos) if lines_with_nos else 0
            max_line = max(end_lines) if end_lines else 0
            fp = model_items[0][2].get("filepath", "")
            if min_line and max_line and fp:
                span_link = format_file_link(fp, min_line, max_line)
                lines.append(f"\nModule '{mod}' ({len(items)} méthodes calculées) -- Extrait principal : {span_link}")
            else:
                lines.append(f"\nModule '{mod}' ({len(items)} méthodes calculées) :")
        else:
            lines.append(f"\nModule '{mod}' ({len(items)} méthodes calculées) :")

        for m, name, s, all_sites in items:
            other_mods = [x.get("module") for x in all_sites if x.get("module") != mod]
            c_str = ", ".join(other_mods)
            cascade_info = f" (surcharge {c_str})" if other_mods else " (définition/conversion en calculée)"
            link = format_file_link(s.get("filepath", ""), s.get("lineno", 0), s.get("end_lineno", 0))
            prefix = f"[{m}] " if m != model_name else ""
            lines.append(f"  - {prefix}{name}{cascade_info} -- {link}")

            if m != model_name:
                p = Path(s.get("filepath", ""))
                if p.exists() and s.get("lineno"):
                    try:
                        code_lines = p.read_text(encoding="utf-8").splitlines()
                        sl = max(0, s["lineno"] - 1)
                        el = min(len(code_lines), (s.get("end_lineno") or s["lineno"]))
                        snippet = "\n    ".join(code_lines[sl:el])
                        lines.append(f"    Code {m}.{name}:\n    {snippet}")
                    except Exception:
                        pass

            site_obj = MethodOverrideSite(
                module=mod,
                filepath=s.get("filepath", ""),
                lineno=s.get("lineno", 0),
                end_lineno=s.get("end_lineno"),
            )
            evidence.append(
                _build_override_chain_site_evidence(m, name, 1, len(all_sites), site_obj)
            )

    return MethodOverrideChainResult(summary_text="\n".join(lines), evidence=evidence)


def _compose_method_override_chain(
    G: nx.DiGraph, model_name: str, method_name: str, llm=None
) -> MethodOverrideChainResult:
    if method_name.lower() in ("compute", "_compute", "_compute_*", "*", "all"):
        return _compose_compute_methods_overview(G, model_name, llm=llm)

    sites = resolve_method_override_chain(G, model_name, method_name)

    if not sites:
        text = (
            f"'{method_name}' n'est pas surchargée dans plusieurs modules pour "
            f"'{model_name}' (rien à composer -- une seule déclaration, ou méthode "
            f"introuvable dans le graphe)."
        )
        return MethodOverrideChainResult(
            summary_text=text,
            evidence=_build_override_chain_evidence_no_sites(model_name, method_name),
        )

    lines = [
        f"Cha\u00eene de surcharge de '{model_name}.{method_name}' "
        f"({len(sites)} modules, ordre d'ex\u00e9cution r\u00e9el, pas l'ordre de d\u00e9pendance):"
    ]

    warnings: List[str] = []
    snippets_for_llm: List[str] = []
    evidence: List[Evidence] = []

    for idx, site in enumerate(sites, start=1):
        link = format_file_link(site.filepath, site.lineno, site.end_lineno or site.lineno)
        lines.append(f"  {idx}. module '{site.module}' -- {link}")
        evidence.append(
            _build_override_chain_site_evidence(model_name, method_name, idx, len(sites), site)
        )

        p = Path(site.filepath)
        if not p.exists():
            continue
        source = p.read_text(encoding="utf-8")
        site_has_warning = False

        warning = detect_unguarded_super(
            source, site.filepath, method_name, site.lineno, module=site.module
        )
        evidence.append(_build_override_chain_check_evidence(
            model_name, method_name, site, "unguarded_super", warning
        ))
        if warning:
            warnings.append(warning)
            lines.append(f"     {warning}")
            site_has_warning = True

        relational_warning = detect_unchecked_relational_chain(
            source, site.filepath, method_name, site.lineno, module=site.module
        )
        evidence.append(_build_override_chain_check_evidence(
            model_name, method_name, site, "unchecked_relational_chain", relational_warning
        ))
        if relational_warning:
            warnings.append(relational_warning)
            lines.append(f"     {relational_warning}")
            site_has_warning = True

        security_analysis = analyze_python_security_locks(source, site.filepath)
        site_constraints = extract_method_security_constraints(
            security_analysis, site.lineno, site.end_lineno or site.lineno
        )
        for constraint in site_constraints:
            lines.append(f"     {constraint}")

        if not site_has_warning:
            lines.append(
                "     (aucun risque structurel d\u00e9tect\u00e9 par cette heuristique "
                "pour ce module -- pas de branche non garante ni de cha\u00eene "
                "relationnelle non v\u00e9rifi\u00e9e trouv\u00e9e)"
            )

        if site.end_lineno:
            snippet_lines = source.splitlines()[site.lineno - 1 : site.end_lineno]
            snippets_for_llm.append(
                f"# module '{site.module}' ({site.filepath}:L{site.lineno}-L{site.end_lineno})\n"
                + "\n".join(snippet_lines)
            )

    if warnings and llm is not None:
        interpretation = interpret_override_chain_with_llm(
            model_name, method_name, warnings, snippets_for_llm, llm
        )
        if interpretation:
            lines.append(
                f"  -> Interpr\u00e9tation LLM [confiance: {interpretation['confidence'].upper()}, "
                f"distincte de la confiance statique ci-dessus]: {interpretation['summary']}"
            )

    return MethodOverrideChainResult(summary_text="\n".join(lines), evidence=evidence)


def analyze_method_override_chain(
    G: nx.DiGraph, model_name: str, method_name: str, llm=None
) -> str:
    return _compose_method_override_chain(G, model_name, method_name, llm=llm).summary_text


def analyze_method_override_chain_with_evidence(
    G: nx.DiGraph, model_name: str, method_name: str, llm=None
) -> MethodOverrideChainResult:
    return _compose_method_override_chain(G, model_name, method_name, llm=llm)


_LLM_CONFIDENCE_CLOSED_SET = {"high", "medium", "low"}

_INTERPRETATION_SYSTEM_PROMPT = (
    "Tu es un analyste de code Odoo. Un premier passage automatique (analyse AST) a "
    "rep\u00e9r\u00e9 un appel `super()` inconditionnel apr\u00e8s une branche conditionnelle qui "
    "ne se termine pas directement par un `return`/`raise` \u00e0 son dernier statement -- "
    "CECI EST UN INDICE BRUT, PAS UN FAIT CONFIRM\u00c9. Cette heuristique statique ne "
    "v\u00e9rifie ni si la branche modifie r\u00e9ellement un champ de l'enregistrement, ni si "
    "un `raise`/`return` imbriqu\u00e9 plus loin dans la branche couvre d\u00e9j\u00e0 tous les cas -- "
    "elle peut donc se tromper. AVANT de r\u00e9sumer une cons\u00e9quence, VERIFIE toi-m\u00eame sur "
    "le code fourni : (1) la branche \u00e9crit-elle vraiment un champ de l'enregistrement "
    "(`rec.champ = ...`, `.write(...)`, etc.) sur au moins un chemin qui NE se termine PAS "
    "par un `return`/`raise` ? Si NON (ex: la branche ne fait que lever une exception ou ne "
    "rien faire), il n'y a RIEN que le `super()` puisse \u00e9craser -- dis-le explicitement, "
    "n'invente aucune cons\u00e9quence n\u00e9gative, et mets confidence \u00e0 'low'. (2) Si la "
    "pr\u00e9misse tient r\u00e9ellement, r\u00e9sume en une phrase la cons\u00e9quence m\u00e9tier concr\u00e8te "
    "(quel comportement l'utilisateur observera r\u00e9ellement). Ta r\u00e9ponse doit toujours "
    "\u00eatre coh\u00e9rente avec tout message d'erreur (UserError/ValidationError) visible dans "
    "le m\u00eame extrait de code -- si un `raise` bloque explicitement un cas, ne dis JAMAIS "
    "que ce cas est approuv\u00e9 ou que la restriction est annul\u00e9e. R\u00e9ponds STRICTEMENT en "
    "JSON, sans aucun texte avant ou apr\u00e8s, au format exact: "
    '{"summary": "...", "confidence": "high"|"medium"|"low"}. '
    "N'utilise JAMAIS une autre valeur de confidence que high, medium, ou low."
)


def interpret_override_chain_with_llm(
    model_name: str,
    method_name: str,
    warnings: List[str],
    snippets: List[str],
    llm,
) -> Optional[dict]:
    if not warnings or llm is None:
        return None

    detected = "\n".join(f"- {w}" for w in warnings)
    code_block = "\n\n".join(snippets)
    prompt = (
        f"M\u00e9thode '{model_name}.{method_name}', cha\u00eene de surcharge "
        f"(ordre d'ex\u00e9cution r\u00e9el):\n```python\n{code_block}\n```\n\n"
        f"Indice brut de l'analyse statique (AST) -- \u00e0 v\u00e9rifier, pas \u00e0 prendre pour "
        f"acquis:\n{detected}\n\n"
        "V\u00e9rifie d'abord si cet indice tient reellement (la branche mute-t-elle un champ "
        "de l'enregistrement sans que ce chemin ne se termine par return/raise ?), puis "
        "r\u00e9sume en une phrase claire le comportement m\u00e9tier r\u00e9ellement observ\u00e9 (pas le "
        "code), et indique ta confiance."
    )

    try:
        from langchain_core.messages import SystemMessage, HumanMessage

        response = llm.invoke([
            SystemMessage(content=_INTERPRETATION_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        raw = (response.content or "").strip()
    except Exception as e:
        _logger.warning(
            "LLM interpretation call failed for %s.%s: %s", model_name, method_name, e
        )
        return None

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        _logger.warning(
            "LLM interpretation returned non-JSON response for %s.%s: %r",
            model_name, method_name, raw,
        )
        return None

    if not isinstance(parsed, dict):
        return None

    summary = parsed.get("summary")
    confidence = parsed.get("confidence")

    if confidence not in _LLM_CONFIDENCE_CLOSED_SET:
        _logger.warning(
            "LLM interpretation returned out-of-set confidence for %s.%s: %r",
            model_name, method_name, confidence,
        )
        return None

    if not summary or not isinstance(summary, str):
        return None

    return {"summary": summary, "confidence": confidence}
