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


def resolve_method_override_chain(
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


_STATE_MUTATING_CALL_NAMES = {"write", "update", "unlink"}


def _branch_mutates_record_state(stmts: List[ast.stmt]) -> bool:
    """True if the branch body writes to a record/self attribute (e.g.
    `rec.field = ...`, `self.field += ...`) or calls a known state-mutating
    method (`.write(`, `.update(`, `.unlink(`) anywhere within it, including
    nested blocks (e.g. a nested `if` that raises on one path and does
    nothing on the other).

    Root cause fix (2026-08-25, Bloc 9 hallucination gap, sections 139-141):
    a branch that only computes a LOCAL variable (`n2 = rec.employee_id...`)
    and then conditionally `raise`s is not actually at risk of being
    silently clobbered by an unconditional super() call afterwards -- there
    is no record state for super() to re-apply logic on top of. Local-
    variable-only assignments (target is a plain ast.Name, not an
    ast.Attribute) deliberately do NOT count as mutation for this reason.
    Confirmed against the real custom_hr_leave_workflow.action_approve case
    (hr_leave.py): the outer `if` body ends in a nested `if ...: raise` with
    no `else`, so the previous last-statement-only check considered it
    'non-returning' even though the only thing it can do besides raising is
    nothing at all -- no field ever gets written. Confirmed still correctly
    flags the real VIP bug (custom_credit_note_approval_vip.action_valider_avoir,
    which assigns `rec.avoir_valide_par_id` / `rec.avoir_niveau_appro`, both
    Attribute targets).
    """
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

    Recordset-subtraction guard (found 2026-08-25, real corpus,
    hr_expense.AccountMove._compute_commercial_partner_id, section 151 of
    contexte.txt): a conditional inside `for x in <name>:` that mutates
    state is NOT actually at risk if the later super() call is of the
    explicit 2-arg form `super(Class, self - <name>)` -- Odoo's recordset
    subtraction here explicitly excludes the very records the branch just
    mutated from what super() will re-process. This is a real guard, just
    expressed as recordset arithmetic instead of return/raise, and is
    tracked separately per (conditional, super-call) pairing rather than
    globally, so a genuinely unguarded conditional elsewhere in the same
    method (paired with a DIFFERENT super() call, or one that excludes a
    different/no recordset) is still correctly flagged.

    This remains a heuristic, not full control-flow/data-flow analysis: it
    does not verify the super() call and the conditional branch actually
    touch the same fields, it only recognizes the exact `self - <bare
    name>` subtraction shape (not an inline `.filtered(...)` never bound
    to a name, nor any other guard expressed some other way, e.g. an early
    top-level `if not cond: return` before the super() call). Confidence
    is fixed 'low' by the caller, same convention as
    server_action_analyzer.py's static regex layer.
    """

    def __init__(self, method_name: str):
        self.method_name = method_name
        self._if_depth = 0
        self._for_loop_stack: List[str] = []
        # (lineno, condition_source, enclosing_loop_var) -- condition_source
        # is the unparsed `if` test, e.g. "rec.avoir_vip_exempt" or
        # "rec.amount_total > 20000", kept so the caller can cite the actual
        # literal/threshold instead of only describing the structural shape
        # (Bloc 9 gap, 2026-08-07). enclosing_loop_var is the bare name this
        # conditional's `for` loop iterates over (e.g. "own_expense_moves"),
        # or None if the branch isn't inside a `for x in <bare name>:` loop
        # -- used to match against a later super() call's excluded
        # recordset (2026-08-25, section 151).
        self.non_returning_conditionals: List[tuple] = []
        # (lineno, excluded_recordset_name) -- excluded_recordset_name is
        # the <name> in `super(Class, self - <name>)`, or None for a
        # zero-arg super() call or any other second-argument shape.
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
        """If a `for x in <expr>:` loop iterates directly over a bare
        name (e.g. `for move in own_expense_moves:`), return that name --
        the candidate 'excluded subset' variable a later
        `super(Class, self - <name>)` call might reference. Returns None
        for any other iterable shape (inline `.filtered(...)` never bound
        to a name, method calls, etc.) -- deliberately conservative, a
        guard expressed that way is a false negative we accept."""
        if isinstance(node, ast.Name):
            return node.id
        return None

    @staticmethod
    def _extract_excluded_recordset_name(super_call: ast.Call) -> Optional[str]:
        """For a `super(Class, expr)` call (explicit 2-arg form), return
        the name of the recordset excluded from `self` if `expr` is
        exactly `self - <name>` (ast.BinOp, Sub, left=Name('self'),
        right=a bare Name) -- the one confirmed real Odoo idiom for
        guarding a later super() call against re-processing records
        already mutated by an earlier branch. Returns None for zero-arg
        super() or any other second-argument shape -- deliberately
        conservative, same discipline as the rest of this module: a guard
        expressed some other way is a false negative we accept, not a
        case we try to guess at."""
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
        """True if this specific (conditional, super-call) pairing is
        guarded by recordset subtraction -- the conditional's loop
        iterates over the exact same bare name the super() call excludes
        via `self - <name>`."""
        return loop_var is not None and loop_var == excluded_var

    @property
    def has_pattern(self) -> bool:
        return any(
            super_ln > cond_ln and not self._is_guarded_pairing(loop_var, excluded_var)
            for cond_ln, _, loop_var in self.non_returning_conditionals
            for super_ln, excluded_var in self.unconditional_super_calls
        )

    def get_matching_conditions(self) -> List[str]:
        """Condition texts of every non-returning conditional that is
        actually followed by a GENUINELY unguarded super() call (i.e. not
        excluded via recordset subtraction) -- the literal(s) to cite as
        "the exemption/threshold that can get silently overridden",
        deduplicated, in source order."""
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
    "\u26a0\ufe0f SUPER() NON GARD\u00c9: '{method_name}' (module '{module}') contient une "
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
        conditions = visitor.get_matching_conditions()
        condition_text = " / ".join(conditions) if conditions else "?"
        return UNGUARDED_SUPER_WARNING_TEMPLATE.format(
            method_name=method_name, module=module or "?", condition=condition_text
        )
    return None


_RELATIONAL_CHAIN_MIN_DEPTH = 4  # e.g. self.env.user.employee_id.parent_id.parent_id.user_id


def _attribute_chain_depth(node: ast.Attribute) -> int:
    """Count chained `.attr` accesses ending at this Attribute node."""
    depth = 0
    cur = node
    while isinstance(cur, ast.Attribute):
        depth += 1
        cur = cur.value
    return depth


def _attribute_chain_names(node: ast.Attribute) -> List[str]:
    """Collect every attribute name in a chain, base to tip, e.g.
    `self.env.user.employee_id` -> ['env', 'user', 'employee_id']."""
    names = []
    cur = node
    while isinstance(cur, ast.Attribute):
        names.append(cur.attr)
        cur = cur.value
    return list(reversed(names))


class _UncheckedRelationalChainVisitor(ast.NodeVisitor):
    """
    rules.md Regle 3 ("Validation des champs relationnels"): never access a
    Many2one's attributes without first checking it's set. Flags a long
    chained attribute access (>= _RELATIONAL_CHAIN_MIN_DEPTH hops, e.g.
    `self.env.user.employee_id.parent_id.parent_id.user_id`) that is never
    preceded, anywhere else in the same function, by an `if` testing any of
    the same attribute/name tokens -- meaning nothing guards against an
    intermediate hop (e.g. `parent_id`) resolving to an empty recordset,
    which silently evaluates to False/empty instead of raising, and can
    propagate a wrong "nobody notified" result with no error signal at all.

    Deliberately conservative, same discipline as _UnguardedSuperVisitor:
    false negatives (a guard expressed some other way, in a different
    variable, or via try/except) are preferred over false positives.
    """

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
        # Avoid double-counting nested Attribute nodes as separate chains,
        # but still visit sibling children (call args, etc).
        for child in ast.iter_child_nodes(node):
            if child is not node.value:
                self.visit(child)


def _find_guarding_condition_for_helper_call(
    func: ast.FunctionDef, helper_name: str
) -> Optional[str]:
    """Best-effort: if `func` calls `self.<helper_name>(...)` somewhere
    inside an `if` block, return the unparsed source of the innermost
    enclosing `if`'s test -- the literal condition/threshold (e.g.
    "rec.amount_total > 20000") that actually has to be true to reach the
    helper, so a finding inside that helper can cite the real trigger
    instead of only the risky shape. Returns None if the call is
    unconditional or not found (never raises)."""
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
    """
    Deterministic AST heuristic (Bloc 9 gap, found 2026-08-06 replaying the
    Q1.1 "cascade avoirs" benchmark E2E as part of the 8-remaining-modules
    review). detect_unguarded_super only catches the "unconditional
    super() after a non-returning conditional" security-lock shape -- it
    has nothing to say about a plain business-logic override (calls
    super() FIRST, then adds its own field assignment, which is a SAFE
    override pattern on its own) that itself violates rules.md Regle 3 by
    chaining several Many2one hops with no existence check
    (custom_credit_note_approval_regional._get_directeur_regional:
    `self.env.user.employee_id.parent_id.parent_id.user_id`, silently
    False if the hierarchy is incomplete -- exactly the ground-truth risk
    ("Risque: N+2 non gere si vide") the adversarial benchmark expects
    surfaced, and which never reached the synthesis LLM because no tool
    extracted it at all: analyze_security_locks only looks for
    UserError/ValidationError/sudo/getattr, and the unguarded-super
    detector doesn't fire here since this override IS guarded (super()
    runs first, unconditionally, which is the correct pattern).

    Also scans any same-class helper method the target method calls by
    name (one level, e.g. `self._get_x()`) -- the real bug here lives in
    a helper, not inline in the overridden method itself.
    """
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
            # Chain lives in a helper, not the overridden method itself --
            # find the literal condition/threshold in the caller that
            # actually gates reaching it (e.g. "rec.amount_total > 20000"),
            # so the finding cites the real trigger, not just the shape.
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
        "\u26a0\ufe0f CHAINE RELATIONNELLE NON V\u00c9RIFI\u00c9E (R\u00e8gle 3): "
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
    """
    Cheap deterministic pre-filter (no LLM, no full composite tool call):
    for each candidate method name, resolve its override chain and run
    BOTH detect_unguarded_super and detect_unchecked_relational_chain over
    every site's source. Returns only the method names where at least one
    site matches either pattern.

    Renamed from find_methods_with_unguarded_super (2026-08-06, Bloc 9 gap
    review) when detect_unchecked_relational_chain was added alongside it
    -- keeping the old unguarded-super-only name after widening its scope
    would have been misleading at every call site.

    Exists because find_methods_with_override_cascade (ci_agent_tools.py)
    only checks "is this method overridden by more than one module" --
    true for dozens of ordinary methods on a shared model like
    account.move (write, create, action_post...) with zero real finding.
    Dispatching the full LLM-backed analyze_method_override_chain for
    every one of them burns hops and Groq tokens for no signal (confirmed
    2026-08-06: Q1.1/Q1.2/Q5.1 all hit 17 hops once the forced dispatch
    was wired on the cascade-only guard alone). This second, cheaper
    filter narrows the forced dispatch down to methods with an actual
    finding, same discipline as the other J8/J9 structural guards
    (find_server_action_nodes): deterministic AST check first, the
    expensive tool (and its LLM interpretation) only on top of a real hit.
    """
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


# Backward-compatible aliases, kept only for any external caller not yet
# updated -- new code should use find_methods_with_override_risk_findings.
find_methods_with_unguarded_super_and_relational_risk = find_methods_with_override_risk_findings
# 2026-08-07: test_method_override_chain.py (written by a concurrent
# session the same day as the risk-findings rename) still imports the
# original pre-rename name directly -- restoring it here rather than
# editing the test, since the test's own name ("unguarded_super") is the
# more accurate description of the specific real-corpus case it locks in.
find_methods_with_unguarded_super = find_methods_with_override_risk_findings


def analyze_method_override_chain(
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
    sites = resolve_method_override_chain(G, model_name, method_name)

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
        site_has_warning = False

        warning = detect_unguarded_super(
            source, site.filepath, method_name, site.lineno, module=site.module
        )
        if warning:
            warnings.append(warning)
            lines.append(f"     {warning}")
            site_has_warning = True

        relational_warning = detect_unchecked_relational_chain(
            source, site.filepath, method_name, site.lineno, module=site.module
        )
        if relational_warning:
            warnings.append(relational_warning)
            lines.append(f"     {relational_warning}")
            site_has_warning = True

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

    return "\n".join(lines)


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
