"""
code_intelligence/semgrep_locks_analyzer.py

Stories S2.5 & S2.6: Security lock & dynamic uncertainty analysis for Python code.
  - S2.5: Detects hardcoded email/login lists (e.g. _VALIDATEURS_EXCEPTIONNELS) and exact UserError/ValidationError exception strings.
  - S2.6: Detects dynamic dispatch (getattr, eval, exec) and marks results with confidence='low'.
"""

import ast
import re
from dataclasses import dataclass, field
from typing import List, Set, Optional

import logging

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
    # Index-aligned with exception_messages, same convention as
    # exception_conditions. When the enclosing condition is (or starts
    # with, as the first `and` operand) a bare truthiness check on a
    # relational field/attribute -- e.g. `if rec.demande_achat_liee_id and
    # rec.demande_achat_liee_id.montant_estime > 2000:` -- this holds the
    # unparsed text of that guarding operand (e.g.
    # "rec.demande_achat_liee_id"), else "". See
    # _detect_link_guard_field's docstring for why this exists.
    exception_guard_fields: List[str] = field(default_factory=list)
    has_dynamic_dispatch: bool = False
    dynamic_dispatch_types: List[str] = field(default_factory=list)
    required_groups: List[str] = field(default_factory=list)
    security_warnings: List[str] = field(default_factory=list)
    confidence: str = "high"
    summary_text: str = ""


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
        # Bloc 9 gap (module 5/8, custom_asset_loan, 2026-08-10): index-aligned
        # with exception_messages -- the unparsed source of every `if` test
        # enclosing the corresponding raise, outer to inner, joined with
        # " and " (ALL must hold for the raise to trigger), or "" if the
        # raise sits outside any `if`. Same pattern as _UnguardedSuperVisitor /
        # _find_guarding_condition_for_helper_call in method_override_resolver.py
        # (Module 1/8's fix for the analogous gap on `super()` calls) --
        # without this, a purely conditional rule (e.g. "only applies if a
        # linked purchase request exceeds 2000e") reaches the synthesis LLM
        # as a bare message with no visible condition, and gets reasoned
        # about as if it were unconditional (bloc9-05c-no-link-trap).
        self.exception_conditions: List[str] = []
        # Index-aligned with exception_messages -- see
        # PythonSecurityLockAnalysis.exception_guard_fields docstring.
        self.exception_guard_fields: List[str] = []
        self.dynamic_dispatches: List[str] = []
        self.required_groups: List[str] = []
        self._if_test_stack: List[ast.expr] = []

    def visit_If(self, node: ast.If):
        self._if_test_stack.append(node.test)
        self.generic_visit(node)
        self._if_test_stack.pop()

    def _current_condition_text(self) -> str:
        """Unparsed source of every `if` test currently enclosing the node
        being visited, outer to inner. Same limitation as method_override_
        resolver.py's _GuardFinder: does not distinguish the `if` body from
        its `orelse` (a raise reached only via `else` would be mis-described
        as gated by the positive condition) -- deliberately conservative,
        not full control-flow analysis."""
        if not self._if_test_stack:
            return ""
        parts = []
        for test in self._if_test_stack:
            try:
                parts.append(ast.unparse(test))
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
        shape means the WHOLE condition -- and therefore whatever it
        guards -- can only ever be true when that first operand is truthy
        (typically: a real linked record is present). Returns the unparsed
        text of that guarding operand, checking outer tests first (the
        outermost guard is the binding constraint), or "" if no enclosing
        `if` has this shape.

        Bloc 9 gap (2026-08-10, bloc9-05c-no-link-trap): the raw condition
        text alone (via _current_condition_text) already contains enough
        information to derive this deterministically, but a live run
        showed the synthesis LLM misreading the short-circuit direction
        even with the condition quoted to it verbatim -- it concluded the
        rule "applies when NOT linked", the exact inverse of what the code
        does. This makes the derived conclusion an explicit, computed fact
        instead of leaving Python boolean short-circuit reasoning to the
        small model. Deliberately conservative (same discipline as
        _extract_amount in rag/graph.py): only the clear, unambiguous shape
        is flagged -- a guard expressed any other way (e.g. `if not rec.x:
        return` early-exit, or a helper method) is silently not detected,
        which is safe (no annotation is added, not a wrong one).

        Bloc 9 gap (module 5/8 fix rerun, 2026-08-11, cross-module
        contamination on bloc9-05c-no-link-trap): the original second
        branch matched any `if` test that was merely "not a Compare and
        not a BoolOp" -- meant to catch a bare `if rec.linked_id:`, but
        that negative shape also matches an `ast.UnaryOp` such as
        `if not (user_ok or email_ok):` (custom_purchase_request's own,
        unrelated approval gate). A live run on a question mentioning both
        "mise a disposition" and "demande d'achat" -- so both models were
        legitimately in scope for the same turn -- produced a fabricated
        "[GARDE DE LIEN: si 'not (user_ok or email_ok)' est vide/absent..."
        annotation for custom_purchase_request: nonsensical, since a
        boolean authorization check can never be "vide/absent" the way a
        Many2one field can. This was not the cross-module scoping bug
        fixed on 2026-08-11 in rag/graph.py (_scoped_raw_tool_output) --
        that fix correctly kept this observation in scope, because the
        question genuinely referenced both models; the bug was in THIS
        function misclassifying an unrelated boolean condition as a link-
        guard field in the first place. Narrowed to a positive-shape check
        (ast.Attribute or ast.Name only) instead of the negative one --
        the only two node types a bare relational-field/attribute
        truthiness check can actually be.
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
        """Detect hardcoded email/login lists assigned to variables like _VALIDATEURS_EXCEPTIONNELS."""
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

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Detect dynamic dispatch calls: getattr, eval, exec."""
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

        if func_name in {"getattr", "eval", "exec"}:
            if func_name not in self.dynamic_dispatches:
                self.dynamic_dispatches.append(func_name)

        # Bloc 9 gap (2026-08-10, bloc9-01a-business): a Python-level guard
        # like `self.env.user.has_group('account.group_account_manager')`
        # gates the raise right above it, but the technical group xmlid it
        # checks was never extracted anywhere in the pipeline -- only the
        # UserError/ValidationError message text was. A question asking
        # WHO can approve something got the human-readable message
        # ("un responsable comptable") but never the technical group
        # identifier backing it, which is exactly what a governance answer
        # needs to be actionable/citable. Detects `<expr>.has_group('xml.id')`
        # regardless of the receiver expression (self.env.user, rec.create_uid,
        # etc.) -- only the literal string argument is captured.
        if isinstance(node.func, ast.Attribute) and node.func.attr == "has_group":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                group_xmlid = node.args[0].value
                if group_xmlid not in self.required_groups:
                    self.required_groups.append(group_xmlid)

        self.generic_visit(node)


def analyze_python_security_locks(code: str, filepath: str) -> PythonSecurityLockAnalysis:
    """
    Analyze Python source code for hardcoded security locks, exception messages,
    and dynamic dispatch uncertainties.
    """
    result = PythonSecurityLockAnalysis(filepath=filepath)

    if not code or not code.strip():
        result.summary_text = f"File '{filepath}': Empty code."
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
        result.dynamic_dispatch_types = visitor.dynamic_dispatches
        result.required_groups = visitor.required_groups

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
                # Regex fallback can't recover the enclosing condition (no
                # control-flow structure available from a flat pattern
                # match) -- kept index-aligned with "" rather than left
                # unset, same convention as the AST path.
                result.exception_conditions.append("")
                result.exception_guard_fields.append("")

    if not result.required_groups:
        for group_xmlid in _HAS_GROUP_PATTERN.findall(code):
            if group_xmlid not in result.required_groups:
                result.required_groups.append(group_xmlid)

    # 3. Categorize findings
    if result.hardcoded_logins:
        result.has_hardcoded_logins = True
        result.security_warnings.append(
            f"⚠️ LOGINS/EMAILS EN DUR: Fichier '{filepath}' contient des adresses privilégies "
            f"codées en dur: {result.hardcoded_logins}. Contourne le système de droits standard Odoo."
        )

    if result.dynamic_dispatch_types:
        result.has_dynamic_dispatch = True
        result.confidence = "low"
        result.security_warnings.append(
            f"⚠️ DISPATCH DYNAMIQUE: Fichier '{filepath}' utilise {', '.join(result.dynamic_dispatch_types)}(). "
            f"La logique d'exécution exacte dépend de paramètres dynamiques et ne peut pas être "
            f"classifiée statiquement avec certitude. [Confiance: FAIBLE]"
        )

    # 4. Summary Text
    from code_intelligence.utils import format_file_link, SENSITIVE_BYPASS_MARKER
    line_count = max(1, len(code.splitlines()))
    file_link = format_file_link(filepath, 1, line_count)
    # 2026-08-10 (Bloc 9 gap, module 7/8, bloc9-07 raw check): `result.confidence`
    # is stored in English ("low"/"high") -- test_s2_5_semgrep_locks.py already
    # asserts on that exact string, so the stored value itself must not change.
    # But every OTHER low-confidence message in this codebase (the dynamic-
    # dispatch inline warning right above, the override-chain warnings in
    # method_override_resolver.py, etc.) renders "[Confiance: FAIBLE]" in
    # French -- only this one header line fell back to a raw .upper() of the
    # English value, producing the inconsistent "[Confiance: LOW]". "high"
    # deliberately left as-is (translating it too is a separate, broader,
    # out-of-scope change nothing currently expects or checks for).
    _confidence_label = "FAIBLE" if result.confidence == "low" else result.confidence.upper()
    lines = [f"Analyse des verrous Python ({file_link}) [Confiance: {_confidence_label}]:"]
    if result.has_hardcoded_logins:
        # Bloc 7 (J23-24, revised): the ONLY line in this analyzer's output
        # that describes an actual bypass (privileged access granted
        # outside Odoo's normal ir.rule/ACL system) rather than ordinary
        # governance/uncertainty info -- marked so authorization_gate.py
        # redacts just this line for unprivileged requesters, not the
        # whole analysis (which also covers legitimate approval-flow
        # questions that must stay answerable for everyone).
        lines.append(f"  - {SENSITIVE_BYPASS_MARKER} Logins/Emails privilégies en dur: {result.hardcoded_logins}")
    if result.exception_messages:
        lines.append(f"  - Messages de verrous (UserError/ValidationError):")
        # exception_conditions/exception_guard_fields are index-aligned with
        # exception_messages (see SecurityLockASTVisitor); pad defensively
        # in case some caller ever builds a PythonSecurityLockAnalysis by
        # hand without them, same discipline as the rest of this function
        # never trusting shape.
        conditions = result.exception_conditions or [""] * len(result.exception_messages)
        guard_fields = result.exception_guard_fields or [""] * len(result.exception_messages)
        for msg, condition, guard_field in zip(result.exception_messages, conditions, guard_fields):
            if condition:
                # Module 5/8 fix (2026-08-10): without this, a raise gated by
                # an `if` (e.g. "only if a linked purchase request exceeds
                # 2000e") reached the synthesis LLM as a bare, apparently
                # unconditional message -- it then reasoned the rule always
                # applies (bloc9-05c-no-link-trap), the exact inverse of the
                # ground truth documented in that adversarial check script.
                lines.append(f"    * \"{msg}\" (condition : {condition})")
            else:
                lines.append(f"    * \"{msg}\"")
            if guard_field:
                # Module 5/8 fix, part 2 (2026-08-10, bloc9-05c-no-link-trap):
                # spelling out the short-circuit CONCLUSION explicitly and
                # deterministically, rather than leaving the small synthesis
                # LLM to derive it from the raw condition text -- a live run
                # showed it misreading the short-circuit direction even with
                # the condition quoted to it verbatim. Also machine-parseable
                # by rag/graph.py's _backfill_link_guard_clarifications so
                # the correct conclusion reaches the final answer
                # unconditionally, independent of what the LLM said.
                lines.append(
                    f"      [GARDE DE LIEN: si '{guard_field}' est vide/absent (aucun "
                    f"enregistrement lie), cette condition est FAUSSE par court-circuit "
                    f"Python (evaluation de gauche a droite d'un 'and') -- la regle ci-dessus "
                    f"NE S'APPLIQUE PAS dans ce cas, quel que soit le reste de la condition.]"
                )
    if result.required_groups:
        groups_joined = ', '.join(result.required_groups)
        lines.append(f"  - Groupe(s) technique(s) requis detecte(s) (has_group): {groups_joined}")
    if result.has_dynamic_dispatch:
        lines.append(f"  - Incertitude dynamique ({', '.join(result.dynamic_dispatch_types)}): revue manuelle recommandée")

    if not result.security_warnings and not result.exception_messages:
        lines.append("  - Aucun verrou spécifique ni incertitude dynamique détecté.")

    result.summary_text = "\n".join(lines)
    return result


def python_source_has_security_findings(code: str, filepath: str = "<unknown>") -> bool:
    """
    Cheap boolean wrapper around analyze_python_security_locks: True if the
    file has ANY finding (hardcoded login/email list, UserError/
    ValidationError message, dynamic dispatch, or a has_group() check).

    Deliberately reuses the full analysis rather than re-implementing a
    faster short-circuit scan -- two independent detectors for "does this
    file have a lock" is exactly the F-08/J7 duplication mistake this
    codebase already paid for once. The full analysis is already cheap
    (one AST parse + a few regex passes, no LLM), so there's no real
    performance reason to duplicate it.

    Added 2026-08-10 (Bloc 9, module 5 gap): used as the structural
    pre-dispatch guard for analyser_verrous_securite in rag/graph.py, so
    that forced dispatch no longer depends on the question's wording
    matching _APPROVAL_PATTERN -- questions like "pourquoi je n'arrive pas
    à démarrer..." or "la règle s'applique-t-elle..." contain none of that
    vocabulary, so the keyword-only trigger silently never fired and the
    LLM was left to pick a tool on its own, which it did wrong (hallucinated
    a malformed method name instead of finding the real Python lock).
    """
    result = analyze_python_security_locks(code, filepath)
    return bool(
        result.hardcoded_logins
        or result.exception_messages
        or result.dynamic_dispatch_types
        or result.required_groups
    )
