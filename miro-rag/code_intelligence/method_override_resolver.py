"""
code_intelligence/method_override_resolver.py

Bloc 9 gap, found 2026-08-06 while investigating adversarial Q1.2
("avoir VIP"). The agent answered evasively because it resolved
account.move.action_valider_avoir on the base module
(custom_credit_note_approval) only, never following the _inherit cascade
into custom_credit_note_approval_regional / _vip. Reading the real code
then surfaced a genuine bug in the VIP module itself: it sets a
conditional exemption without an early `return`, then unconditionally
calls `super().action_valider_avoir()` -- which re-applies the base
class's 5000e/manager threshold to VIP records too, silently nullifying
the exemption.

Two layers, mirroring the J8 pattern (server_action_analyzer.py):
  1. Deterministic layer (this file's core): composes the override chain
     in real EXECUTION order from the knowledge graph's per-method
     `override_sites` (graph_builder.py), and an AST-based heuristic
     detector for the unguarded-super pattern. Confidence is always a
     fixed value per finding type, never inferred by an LLM.
  2. Bounded LLM interpretation layer (interpret_override_chain_with_llm):
     ONLY invoked when the deterministic detector already found something
     to interpret. Summarizes the concrete behavioral consequence in one
     sentence, with a confidence tag restricted to a closed set. Never
     replaces or hides the deterministic finding, same discipline as
     server_action_analyzer.interpret_server_action_with_llm.
"""

import ast
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import networkx as nx

from code_intelligence.utils import format_file_link

_logger = logging.getLogger(__name__)


@dataclass
class MethodOverrideSite:
    """One module's override of a given method, in real EXECUTION order
    (first to run first). Odoo builds each model's final class by
    prepending the LAST-loaded/most-dependent module's class ahead of
    earlier ones in the MRO, so the module loaded last runs FIRST and its
    super() call cascades down towards the module loaded first (usually
    the one holding `_name`). Execution order is therefore the reverse of
    manifest-dependency load order (which is how override_sites is stored
    on the graph -- see graph_builder.py)."""
    module: str
    filepath: str
    lineno: int
    end_lineno: Optional[int] = None


def resoudre_chaine_surcharge_methode(
    G: nx.DiGraph, model_name: str, method_name: str
) -> List[MethodOverrideSite]:
    """
    Deterministic: for a given model + method name, return every module
    that overrides that exact method, ordered by REAL execution order.

    Reads override_sites directly off the graph's Method node (populated
    in manifest-dependency load order by graph_builder.py) -- no LLM, no
    file parsing. Returns an empty list if the method isn't found, or is
    only declared in a single module (nothing to compose an order for).
    """
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
    return list(reversed(sites))  # load order (as stored) -> execution order


def _branch_returns_or_raises(stmts: List[ast.stmt]) -> bool:
    """True if the LAST statement of a branch body is a Return or Raise --
    a proxy for "this branch exits the method instead of falling through
    to whatever comes after it"."""
    if not stmts:
        return False
    return isinstance(stmts[-1], (ast.Return, ast.Raise))


class _UnguardedSuperVisitor(ast.NodeVisitor):
    """
    Walks a single method body looking for the exact shape found in the
    real VIP bug:
      (a) an `if` (at any nesting depth, e.g. inside a `for`) whose body
          sets state and does NOT end in return/raise -- it falls through
          instead of exiting the conditional branch, and
      (b) a call shaped `super().<method_name>(...)` that sits OUTSIDE any
          `if` (so it always executes regardless of (a)'s condition) AND
          whose source line comes AFTER at least one such non-returning
          conditional -- i.e. it can re-run parent logic on top of state
          the conditional branch just set, potentially clobbering it.

    This is a heuristic, not full control-flow/data-flow analysis: it
    does not verify the super() call and the conditional branch actually
    touch the same fields, and it will not recognize a guard expressed
    some other way (e.g. an early top-level `if not cond: return` before
    the super() call). Scoped intentionally to this one concrete, already
    -confirmed-real bug shape. Confidence is fixed 'low' by the caller,
    same convention as server_action_analyzer.py's static regex layer.
    """

    def __init__(self, method_name: str):
        self.method_name = method_name
        self._if_depth = 0
        self.non_returning_conditional_linenos: List[int] = []
        self.unconditional_super_call_linenos: List[int] = []

    def visit_If(self, node: ast.If):
        if not _branch_returns_or_raises(node.body):
            self.non_returning_conditional_linenos.append(node.lineno)
        self._if_depth += 1
        self.generic_visit(node)
        self._if_depth -= 1

    def visit_Call(self, node: ast.Call):
        if self._if_depth == 0 and self._is_super_call(node):
            self.unconditional_super_call_linenos.append(node.lineno)
        self.generic_visit(node)

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

    @property
    def has_pattern(self) -> bool:
        return any(
            super_ln > cond_ln
            for cond_ln in self.non_returning_conditional_linenos
            for super_ln in self.unconditional_super_call_linenos
        )


UNGUARDED_SUPER_WARNING_TEMPLATE = (
    "\u26a0\ufe0f SUPER() NON GARD\u00c9: '{method_name}' (module '{module}') contient une "
    "branche conditionnelle qui modifie l'\u00e9tat sans `return` explicite, suivie d'un "
    "appel `super().{method_name}(...)` inconditionnel plus loin dans la m\u00e9thode. "
    "La logique de la classe parente va se r\u00e9appliquer sur TOUS les enregistrements, "
    "y compris ceux couverts par la branche conditionnelle -- risque r\u00e9el que la "
    "condition soit silencieusement annul\u00e9e. "
    "[Confiance: FAIBLE -- heuristique statique sur la forme exacte du contr\u00f4le de "
    "flux, ne d\u00e9tecte pas les gardes formul\u00e9es autrement]"
)


def detect_unguarded_super(
    source: str, filepath: str, method_name: str, target_lineno: int, module: str = ""
) -> Optional[str]:
    """
    Deterministic AST heuristic. Returns a warning string if the method
    definition starting at target_lineno in `source` matches the
    unguarded-super pattern, None otherwise (including on parse failure or
    if the method can't be located -- never crashes the caller, same
    defensive style as the rest of the extractors)."""
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
        return UNGUARDED_SUPER_WARNING_TEMPLATE.format(
            method_name=method_name, module=module or "?"
        )
    return None


def find_methods_with_unguarded_super(
    G: nx.DiGraph, model_name: str, method_names: List[str]
) -> List[str]:
    """
    Cheap deterministic pre-filter (no LLM, no full composite tool call):
    for each candidate method name, resolve its override chain and run
    detect_unguarded_super over every site's source. Returns only the
    method names where at least one site actually matches the unguarded-
    super pattern.

    Exists because find_methods_with_override_cascade (ci_agent_tools.py)
    only checks "is this method overridden by more than one module" --
    true for dozens of ordinary methods on a shared model like
    account.move (write, create, action_post...) with zero unguarded-super
    issue. Dispatching the full LLM-backed analyser_chaine_surcharge_methode
    for every one of them burns hops and Groq tokens for no signal
    (confirmed 2026-08-06: Q1.1/Q1.2/Q5.1 all hit 17 hops once the forced
    dispatch was wired on the cascade-only guard alone -- and Q1.2 still
    answered evasively because the real finding was buried in noise). This
    second, cheaper filter narrows the forced dispatch down to methods
    with an actual finding, same discipline as the other J8/J9 structural
    guards (find_server_action_nodes): deterministic AST check first, the
    expensive tool (and its LLM interpretation) only on top of a real hit.
    """
    hits: List[str] = []
    for method_name in method_names:
        sites = resoudre_chaine_surcharge_methode(G, model_name, method_name)
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
            ):
                hits.append(method_name)
                break
    return hits


def analyser_chaine_surcharge_methode(
    G: nx.DiGraph, model_name: str, method_name: str, llm=None
) -> str:
    """
    Composite tool: resolves the override chain for model_name.method_name
    in real execution order, reads each site's exact source slice, runs
    the deterministic unguarded-super detector on each, and (only if a
    warning was found) requests a bounded LLM interpretation. Always
    source-cited (module + file + line range per site), per project rule
    ("sourcing obligatoire sur tout \u00e9l\u00e9ment produit").
    """
    sites = resoudre_chaine_surcharge_methode(G, model_name, method_name)

    if not sites:
        return (
            f"'{method_name}' n'est pas surcharg\u00e9e dans plusieurs modules pour "
            f"'{model_name}' (rien \u00e0 composer -- une seule d\u00e9claration, ou m\u00e9thode "
            f"introuvable dans le graphe)."
        )

    lines = [
        f"Cha\u00eene de surcharge de '{model_name}.{method_name}' "
        f"({len(sites)} modules, ordre d'ex\u00e9cution r\u00e9el, pas l'ordre de d\u00e9pendance):"
    ]

    warnings: List[str] = []
    snippets_for_llm: List[str] = []

    for idx, site in enumerate(sites, start=1):
        link = format_file_link(site.filepath, site.lineno, site.end_lineno or site.lineno)
        lines.append(f"  {idx}. module '{site.module}' -- {link}")

        p = Path(site.filepath)
        if not p.exists():
            continue
        source = p.read_text(encoding="utf-8")

        warning = detect_unguarded_super(
            source, site.filepath, method_name, site.lineno, module=site.module
        )
        if warning:
            warnings.append(warning)
            lines.append(f"     {warning}")

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

    return "\n".join(lines)


_LLM_CONFIDENCE_CLOSED_SET = {"high", "medium", "low"}

_INTERPRETATION_SYSTEM_PROMPT = (
    "Tu es un analyste de code Odoo. Un premier passage automatique (analyse AST) a "
    "d\u00e9j\u00e0 d\u00e9tect\u00e9 qu'une m\u00e9thode surcharg\u00e9e en cascade sur plusieurs modules contient "
    "un appel `super()` inconditionnel apr\u00e8s une branche conditionnelle sans `return`. "
    "Ta t\u00e2che est UNIQUEMENT d'interpr\u00e9ter et r\u00e9sumer en une phrase la cons\u00e9quence "
    "m\u00e9tier concr\u00e8te (quel comportement l'utilisateur observera r\u00e9ellement), et "
    "d'indiquer ta confiance dans cette interpr\u00e9tation. R\u00e9ponds STRICTEMENT en JSON, "
    "sans aucun texte avant ou apr\u00e8s, au format exact: "
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
    """
    Bounded LLM interpretation layer, only called when the deterministic
    detector already found at least one warning. Mirrors
    server_action_analyzer.interpret_server_action_with_llm's discipline:
    fixed JSON shape, closed confidence set, graceful degradation to None
    on any malformed response, out-of-set confidence, or call failure --
    never crashes, never guesses, never silently trusts an out-of-spec
    response.
    """
    if not warnings or llm is None:
        return None

    detected = "\n".join(f"- {w}" for w in warnings)
    code_block = "\n\n".join(snippets)
    prompt = (
        f"M\u00e9thode '{model_name}.{method_name}', cha\u00eene de surcharge "
        f"(ordre d'ex\u00e9cution r\u00e9el):\n```python\n{code_block}\n```\n\n"
        f"Constat d\u00e9tect\u00e9 par analyse statique (AST):\n{detected}\n\n"
        "R\u00e9sume en une phrase claire le comportement m\u00e9tier r\u00e9ellement observ\u00e9 "
        "(pas le code), et indique ta confiance."
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
