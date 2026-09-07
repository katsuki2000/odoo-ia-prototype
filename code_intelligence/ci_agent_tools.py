"""
code_intelligence/ci_agent_tools.py

LangChain @tool wrappers for all 9 Code Intelligence tools (5 composite + 4 auxiliary).
Bound to LLM inside code_intelligence_agent via bind_tools().
All code and docstrings in English per project coding rules.
"""

import json
import logging
from typing import Optional

from pathlib import Path

from langchain_core.tools import tool
from code_intelligence.utils import resolve_model_xmlref
from code_intelligence.business_resolver import resolve_business_term

_logger = logging.getLogger(__name__)

_GRAPH_REF = None
_LLM_REF = None


def set_graph_ref(G):
    """Set global knowledge graph reference for tool wrappers."""
    global _GRAPH_REF
    _GRAPH_REF = G


def set_llm_ref(llm):
    """Set global LLM reference for tool wrappers needing bounded interpretation (J8)."""
    global _LLM_REF
    _LLM_REF = llm


def _require_graph():
    """Guard: ensure knowledge graph is initialized before tool execution."""
    if _GRAPH_REF is None:
        raise RuntimeError("Knowledge graph not initialized. Call set_graph_ref(G) first.")
    return _GRAPH_REF


WILDCARD_MODEL_ERROR_MSG = (
    "Erreur : le modèle doit être spécifié explicitement (les jokers '*' et "
    "l'extraction globale de tous les modèles ne sont pas autorisés par la politique de sécurité J32-J33)."
)


def _is_wildcard_model(model_name: str) -> bool:
    """J32-J33: Detect wildcard or bulk model queries."""
    clean = (model_name or "").strip().lower()
    return clean in {"*", "%", "all", "tous", "tous les modèles", "all models", ""}


def _resolve_model_param(model_name: str) -> str:
    """
    J3 structural guard: ensure composite/auxiliary tools always operate on a
    real technical model name, even when the LLM supplies a business term
    instead of the exact Odoo model (e.g. "avoir" instead of "account.move").

    This is a SAFETY NET, not the primary resolution path -- the primary
    path is the [BUSINESS TERM RESOLVER S2.0] hint injected into the system
    prompt once per question in code_intelligence_agent() (rag/graph.py),
    which already ran full arbitration (static alias -> fuzzy -> bounded LLM
    on ambiguity) for the user's actual question. This guard exists because
    nothing forces the LLM to actually use that hint verbatim in its tool
    calls -- so every tool re-validates its own model_name independently.

    Deliberately does NOT pass an llm client here (no re-arbitration at the
    tool level): ambiguity arbitration already happened once per question
    upstream; repeating it per tool call would multiply LLM calls and risk
    inconsistent picks across different tools within the same question.
    Only static alias + fuzzy graph match are attempted here.

    If model_name is already a valid indexed technical model, it is
    returned unchanged (zero overhead, and never overrides an already-
    correct technical identifier). If it cannot be resolved to exactly one
    unambiguous model, the original value is returned unchanged and the
    downstream tool's own "model not found" check will surface the error to
    the LLM -- this function never silently guesses.
    """
    if _is_wildcard_model(model_name):
        return model_name

    G = _require_graph()
    if G.has_node(f"model:{model_name}"):
        return model_name

    concept = resolve_business_term(model_name, G)  # llm=None: static alias + fuzzy only
    if concept.is_resolved and len(concept.resolved_models) == 1:
        _logger.info(
            "Resolved business term %r -> technical model %r (source=%s)",
            model_name, concept.resolved_models[0], concept.source_step,
        )
        return concept.resolved_models[0]

    return model_name


resolve_model_param = _resolve_model_param


# =====================================================================
# COMPOSITE TOOLS (B.1.1 - B.1.5)
# =====================================================================

@tool
def who_has_access_to(model_name: str, permission: str = "read", group_id: Optional[str] = None) -> str:
    """Evaluate model access rights and list active ir.rule record rules. Call ONCE per model without group_id unless testing a single group."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG

    from code_intelligence.deterministic_tools import who_has_access_to as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name, permission=permission, group_id=group_id)
    return result.summary_text


@tool
def field_change_impact(field_name: str, model_name: str) -> str:
    """Analyze upstream triggers and downstream computed fields when modifying a model field."""
    from code_intelligence.deterministic_tools import field_change_impact as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, field_name, model_name)
    parts = [result.summary_text]
    if result.upstream_triggers:
        parts.append(f"Upstream triggers: {', '.join(result.upstream_triggers)}")
    if result.downstream_computed_fields:
        parts.append(f"Downstream impacted fields: {', '.join(result.downstream_computed_fields)}")
    return "\n".join(parts)


@tool
def button_execution_path(button_name: str, model_name: str, user_groups_json: str = "[]") -> str:
    """Trace UI button execution path, method called, workflow transition, required groups,
    and whether the requester can actually use it. Call this for any "how do I do X" question."""
    # NOTE (dev-facing only, kept out of the @tool docstring -- same rationale
    # as evaluate_record_rules above): user_groups_json is ALWAYS
    # overridden by rag/graph.py's _override_user_groups_arg with the real
    # requester's groups before this tool executes.
    from code_intelligence.deterministic_tools import button_execution_path as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    try:
        user_groups = json.loads(user_groups_json) if isinstance(user_groups_json, str) else user_groups_json
    except Exception:
        user_groups = None
    result = _impl(G, button_name, model_name, user_groups=user_groups)
    return result.summary_text + "\n" + "\n".join(result.execution_steps)


@tool
def trace_full_inheritance(model_name: str) -> str:
    """Trace full _inherit extension and _inherits delegation hierarchy for an Odoo model."""
    from code_intelligence.deterministic_tools import trace_full_inheritance as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name)
    return result.summary_text


@tool
def describe_workflow(model_name: str) -> str:
    """Inspect workflow states, state field, and state machine transitions for an Odoo model."""
    from code_intelligence.deterministic_tools import describe_workflow as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name)
    return result.summary_text


# =====================================================================
# AUXILIARY TOOLS (B.2.1 - B.2.4)
# =====================================================================

@tool
def resolve_technical_name(technical_name: str) -> str:
    """Resolve technical group XML-ID (e.g. sales_team.group_sale_manager) to business role name."""
    from code_intelligence.auxiliary_tools import resolve_technical_name_to_role as _impl
    return _impl(technical_name)


@tool
def list_involved_modules(model_name: str) -> str:
    """List Odoo modules defining or extending a model, each tagged with its role
    (declares = holds _name, extends = _inherit only). When a model spans several
    modules, all candidates are listed. If a module name is provided, lists all models
    defined or extended by that module."""
    from code_intelligence.auxiliary_tools import list_involved_modules_with_role as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    mod_node = f"module:{model_name}"
    if not G.has_node(f"model:{model_name}") and G.has_node(mod_node):
        models_with_role = []
        for pred in G.predecessors(mod_node):
            if pred.startswith("model:"):
                m = pred.replace("model:", "")
                edge = G.get_edge_data(pred, mod_node) or {}
                role = edge.get("role", "extends")
                models_with_role.append(f"{m} ({role})")
        if models_with_role:
            return f"Module '{model_name}' defines or extends the following models: {', '.join(sorted(models_with_role))}."
    entries = _impl(G, model_name)
    if entries:
        formatted = ", ".join(f"{mod} ({role})" for mod, role in entries)
        ambiguity_note = (
            " [SYMBOLE AMBIGU: plusieurs modules candidats -- ne pas en choisir un "
            "arbitrairement, les présenter tous ou demander à l'utilisateur de trancher]"
            if len(entries) > 1 else ""
        )
        return f"Modules implicated for model '{model_name}': {formatted}.{ambiguity_note}"
    return f"No modules found for model '{model_name}' in the indexed knowledge graph."


@tool
def explain_decision_path(path_nodes_json: str) -> str:
    """Explain graph path (JSON list of node IDs) in natural language."""
    from code_intelligence.auxiliary_tools import explain_decision_path as _impl
    G = _require_graph()
    try:
        path_nodes = json.loads(path_nodes_json)
        
    except (json.JSONDecodeError, TypeError):
        return "Error: path_nodes_json must be a valid JSON list of node IDs."
    if not isinstance(path_nodes, list) or not all(isinstance(n, str) for n in path_nodes):
        return (
            "Error: path_nodes_json must be a JSON list of string node IDs "
            "(e.g. [\"model:account.move\", \"rule:xyz\"]), not numbers or other types."
        )
    return _impl(G, path_nodes)


@tool
def read_source_code(filepath: str, line_start: int, line_end: int) -> str:
    """Read precise slice of source code lines (max 200 lines)."""
    from code_intelligence.auxiliary_tools import read_precise_source_code as _impl
    return _impl(filepath, line_start, line_end)


def evaluate_rules_raw(model_name: str, permission: str = "read", user_groups_json: str = "[]"):
    """
    Execute evaluate_record_rules and return the full
    RuleEvaluationResult (not just summary_text).  Exposed so that
    graph.py's J14 can_view_amount block can call this once and reuse
    the result object instead of re-executing the engine a second time.
    """
    from code_intelligence.deterministic_tools import evaluate_record_rules as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    try:
        user_groups = json.loads(user_groups_json) if isinstance(user_groups_json, str) else user_groups_json
    except Exception:
        user_groups = []
    return _impl(G, model_name, permission=permission, user_groups=user_groups)


@tool
def evaluate_record_rules(model_name: str, permission: str = "read", user_groups_json: str = "[]") -> str:
    """Evaluate Odoo ir.rule record rules for a model and permission (read, write, create, unlink)."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    # NOTE (dev-facing only, kept out of the @tool docstring on purpose --
    # the docstring above is sent verbatim to the LLM as this tool's
    # description on every single call, so it stays LLM-relevant only):
    # user_groups_json is ALWAYS overridden by the caller (rag/graph.py's
    # code_intelligence_agent, via _override_user_groups_arg) with the
    # actual requester's real Odoo group ids from the signed JWT before
    # this tool executes -- whatever value the LLM supplies here is
    # discarded. The LLM doesn't need to know this to call the tool
    # correctly (it just needs model_name + permission), so telling it costs
    # tokens on every request for zero behavioral benefit.
    return evaluate_rules_raw(model_name, permission, user_groups_json).summary_text


def find_model_source_filepaths(G, model_name: str) -> set:
    """
    Locate Python source filepaths linked to the given technical model
    (via HAS_FIELD edges or Method nodes), independently of what the
    caller does with them.

    Extracted from analyze_security_locks's original inline logic so
    that a second consumer (analyze_data_constraints, J13-bis) doesn't
    reimplement the same lookup a second time -- two independent copies of
    "which files belong to this model" is exactly the kind of duplication
    that produced the F-08 rule-indexing bug in J7.
    """
    model_node = f"model:{model_name}"
    if model_node not in G:
        return set()

    filepaths = set(G.nodes[model_node].get("filepaths", []))

    for u, v, attrs in G.edges(data=True):
        if attrs.get("edge_type") == "HAS_FIELD" and u == model_node:
            f_path = G.nodes[v].get("filepath", "")
            if f_path:
                filepaths.add(f_path)

    for node, attrs in G.nodes(data=True):
        if attrs.get("node_type") == "Method" and attrs.get("model") == model_name:
            f_path = attrs.get("filepath", "")
            if f_path:
                filepaths.add(f_path)

    # Include source filepaths from inherited models (EXTENDS edges)
    for _, target_node, attrs in G.out_edges(model_node, data=True):
        if attrs.get("edge_type") == "EXTENDS" and target_node.startswith("model:"):
            parent_fps = G.nodes[target_node].get("filepaths", [])
            filepaths.update(parent_fps)

    return filepaths


def find_security_lock_source_files(G, model_name: str) -> list:
    """
    Return all source filepaths associated with `model_name` that contain
    security findings (exception messages, required groups, hardcoded logins/IDs).
    """
    from code_intelligence.semgrep_locks_analyzer import python_source_has_security_findings
    from pathlib import Path

    filepaths = find_model_source_filepaths(G, model_name)
    hit_files = []
    for fp in sorted(filepaths):
        if not _is_custom_module_filepath(fp):
            continue
        p = Path(fp)
        if not p.exists():
            continue
        code = p.read_text(encoding="utf-8")
        if python_source_has_security_findings(code, fp):
            hit_files.append(fp)
    return hit_files


def find_server_action_nodes(G, model_name: str) -> list:
    """
    Locate ServerAction nodes (ir.actions.server / base.automation, as
    normalized by graph_builder) targeting the given technical model.

    Extracted as a standalone helper (not inlined in analyze_server_actions)
    so that rag/graph.py's deterministic pre-dispatch guard can check for
    presence WITHOUT re-implementing the lookup -- two independent
    implementations of "does this model have server actions" is exactly the
    kind of duplication that produced the F-08 rule-indexing bug in J7.
    Returns a list of (node_id, attrs) tuples, empty if none found.
    """
    model_node = f"model:{model_name}"
    if model_node not in G:
        return []

    sa_nodes = []
    for node, attrs in G.nodes(data=True):
        if attrs.get("node_type") == "ServerAction":
            target_m = attrs.get("model_id", "")
            clean_m = resolve_model_xmlref(target_m)
            if clean_m == model_name or G.has_edge(node, model_node):
                sa_nodes.append((node, attrs))
    return sa_nodes


def find_methods_with_override_cascade(G, model_name: str) -> list:
    """
    Locate methods on the given technical model that are overridden in more
    than one module (a real _inherit cascade), by reading override_sites off
    each Method node (populated by graph_builder.py in manifest-dependency
    load order; see method_override_resolver.py).

    Extracted as a standalone helper (not inlined in rag/graph.py) so the
    forced-dispatch guard there can check for structural presence WITHOUT
    re-implementing the lookup -- same rationale as find_server_action_nodes
    above (F-08 duplication lesson from J7). Needed because
    analyze_method_override_chain requires a method_name that never
    appears in the natural-language question, unlike the model-only forced
    dispatches (J8/J9) -- this structural guard is what makes it safe to
    reuse the broad _APPROVAL_PATTERN keyword trigger for it (see rag/
    graph.py): on a model with no real override cascade the cost of a
    keyword false-positive is zero, nothing is dispatched.

    Returns a list of method names (str), empty if none found.
    """
    prefix = f"method:{model_name}."
    method_names = []
    for node, attrs in G.nodes(data=True):
        if not node.startswith(prefix):
            continue
        if attrs.get("node_type") != "Method":
            continue
        if len(attrs.get("override_sites", [])) > 1:
            method_names.append(node[len(prefix):])
    return method_names


@tool
def analyze_server_actions(model_name: str) -> str:
    """Analyze server actions (ir.actions.server) and automated rules (base.automation) for a given model. Detects sudo() calls, hardcoded IDs, and security warnings."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.server_action_analyzer import (
        analyze_server_action_code, interpret_server_action_with_llm,
    )
    G = _require_graph()
    model_name = _resolve_model_param(model_name)

    model_node = f"model:{model_name}"
    if model_node not in G:
        return f"Model '{model_name}' was not found in the indexed knowledge graph."

    sa_nodes = find_server_action_nodes(G, model_name)
    if not sa_nodes:
        return f"No server actions (ir.actions.server) found for model '{model_name}'."

    import re
    from code_intelligence.utils import format_file_link

    summaries = []
    for node_id, attrs in sa_nodes:
        xml_id = attrs.get("xml_id", node_id)
        code = attrs.get("code", "")
        action_type = attrs.get("action_type", "server_action")
        name = attrs.get("name", "")
        user_id = attrs.get("user_id", "")
        interval_number = attrs.get("interval_number", 1)
        interval_type = attrs.get("interval_type", "")

        analysis = analyze_server_action_code(
            code=code,
            action_xml_id=xml_id,
            action_type=action_type,
            action_name=name,
            user_id=user_id,
            interval_number=interval_number,
            interval_type=interval_type,
        )
        analysis = interpret_server_action_with_llm(analysis, code, _LLM_REF)
        summary = analysis.summary_text
        if analysis.llm_summary:
            summary += f"\n  - Interprétation: {analysis.llm_summary}"

        # If code calls a method on model, e.g. model.<method_name>()
        invoked_methods = re.findall(r"\b(?:model|records?|self)\.([a-zA-Z0-9_]+)\s*\(", code)
        for m_name in invoked_methods:
            m_node_id = f"method:{model_name}.{m_name}"
            if m_node_id in G:
                m_attrs = G.nodes[m_node_id]
                m_fp = m_attrs.get("filepath")
                m_start = m_attrs.get("lineno", 1)
                m_end = m_attrs.get("end_lineno") or (m_start + 30)
                if m_fp:
                    m_link = format_file_link(m_fp, m_start, m_end)
                    summary += f"\n  - Méthode Python appelée: {m_name}() (Defined at {m_link})"

                    # Inspect sub-methods up to depth 2
                    queue = [(m_name, m_fp, m_start, m_end, 1)]
                    visited_m = {m_name}
                    while queue:
                        curr_m, curr_fp, curr_start, curr_end, depth = queue.pop(0)
                        if depth > 2:
                            break
                        try:
                            p = Path(curr_fp)
                            if p.exists():
                                src_lines = p.read_text(encoding="utf-8").splitlines()
                                curr_code = "\n".join(src_lines[max(0, curr_start - 1):min(len(src_lines), curr_end)])
                                sub_calls = re.findall(r"\b(?:obj|self|record)\.([a-zA-Z0-9_]+)\s*\(", curr_code)
                                for sub_m in sub_calls:
                                    if sub_m in visited_m:
                                        continue
                                    visited_m.add(sub_m)
                                    sub_node_id = f"method:{model_name}.{sub_m}"
                                    if sub_node_id in G:
                                        sub_attrs = G.nodes[sub_node_id]
                                        sub_fp = sub_attrs.get("filepath")
                                        sub_start = sub_attrs.get("lineno", 1)
                                        sub_end = sub_attrs.get("end_lineno") or (sub_start + 30)
                                        if sub_fp:
                                            sub_link = format_file_link(sub_fp, sub_start, sub_end)
                                            indent = "  " * depth
                                            summary += f"\n{indent}  -> Sous-méthode appelée: {sub_m}() (Defined at {sub_link})"
                                            queue.append((sub_m, sub_fp, sub_start, sub_end, depth + 1))
                        except Exception:
                            pass

        summaries.append(summary)

    return "\n\n".join(summaries)


def _is_custom_module_filepath(filepath: str) -> bool:
    """True if filepath belongs to a downstream/installed module rather than the core Odoo framework."""
    from config.settings import CORE_ADDONS_PATH, CORE_FRAMEWORK_ADDONS_PATH, CUSTOM_ADDONS_PATH
    try:
        resolved = Path(filepath).resolve()
        if CUSTOM_ADDONS_PATH and Path(CUSTOM_ADDONS_PATH).resolve() in resolved.parents:
            return True
        if CORE_ADDONS_PATH and Path(CORE_ADDONS_PATH).resolve() in resolved.parents:
            return False
        if CORE_FRAMEWORK_ADDONS_PATH and Path(CORE_FRAMEWORK_ADDONS_PATH).resolve() in resolved.parents:
            return False
    except Exception:
        pass
    path_parts = Path(filepath).parts
    core_dirs = {"odoo/addons", "base", "web"}
    if any(c in path_parts for c in core_dirs):
        return False
    return True


def _sort_filepaths_custom_first(filepaths) -> list:
    """
    Sort filepaths so custom_* module files are examined before core/OCA
    files, instead of raw alphabetical order.

    analyze_security_locks reads each file in full and concatenates a
    per-file summary; when the combined output later gets truncated
    (context/token budget upstream -- that cap is deliberately NOT touched
    here, see todo/rules.md: it has already been raised several times and
    is not the fix for this class of problem), whatever is dropped is
    whatever comes LAST in this iteration order. Raw alphabetical sorting
    means a core/OCA path (e.g. 'account/models/...') can sort before a
    project's actual custom_* module simply by alphabet, pushing the
    custom mechanism -- the one actually relevant to a security question --
    out of the response while irrelevant core noise survives. Putting
    custom_* files first guarantees the opposite: if anything is cut, it's
    core/OCA noise, never the custom lock/override a user is asking about.
    Alphabetical order is preserved within each group for determinism.
    """
    return sorted(filepaths, key=lambda fp: (not _is_custom_module_filepath(fp), fp))


@tool
def analyze_security_locks(model_name: str) -> str:
    """Analyze Python code for a given model to detect hardcoded security locks, exception messages (UserError/ValidationError), hardcoded email/login lists, and dynamic dispatch uncertainties (getattr/eval/exec)."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.semgrep_locks_analyzer import analyze_python_security_locks

    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    model_node = f"model:{model_name}"
    if model_node not in G:
        return f"Model '{model_name}' was not found in the indexed knowledge graph."

    filepaths = find_model_source_filepaths(G, model_name)

    if not filepaths:
        return f"No Python source files located for model '{model_name}'."

    summaries = []
    for fp in _sort_filepaths_custom_first(filepaths):
        p = Path(fp)
        if p.exists():
            code = p.read_text(encoding="utf-8")
            analysis = analyze_python_security_locks(code, fp)
            summaries.append(analysis.summary_text)

    return "\n\n".join(summaries) if summaries else f"No security analysis results for model '{model_name}'."


@tool
def analyze_method_override_chain(model_name: str, method_name: str) -> str:
    """Resolve the REAL execution order of a method overridden across several
    modules in an _inherit cascade (e.g. account.move.action_valider_avoir
    extended by 3 different customization modules), and flag if a
    conditional exemption set without an early `return` is silently
    nullified by an unconditional `super()` call later in the same method.
    ALWAYS call this when a governance question involves a method known to
    be overridden in more than one module (check trace_full_inheritance /
    list_involved_modules first) -- reading a single module's version of
    the method in isolation can miss the real, composed behavior."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.method_override_resolver import analyze_method_override_chain as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    return _impl(G, model_name, method_name, llm=_LLM_REF)


@tool
def analyze_data_constraints(model_name: str) -> str:
    """Detect _sql_constraints declarations and relational field domain= conditions
    (Many2one/Many2many) for a given model via static Semgrep analysis. Deterministic
    pattern matching, not LLM interpretation -- high confidence."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.data_constraints_analyzer import analyze_data_constraints_from_filepaths

    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    model_node = f"model:{model_name}"
    if model_node not in G:
        return f"Model '{model_name}' was not found in the indexed knowledge graph."

    filepaths = find_model_source_filepaths(G, model_name)
    if not filepaths:
        return f"No Python source files located for model '{model_name}'."

    result = analyze_data_constraints_from_filepaths(model_name, filepaths)
    return result.summary_text


# =====================================================================
# TOOL REGISTRY
# =====================================================================

ALL_CI_TOOLS = [
    list_involved_modules,
    who_has_access_to,
    evaluate_record_rules,
    analyze_server_actions,
    analyze_security_locks,
    analyze_method_override_chain,
    analyze_data_constraints,
    field_change_impact,
    button_execution_path,
    trace_full_inheritance,
    describe_workflow,
    resolve_technical_name,
    explain_decision_path,
    read_source_code,
]
