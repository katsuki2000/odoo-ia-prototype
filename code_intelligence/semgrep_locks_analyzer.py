"""
code_intelligence/semgrep_locks_analyzer.py

Stories S2.5 & S2.6: Security lock & dynamic uncertainty analysis for Python code.
  - S2.5: Detects hardcoded email/login lists (e.g. _VALIDATEURS_EXCEPTIONNELS) and exact UserError/ValidationError exception strings.
  - S2.6: Detects dynamic dispatch (getattr, eval, exec) and marks results with confidence='low'.
"""

import ast
import copy
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Optional

import logging

from core.evidence import Evidence, EvidenceSourceType, make_evidence

_logger = logging.getLogger(__name__)


@dataclass
class PythonSecurityLockAnalysis:
    """Result of analyzing Python model code for security locks and uncertainties."""
    filepath: str
    has_hardcoded_logins: bool = False
    hardcoded_logins: List[str] = field(default_factory=list)
    exception_messages: List[str] = field(default_factory=list)
    # Index-aligned with exception_messages -- see SecurityLockASTVisitor's
    # __init__ comment. Always the same length as exception_messages.
    exception_conditions: List[str] = field(default_factory=list)

    exception_guard_fields: List[str] = field(default_factory=list)
    # Index-aligned with exception_messages -- source line of the `raise`
    # statement itself. 0 means unknown (regex-fallback path, no AST
    # available). Lets a caller attribute one exception finding to one
    # specific method override site -- see extract_method_security_constraints.
    exception_linenos: List[int] = field(default_factory=list)
    has_dynamic_dispatch: bool = False
    dynamic_dispatch_types: List[str] = field(default_factory=list)
    required_groups: List[str] = field(default_factory=list)
 
    required_group_methods: List[str] = field(default_factory=list)
    # Index-aligned with required_groups -- source line of the has_group()
    # call itself. Same 0-means-unknown convention as exception_linenos.
    required_group_linenos: List[int] = field(default_factory=list)
    security_warnings: List[str] = field(default_factory=list)
    confidence: str = "high"
    summary_text: str = ""

    # B1 (todo/contexte.txt section 452+, tool 7/24, 2/4 Analyse CI):
    # structured Evidence produced at the source -- one per security-relevant
    # category actually checked, always asserted explicitly whether found or
    # not (same convention as the 5 Composites CI and analyze_server_actions).
    # Unlike analyze_server_actions (confidence="LOW" fixed tool-wide),
    # confidence here follows the epistemic nature of each fact: HIGH for
    # directly observed AST facts (hardcoded_logins/exception_messages/
    # required_groups), LOW only for a positive dynamic_dispatch finding
    # (HIGH when explicitly absent) -- see _build_security_lock_evidence()
    # docstring for the full arbitrage. Populated by
    # analyze_python_security_locks() below.
    evidence: List[Evidence] = field(default_factory=list)


# Regex fallback for email pattern detection
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_GETATTR_PATTERN = re.compile(r"\bgetattr\s*\(")
_EVAL_PATTERN = re.compile(r"\beval\s*\(")
_EXEC_PATTERN = re.compile(r"\bexec\s*\(")
_EXCEPTION_RAISE_PATTERN = re.compile(r"raise\s+(?:ValidationError|UserError)\s*\(\s*([\"'].*?[\"'])", re.DOTALL)


_HAS_GROUP_PATTERN = re.compile(r"has_group\s*\(\s*['\"]([\w.]+)['\"]\s*\)")


class SecurityLockASTVisitor(ast.NodeVisitor):
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.hardcoded_logins: List[str] = []
        self.exception_messages: List[str] = []

        self.exception_conditions: List[str] = []
        # Index-aligned with exception_messages -- see
        # PythonSecurityLockAnalysis.exception_guard_fields docstring.
        self.exception_guard_fields: List[str] = []
        # Index-aligned with exception_messages -- see
        # PythonSecurityLockAnalysis.exception_linenos docstring.
        self.exception_linenos: List[int] = []
        self.dynamic_dispatches: List[str] = []
        self.required_groups: List[str] = []
        # Index-aligned with required_groups -- see
        # PythonSecurityLockAnalysis.required_group_methods docstring.
        self.required_group_methods: List[str] = []
        # Index-aligned with required_groups -- see
        # PythonSecurityLockAnalysis.required_group_linenos docstring.
        self.required_group_linenos: List[int] = []
        self._if_test_stack: List[ast.expr] = []

        self._function_stack: List[str] = []
        # Stack of {name: defining_expr} per enclosing function scope, used
        # to resolve opaque local boolean variables (e.g. `email_ok`) back
        # to their source expression when rendering condition text -- see
        # _resolve_local_names below. One dict per function nesting level,
        # pushed/popped alongside _function_stack.
        self._local_var_defs: List[Dict[str, ast.expr]] = []

    def visit_If(self, node: ast.If):
        self._if_test_stack.append(node.test)
        self.generic_visit(node)
        self._if_test_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._function_stack.append(node.name)
        self._local_var_defs.append({})
        self.generic_visit(node)
        self._local_var_defs.pop()
        self._function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._function_stack.append(node.name)
        self._local_var_defs.append({})
        self.generic_visit(node)
        self._local_var_defs.pop()
        self._function_stack.pop()

    def _current_method_name(self) -> str:
        """Innermost enclosing def/async def name, or "" at module level
        (e.g. a has_group() call in a class-body default or a bare module-
        level function)."""
        return self._function_stack[-1] if self._function_stack else ""

    def _resolve_local_names(self, node: ast.expr) -> ast.expr:
        """
        Return a copy of `node` with any Name(Load) reference to a locally
        assigned variable (e.g. `email_ok`) substituted by a copy of its
        defining expression, one level only -- names appearing INSIDE the
        substituted expression itself are never further resolved. This
        matches the rest of this file's deliberately conservative, not
        full-data-flow stance (see _current_condition_text/_detect_link_
        guard_field docstrings).

        Exists because a raw `ast.unparse()` of a condition like
        `rec.montant_estime > 10000 and not email_ok` leaves `email_ok`
        opaque to a downstream LLM reader, which then has to guess what it
        gates on -- and can guess wrong (e.g. attributing it to an
        unrelated has_group() check seen in a sibling condition). Resolving
        it to its actual source expression (`self.env.user.login in
        rec._VALIDATEURS_EXCEPTIONNELS`) removes the guess entirely.
        """
        if not self._local_var_defs:
            return node
        local_map = self._local_var_defs[-1]
        if not local_map:
            return node

        class _NameResolver(ast.NodeTransformer):
            def visit_Name(inner_self, n: ast.Name):
                if isinstance(n.ctx, ast.Load) and n.id in local_map:
                    return copy.deepcopy(local_map[n.id])
                return n

        return _NameResolver().visit(copy.deepcopy(node))

    def _current_condition_text(self) -> str:
        """Unparsed source of every `if` test currently enclosing the node
        being visited, outer to inner, with locally-assigned names resolved
        to their defining expression (see _resolve_local_names). Same
        limitation as method_override_resolver.py's _GuardFinder: does not
        distinguish the `if` body from its `orelse` (a raise reached only
        via `else` would be mis-described as gated by the positive
        condition) -- deliberately conservative, not full control-flow
        analysis."""
        if not self._if_test_stack:
            return ""
        parts = []
        for test in self._if_test_stack:
            try:
                parts.append(ast.unparse(self._resolve_local_names(test)))
            except Exception:
                parts.append("?")
        return " and ".join(parts)

    def _detect_link_guard_field(self) -> str:
        """
        Detect whether any `if` test currently enclosing the node being
        visited is -- or begins with, as the first operand of an `and` --
        a bare truthiness check on a relational field/attribute (NOT a
        Compare, e.g. not `x > 2000` or `x == y`), such as
        `if rec.demande_achat_liee_id:` or
        `if rec.demande_achat_liee_id and rec.demande_achat_liee_id.montant_estime > 2000:`.

        Python's `and` short-circuits on a falsy first operand, so this
        shape means the whole condition can only be true when that first operand is truthy.
        Returns the unparsed text of that guarding operand, checking outer tests first,
        or "" if no enclosing `if` has this shape.
        """
        for test in self._if_test_stack:  # outer to inner: outermost guard binds first
            if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And) and test.values:
                first = test.values[0]
                if not isinstance(first, ast.Compare):
                    try:
                        return ast.unparse(first)
                    except Exception:
                        return ""
            elif isinstance(test, (ast.Attribute, ast.Name)):
                try:
                    return ast.unparse(test)
                except Exception:
                    return ""
        return ""

    def visit_Assign(self, node: ast.Assign):
        """Detect hardcoded email/login lists assigned to variables like _VALIDATEURS_EXCEPTIONNELS,
        and record simple single-target local assignments (within a function scope) so that
        _resolve_local_names can later substitute opaque names like `email_ok` back to their
        defining expression in rendered condition text."""
        # Check if right-hand side is a List/Tuple of string literals
        if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            str_elts = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    str_elts.append(elt.value)

            # Check if elements contain emails
            emails = [s for s in str_elts if _EMAIL_PATTERN.match(s)]
            if emails:
                self.hardcoded_logins.extend(emails)

        if (
            self._local_var_defs
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            self._local_var_defs[-1][node.targets[0].id] = node.value

        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise):
        """Extract exact UserError and ValidationError exception message strings."""
        if isinstance(node.exc, ast.Call):
            func_name = ""
            if isinstance(node.exc.func, ast.Name):
                func_name = node.exc.func.id
            elif isinstance(node.exc.func, ast.Attribute):
                func_name = node.exc.func.attr

            if func_name in {"ValidationError", "UserError"}:
                message = None
                if node.exc.args:
                    first_arg = node.exc.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                        message = first_arg.value.strip()
                    elif isinstance(first_arg, ast.BinOp) and isinstance(first_arg.left, ast.Constant):
                        # e.g. "Msg %s" % var -> extract template
                        if isinstance(first_arg.left.value, str):
                            message = first_arg.left.value.strip()
                    elif isinstance(first_arg, ast.JoinedStr):
                        # f-string -> extract literal text parts
                        parts = [p.value for p in first_arg.values if isinstance(p, ast.Constant) and isinstance(p.value, str)]
                        if parts:
                            message = "".join(parts).strip()

                if message is not None:
                    self.exception_messages.append(message)
                    # Index-aligned with exception_messages -- see __init__
                    # docstring comment above for why this exists.
                    self.exception_conditions.append(self._current_condition_text())
                    self.exception_guard_fields.append(self._detect_link_guard_field())
                    self.exception_linenos.append(node.lineno)

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Detect dynamic dispatch calls: getattr, eval, exec."""
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

        if func_name in {"getattr", "eval", "exec"}:
            if func_name not in self.dynamic_dispatches:
                self.dynamic_dispatches.append(func_name)

        if isinstance(node.func, ast.Attribute) and node.func.attr == "has_group":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                group_xmlid = node.args[0].value
                if group_xmlid not in self.required_groups:
                    self.required_groups.append(group_xmlid)
                    # Index-aligned with the append above (first-seen
                    # dedup) -- see required_group_methods docstring.
                    self.required_group_methods.append(self._current_method_name())
                    self.required_group_linenos.append(node.lineno)

        self.generic_visit(node)


def _build_security_lock_evidence(
    filepath: str,
    hardcoded_logins: List[str],
    exception_messages: List[str],
    exception_conditions: List[str],
    exception_guard_fields: List[str],
    exception_linenos: List[int],
    required_groups: List[str],
    required_group_methods: List[str],
    required_group_linenos: List[int],
    dynamic_dispatch_types: List[str],
) -> List[Evidence]:
    """
    B1 (todo/contexte.txt section 452+, tool 7/24, 2/4 Analyse CI): structured
    Evidence produced at the source, one per security-relevant category
    actually checked, always asserted explicitly whether found or not (same
    "fait explicite si negatif" convention as the 5 Composites CI and
    analyze_server_actions).

    Unlike analyze_server_actions (fixed confidence="LOW" throughout, an
    arbitrage specific to that tool's data-driven, runtime-modifiable input),
    confidence here follows the epistemic nature of each *fact*, not a single
    tool-wide constant:
      - hardcoded_logins / exception_messages / required_groups: HIGH --
        these are directly observed AST facts (a literal string list, a
        raise statement, a has_group() call) parsed once from real module
        source. What conclusion a caller draws from the surrounding control
        flow is a separate question from whether the fact itself was
        observed with certainty.
      - dynamic_dispatch: LOW when present -- PythonSecurityLockAnalysis.
        confidence already degrades to "low" in this case, because getattr/
        eval/exec make the actual runtime behaviour unknowable statically --
        but HIGH when explicitly absent, since the *absence* of getattr/
        eval/exec in the source is itself a certain, directly observed fact
        (same asymmetry the tool-level confidence field already encodes).

    scope carries only keys that are actually known -- no lineno=0, no
    method="" placeholder (rule agreed for this tool): "lineno" for
    exception/group findings when the AST path produced a real line number
    (0 means the regex-fallback path ran instead, no AST available), "method"
    for group findings when the enclosing method was resolved (has_group()
    at module level, or an unresolved enclosing scope, leaves it "").
    hardcoded_logins and dynamic_dispatch carry no such per-occurrence
    location data (the visitor doesn't track it for these two categories),
    so their scope stays {} -- an honestly empty scope, not an artificial one.
    """
    evidence: List[Evidence] = []

    # 1. hardcoded_logins
    if hardcoded_logins:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"File '{filepath}' contains hardcoded privileged login(s)/"
                f"email(s): {hardcoded_logins}"
            ),
            source=f"security_lock:{filepath}:hardcoded_logins",
            value=hardcoded_logins,
            confidence="HIGH",
            scope={},
        ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"File '{filepath}' contains no hardcoded login/email",
            source=f"security_lock:{filepath}:hardcoded_logins",
            value=None,
            confidence="HIGH",
            scope={},
        ))

    # 2. exception_messages (one Evidence per raise site)
    if exception_messages:
        conditions = exception_conditions or [""] * len(exception_messages)
        guard_fields = exception_guard_fields or [""] * len(exception_messages)
        linenos = exception_linenos or [0] * len(exception_messages)
        for i, (message, condition, guard_field, lineno) in enumerate(
            zip(exception_messages, conditions, guard_fields, linenos)
        ):
            claim = f"File '{filepath}' raises UserError/ValidationError \"{message}\""
            if condition:
                claim += f" (condition: {condition})"
            if guard_field:
                claim += f" (link-guarded on '{guard_field}')"
            scope: Dict[str, Any] = {}
            if lineno:
                scope["lineno"] = lineno
            # Disambiguator: real lineno when known, else the list index --
            # the regex-fallback path (lineno=0) still needs a unique source
            # per finding, and list order is stable for identical input code.
            disambiguator = lineno if lineno else i
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=claim,
                source=f"security_lock:{filepath}:exception:{disambiguator}",
                value=message,
                confidence="HIGH",
                scope=scope,
            ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=(
                f"File '{filepath}' raises no UserError/ValidationError with "
                f"an extractable message"
            ),
            source=f"security_lock:{filepath}:exception",
            value=None,
            confidence="HIGH",
            scope={},
        ))

    # 3. required_groups (one Evidence per has_group() requirement)
    if required_groups:
        methods = required_group_methods or [""] * len(required_groups)
        linenos = required_group_linenos or [0] * len(required_groups)
        for group_xmlid, method_name, lineno in zip(required_groups, methods, linenos):
            claim = f"File '{filepath}' requires group '{group_xmlid}' via has_group()"
            if method_name:
                claim += f" in method '{method_name}()'"
            scope: Dict[str, Any] = {}
            if method_name:
                scope["method"] = method_name
            if lineno:
                scope["lineno"] = lineno
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=claim,
                source=f"security_lock:{filepath}:group:{group_xmlid}",
                value=group_xmlid,
                confidence="HIGH",
                scope=scope,
            ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"File '{filepath}' contains no has_group() requirement",
            source=f"security_lock:{filepath}:group",
            value=None,
            confidence="HIGH",
            scope={},
        ))

    # 4. dynamic_dispatch (one Evidence per pattern type, or one negative fact)
    if dynamic_dispatch_types:
        for pattern_name in dynamic_dispatch_types:
            evidence.append(make_evidence(
                source_type=EvidenceSourceType.CODE,
                claim=(
                    f"File '{filepath}' uses dynamic dispatch via {pattern_name}(), "
                    f"not statically classifiable"
                ),
                source=f"security_lock:{filepath}:dynamic_dispatch:{pattern_name}",
                value=pattern_name,
                confidence="LOW",
                scope={},
            ))
    else:
        evidence.append(make_evidence(
            source_type=EvidenceSourceType.CODE,
            claim=f"File '{filepath}' uses no dynamic dispatch (getattr/eval/exec)",
            source=f"security_lock:{filepath}:dynamic_dispatch",
            value=None,
            confidence="HIGH",
            scope={},
        ))

    return evidence


def analyze_python_security_locks(code: str, filepath: str) -> PythonSecurityLockAnalysis:
    """
    Analyze Python source code for hardcoded security locks, exception messages,
    and dynamic dispatch uncertainties.
    """
    result = PythonSecurityLockAnalysis(filepath=filepath)

    if not code or not code.strip():
        result.summary_text = f"File '{filepath}': Empty code."
        result.evidence = _build_security_lock_evidence(
            filepath,
            hardcoded_logins=[],
            exception_messages=[],
            exception_conditions=[],
            exception_guard_fields=[],
            exception_linenos=[],
            required_groups=[],
            required_group_methods=[],
            required_group_linenos=[],
            dynamic_dispatch_types=[],
        )
        return result

    # 1. AST Parsing
    try:
        tree = ast.parse(code, filename=filepath)
        visitor = SecurityLockASTVisitor(filepath)
        visitor.visit(tree)

        result.hardcoded_logins = visitor.hardcoded_logins
        result.exception_messages = visitor.exception_messages
        result.exception_conditions = visitor.exception_conditions
        result.exception_guard_fields = visitor.exception_guard_fields
        result.exception_linenos = visitor.exception_linenos
        result.dynamic_dispatch_types = visitor.dynamic_dispatches
        result.required_groups = visitor.required_groups
        result.required_group_methods = visitor.required_group_methods
        result.required_group_linenos = visitor.required_group_linenos

    except SyntaxError:
        _logger.warning("AST parse failed for %s, falling back to regex analysis", filepath)

    # 2. Regex fallback / reinforcement
    if not result.hardcoded_logins:
        emails = _EMAIL_PATTERN.findall(code)
        if emails:
            # Filter unique emails
            seen = set()
            for e in emails:
                if e not in seen:
                    seen.add(e)
                    result.hardcoded_logins.append(e)

    if not result.dynamic_dispatch_types:
        for pattern, name in [(_GETATTR_PATTERN, "getattr"), (_EVAL_PATTERN, "eval"), (_EXEC_PATTERN, "exec")]:
            if pattern.search(code):
                result.dynamic_dispatch_types.append(name)

    if not result.exception_messages:
        for match in _EXCEPTION_RAISE_PATTERN.finditer(code):
            raw_msg = match.group(1).strip("'\"")
            if raw_msg and raw_msg not in result.exception_messages:
                result.exception_messages.append(raw_msg)

                result.exception_conditions.append("")
                result.exception_guard_fields.append("")
                result.exception_linenos.append(0)

    if not result.required_groups:
        for group_xmlid in _HAS_GROUP_PATTERN.findall(code):
            if group_xmlid not in result.required_groups:
                result.required_groups.append(group_xmlid)

                result.required_group_methods.append("")
                result.required_group_linenos.append(0)

    result.evidence = _build_security_lock_evidence(
        filepath,
        hardcoded_logins=result.hardcoded_logins,
        exception_messages=result.exception_messages,
        exception_conditions=result.exception_conditions,
        exception_guard_fields=result.exception_guard_fields,
        exception_linenos=result.exception_linenos,
        required_groups=result.required_groups,
        required_group_methods=result.required_group_methods,
        required_group_linenos=result.required_group_linenos,
        dynamic_dispatch_types=result.dynamic_dispatch_types,
    )

    # 3. Categorize findings
    if result.hardcoded_logins:
        result.has_hardcoded_logins = True
        result.security_warnings.append(
            f" LOGINS/EMAILS EN DUR: Fichier '{filepath}' contient des adresses privilégies "
            f"codées en dur: {result.hardcoded_logins}. Contourne le système de droits standard Odoo."
        )

    if result.dynamic_dispatch_types:
        result.has_dynamic_dispatch = True
        result.confidence = "low"
        result.security_warnings.append(
            f" DISPATCH DYNAMIQUE: Fichier '{filepath}' utilise {', '.join(result.dynamic_dispatch_types)}(). "
            f"La logique d'exécution exacte dépend de paramètres dynamiques et ne peut pas être "
            f"classifiée statiquement avec certitude. [Confiance: FAIBLE]"
        )

    # 4. Summary Text
    from code_intelligence.utils import format_file_link, SENSITIVE_BYPASS_MARKER
    line_count = max(1, len(code.splitlines()))
    file_link = format_file_link(filepath, 1, line_count)

    _confidence_label = "FAIBLE" if result.confidence == "low" else result.confidence.upper()
    lines = [f"Analyse des verrous Python ({file_link}) [Confiance: {_confidence_label}]:"]
    if result.has_hardcoded_logins:

        lines.append(f"  - {SENSITIVE_BYPASS_MARKER} Logins/Emails privilégies en dur: {result.hardcoded_logins}")
    if result.exception_messages:
        lines.append(f"  - Security lock messages (UserError/ValidationError):")

        conditions = result.exception_conditions or [""] * len(result.exception_messages)
        guard_fields = result.exception_guard_fields or [""] * len(result.exception_messages)
        for msg, condition, guard_field in zip(result.exception_messages, conditions, guard_fields):
            if condition:
                lines.append(f"    * \"{msg}\" (condition : {condition})")
            else:
                lines.append(f"    * \"{msg}\"")
            if guard_field:

                lines.append(
                    f"      [GARDE DE LIEN: si '{guard_field}' est vide/absent (aucun "
                    f"enregistrement lie), cette condition est FAUSSE par court-circuit "
                    f"Python (evaluation de gauche a droite d'un 'and') -- la regle ci-dessus "
                    f"NE S'APPLIQUE PAS dans ce cas, quel que soit le reste de la condition.]"
                )
    if result.required_groups:
        groups_joined = ', '.join(result.required_groups)
        lines.append(f"  - Groupe(s) technique(s) requis detecte(s) (has_group): {groups_joined}")

        methods = result.required_group_methods or [""] * len(result.required_groups)
        for group_xmlid, method_name in zip(result.required_groups, methods):
            if method_name:
                lines.append(f"    * has_group('{group_xmlid}') se trouve dans la methode '{method_name}()' -- ne pas l'attribuer a une autre methode sans le verifier explicitement dans le code source.")
            else:
                lines.append(f"    * has_group('{group_xmlid}') se trouve hors de toute methode (niveau module), ou sa methode englobante n'a pas pu etre determinee.")
    if result.has_dynamic_dispatch:
        lines.append(f"  - Incertitude dynamique ({', '.join(result.dynamic_dispatch_types)}): revue manuelle recommandée")

    if not result.security_warnings and not result.exception_messages:
        lines.append("  - Aucun verrou spécifique ni incertitude dynamique détecté.")

    result.summary_text = "\n".join(lines)
    return result


def python_source_has_security_findings(code: str, filepath: str = "<unknown>") -> bool:
    """
    Checks if the Python code has any security findings:
    hardcoded logins/emails, exception messages, dynamic dispatch, or required groups.
    """
    result = analyze_python_security_locks(code, filepath)
    return bool(
        result.hardcoded_logins
        or result.exception_messages
        or result.dynamic_dispatch_types
        or result.required_groups
    )


def extract_method_security_constraints(
    analysis: PythonSecurityLockAnalysis, lineno: int, end_lineno: int
) -> List[str]:
    """
    Filter a file-level PythonSecurityLockAnalysis down to only the security
    lock findings (has_group requirements, UserError/ValidationError guards)
    physically located within [lineno, end_lineno] -- i.e. inside one specific
    method override site, not the whole file.

    Exists because analyze_security_locks (the composite tool) reports every
    security finding in a file as one flat, file-scoped dump: when a file
    defines several methods, or a method is overridden alongside other
    methods in the same module, that dump does not say which finding belongs
    to which override. analyze_method_override_chain already resolves the
    real per-module execution order and line ranges (MethodOverrideSite) --
    this function lets it attach each site's own security constraints
    directly, instead of leaving that correlation to the reader (or the
    synthesis LLM) to guess from a global, file-scoped dump.

    Findings with an unknown line (0, from the regex-fallback path where no
    AST was parsable) are excluded -- they cannot be attributed to any
    specific site, and attaching them to every site would misattribute them
    more often than it would help.
    """
    constraints: List[str] = []

    for group_xmlid, method_name, group_lineno in zip(
        analysis.required_groups,
        analysis.required_group_methods,
        analysis.required_group_linenos,
    ):
        if group_lineno and lineno <= group_lineno <= end_lineno:
            location = f"dans '{method_name}()'" if method_name else "a cette ligne"
            constraints.append(
                f"VERROU RATTACHE AU SITE: has_group('{group_xmlid}') requis {location}."
            )

    exception_conditions = analysis.exception_conditions or [""] * len(analysis.exception_messages)
    exception_guard_fields = analysis.exception_guard_fields or [""] * len(analysis.exception_messages)
    for message, condition, guard_field, exc_lineno in zip(
        analysis.exception_messages,
        exception_conditions,
        exception_guard_fields,
        analysis.exception_linenos,
    ):
        if exc_lineno and lineno <= exc_lineno <= end_lineno:
            text = f'VERROU RATTACHE AU SITE: "{message}"'
            if condition:
                text += f" (condition : {condition})"
            if guard_field:
                text += (
                    f" [GARDE DE LIEN: si '{guard_field}' est vide/absent, cette "
                    f"condition est FAUSSE par court-circuit Python -- la regle NE "
                    f"S'APPLIQUE PAS dans ce cas.]"
                )
            constraints.append(text)

    return constraints
