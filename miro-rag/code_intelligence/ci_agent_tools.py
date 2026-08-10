"""
code_intelligence/ci_agent_tools.py

LangChain @tool wrappers for all 9 Code Intelligence tools (5 composite + 4 auxiliary).
Bound to LLM inside code_intelligence_agent via bind_tools().
All code and docstrings in English per project coding rules.
"""

import json
import logging
from typing import Optional

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


WILDCARD_MODEL_ERROR_MSG = (
    "Erreur : le modèle doit être spécifié explicitement (les jokers '*' et "
    "l'extraction globale de tous les modèles ne sont pas autorisés par la politique de sécurité J32-J33)."
)


# =====================================================================
# COMPOSITE TOOLS (B.1.1 - B.1.5)
# =====================================================================

@tool
def qui_a_acces_a(model_name: str, droit: str = "read", group_id: Optional[str] = None) -> str:
    """Evaluate model access rights and list active ir.rule record rules. Call ONCE per model without group_id unless testing a single group."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG

    from code_intelligence.deterministic_tools import qui_a_acces_a as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name, droit=droit, group_id=group_id)
    return result.summary_text


@tool
def impact_changement_champ(field_name: str, model_name: str) -> str:
    """Analyze upstream triggers and downstream computed fields when modifying a model field."""
    from code_intelligence.deterministic_tools import impact_changement_champ as _impl
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
def chemin_execution_bouton(button_name: str, model_name: str, user_groups_json: str = "[]") -> str:
    """Trace UI button execution path, method called, workflow transition, required groups,
    and whether the requester can actually use it. Call this for any "how do I do X" question."""
    # NOTE (dev-facing only, kept out of the @tool docstring -- same rationale
    # as evaluer_regles_enregistrement above): user_groups_json is ALWAYS
    # overridden by rag/graph.py's _override_user_groups_arg with the real
    # requester's groups before this tool executes.
    from code_intelligence.deterministic_tools import chemin_execution_bouton as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    try:
        user_groups = json.loads(user_groups_json) if isinstance(user_groups_json, str) else user_groups_json
    except Exception:
        user_groups = None
    result = _impl(G, button_name, model_name, user_groups=user_groups)
    return result.summary_text + "\n" + "\n".join(result.execution_steps)


@tool
def suivre_heritage_complet(model_name: str) -> str:
    """Trace full _inherit extension and _inherits delegation hierarchy for an Odoo model."""
    from code_intelligence.deterministic_tools import suivre_heritage_complet as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name)
    return result.summary_text


@tool
def quel_est_le_processus_de(model_name: str) -> str:
    """Get ordered workflow state machine transitions for an Odoo model."""
    from code_intelligence.deterministic_tools import quel_est_le_processus_de as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    result = _impl(G, model_name)
    return result.summary_text


# =====================================================================
# AUXILIARY TOOLS (B.2.1 - B.2.4)
# =====================================================================

@tool
def resoudre_nom_technique(nom_technique: str) -> str:
    """Resolve technical group XML-ID (e.g. sales_team.group_sale_manager) to business role name."""
    from code_intelligence.auxiliary_tools import resoudre_nom_technique_vers_role as _impl
    return _impl(nom_technique)


@tool
def lister_modules_impliques(model_name: str) -> str:
    """List Odoo modules defining or extending a model, each tagged with its role
    (declares = holds _name, extends = _inherit only). When a model spans several
    modules, ALL candidates are listed -- do not assume the first one listed is
    the "real" origin; if the question depends on which module is responsible,
    ask the user to clarify or state all candidates explicitly rather than
    picking one yourself (Bloc 8 / J28-29: ambiguous symbols)."""
    from code_intelligence.auxiliary_tools import lister_modules_impliques_avec_role as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
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
def expliquer_chemin(path_nodes_json: str) -> str:
    """Explain graph path (JSON list of node IDs) in natural language."""
    from code_intelligence.auxiliary_tools import expliquer_chemin_de_decision as _impl
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
def lire_code_source(filepath: str, line_start: int, line_end: int) -> str:
    """Read precise slice of source code lines (max 200 lines)."""
    from code_intelligence.auxiliary_tools import lire_code_source_precis as _impl
    return _impl(filepath, line_start, line_end)


def evaluer_regles_raw(model_name: str, droit: str = "read", user_groups_json: str = "[]"):
    """
    Execute evaluer_regles_enregistrement and return the full
    RuleEvaluationResult (not just summary_text).  Exposed so that
    graph.py's J14 can_view_amount block can call this once and reuse
    the result object instead of re-executing the engine a second time.
    """
    from code_intelligence.deterministic_tools import evaluer_regles_enregistrement as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    try:
        user_groups = json.loads(user_groups_json) if isinstance(user_groups_json, str) else user_groups_json
    except Exception:
        user_groups = []
    return _impl(G, model_name, droit=droit, user_groups=user_groups)


@tool
def evaluer_regles_enregistrement(model_name: str, droit: str = "read", user_groups_json: str = "[]") -> str:
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
    # correctly (it just needs model_name + droit), so telling it costs
    # tokens on every request for zero behavioral benefit.
    return evaluer_regles_raw(model_name, droit, user_groups_json).summary_text


def find_model_source_filepaths(G, model_name: str) -> set:
    """
    Locate Python source filepaths linked to the given technical model
    (via HAS_FIELD edges or Method nodes), independently of what the
    caller does with them.

    Extracted from analyser_verrous_securite's original inline logic so
    that a second consumer (analyser_contraintes_donnees, J13-bis) doesn't
    reimplement the same lookup a second time -- two independent copies of
    "which files belong to this model" is exactly the kind of duplication
    that produced the F-08 rule-indexing bug in J7.
    """
    model_node = f"model:{model_name}"
    if model_node not in G:
        return set()

    filepaths = set(G.nodes[model_node].get("filepaths", []))
    if filepaths:
        return filepaths

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

    return filepaths


def find_security_lock_source_files(G, model_name: str) -> list:
    """
    Locate Python source files for the given technical model that contain
    at least one security-lock finding (hardcoded login/email list,
    UserError/ValidationError message, dynamic dispatch, or a has_group()
    check), per semgrep_locks_analyzer.python_source_has_security_findings.

    Extracted as a standalone helper so rag/graph.py's deterministic
    pre-dispatch guard for analyser_verrous_securite can check for
    structural presence WITHOUT re-implementing the detection -- same
    rationale as find_server_action_nodes/find_methods_with_override_cascade
    below (F-08 duplication lesson from J7). Unlike those two, there is no
    graph-node representation of locks (they're computed live from source
    by semgrep_locks_analyzer, not indexed by graph_builder.py at build
    time), so this reads the actual files -- still cheap (one AST parse +
    a few regex passes per file, no LLM), matching the same "a false
    positive costs ~nothing" philosophy already used for the other guards.

    Added 2026-08-10 (Bloc 9, module 5 gap): the forced dispatch of
    analyser_verrous_securite previously relied SOLELY on _APPROVAL_PATTERN
    keyword matching in the question text -- questions like "pourquoi je
    n'arrive pas à démarrer..." or "la règle s'applique-t-elle..." contain
    none of that vocabulary, so the dispatch silently never fired and the
    LLM was left to freely pick a tool, which it did wrong (hallucinated a
    malformed method name). This structural guard makes the trigger
    independent of the question's wording -- if the model has a real
    Python lock, analyser_verrous_securite fires no matter how the
    question is phrased.

    Returns a list of filepaths (str) with at least one finding, empty if
    the model has no source files or none of them have any finding.
    """
    from code_intelligence.semgrep_locks_analyzer import python_source_has_security_findings
    from pathlib import Path

    filepaths = find_model_source_filepaths(G, model_name)
    hit_files = []
    for fp in sorted(filepaths):
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

    Extracted as a standalone helper (not inlined in analyser_actions_serveur)
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
    analyser_chaine_surcharge_methode requires a method_name that never
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
def analyser_actions_serveur(model_name: str) -> str:
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

    summaries = []
    for node_id, attrs in sa_nodes:
        xml_id = attrs.get("xml_id", node_id)
        code = attrs.get("code", "")
        analysis = analyze_server_action_code(code, xml_id)
        analysis = interpret_server_action_with_llm(analysis, code, _LLM_REF)
        summaries.append(analysis.summary_text)

    return "\n\n".join(summaries)


@tool
def analyser_verrous_securite(model_name: str) -> str:
    """Analyze Python code for a given model to detect hardcoded security locks, exception messages (UserError/ValidationError), hardcoded email/login lists, and dynamic dispatch uncertainties (getattr/eval/exec)."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.semgrep_locks_analyzer import analyze_python_security_locks
    from pathlib import Path

    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    model_node = f"model:{model_name}"
    if model_node not in G:
        return f"Model '{model_name}' was not found in the indexed knowledge graph."

    filepaths = find_model_source_filepaths(G, model_name)

    if not filepaths:
        return f"No Python source files located for model '{model_name}'."

    summaries = []
    for fp in sorted(filepaths):
        p = Path(fp)
        if p.exists():
            code = p.read_text(encoding="utf-8")
            analysis = analyze_python_security_locks(code, fp)
            summaries.append(analysis.summary_text)

    return "\n\n".join(summaries) if summaries else f"No security analysis results for model '{model_name}'."


@tool
def analyser_chaine_surcharge_methode(model_name: str, method_name: str) -> str:
    """Resolve the REAL execution order of a method overridden across several
    modules in an _inherit cascade (e.g. account.move.action_valider_avoir
    extended by 3 different customization modules), and flag if a
    conditional exemption set without an early `return` is silently
    nullified by an unconditional `super()` call later in the same method.
    ALWAYS call this when a governance question involves a method known to
    be overridden in more than one module (check suivre_heritage_complet /
    lister_modules_impliques first) -- reading a single module's version of
    the method in isolation can miss the real, composed behavior."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from code_intelligence.method_override_resolver import analyser_chaine_surcharge_methode as _impl
    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    return _impl(G, model_name, method_name, llm=_LLM_REF)


@tool
def analyser_contraintes_donnees(model_name: str) -> str:
    """Detect _sql_constraints declarations and relational field domain= conditions
    (Many2one/Many2many) for a given model via static Semgrep analysis. Deterministic
    pattern matching, not LLM interpretation -- high confidence."""
    if _is_wildcard_model(model_name):
        return WILDCARD_MODEL_ERROR_MSG
    from pathlib import Path
    from code_intelligence.semgrep_runner import run_semgrep_analysis
    from code_intelligence.utils import format_file_link

    G = _require_graph()
    model_name = _resolve_model_param(model_name)
    model_node = f"model:{model_name}"
    if model_node not in G:
        return f"Model '{model_name}' was not found in the indexed knowledge graph."

    filepaths = find_model_source_filepaths(G, model_name)
    if not filepaths:
        return f"No Python source files located for model '{model_name}'."

    config_dir = Path(__file__).resolve().parent / "semgrep_rules"
    all_matches = []
    for fp in sorted(filepaths):
        p = Path(fp)
        if not p.exists():
            continue
        all_matches.extend(run_semgrep_analysis(p, config_dir))

    if not all_matches:
        return (
            f"No _sql_constraints or relational domain= patterns detected for "
            f"model '{model_name}' [Confiance: HIGH -- static pattern match, "
            f"deterministic]."
        )

    lines = [
        f"Analyse des contraintes de données (Semgrep) pour '{model_name}' "
        f"[Confiance: HIGH -- correspondance de motif statique, déterministe]:"
    ]
    for match in all_matches:
        link = format_file_link(match.filepath, match.start_line, match.end_line)
        lines.append(f"  - {link} ({match.check_id}): {match.message}")
        if match.lines:
            lines.append(f"    ```\n    {match.lines}\n    ```")

    return "\n".join(lines)


# =====================================================================
# TOOL REGISTRY
# =====================================================================

ALL_CI_TOOLS = [
    lister_modules_impliques,
    qui_a_acces_a,
    evaluer_regles_enregistrement,
    analyser_actions_serveur,
    analyser_verrous_securite,
    analyser_chaine_surcharge_methode,
    analyser_contraintes_donnees,
    impact_changement_champ,
    chemin_execution_bouton,
    suivre_heritage_complet,
    quel_est_le_processus_de,
    resoudre_nom_technique,
    expliquer_chemin,
    lire_code_source,
]
