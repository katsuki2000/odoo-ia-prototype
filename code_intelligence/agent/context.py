_EXECUTION_FAILURE_NOTICE = (
    "\n\n[ATTENTION] Une ou plusieurs analyses n'ont pas pu "
    "s'ex\u00e9cuter correctement pour cette question (panne technique d'un ou "
    "plusieurs outils). La r\u00e9ponse ci-dessus peut donc \u00eatre incompl\u00e8te ; "
    "n'y voyez pas une absence confirm\u00e9e d'information."
)

_CI_TOOL_DISPLAY_NAMES = {
    "analyze_security_locks": "Verrous de sécurité (code Python)",
    "analyze_server_actions": "Actions serveur / automatisations",
    "analyze_method_override_chain": "Chaîne de surcharge de méthode",
    "who_has_access_to": "Matrice d'accès (ACL)",
    "evaluate_record_rules": "Règles d'enregistrement (ir.rule)",
    "can_view_amount_v2": "Vérification déterministe du montant",
    "analyze_data_constraints": "Contraintes de données (Semgrep)",
    "field_change_impact": "Impact de modification de champ",
    "button_execution_path": "Chemin d'exécution du bouton",
    "trace_full_inheritance": "Héritage complet du modèle",
    "describe_workflow": "Workflow (états)",
    "resolve_technical_name": "Résolution de rôle technique",
    "list_involved_modules": "Modules impliqués",
    "explain_decision_path": "Explication du chemin de décision",
    "read_source_code": "Lecture de code source",
}

# ── Dispatch Context ───────────────────────────────────────────────────

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class DispatchContext:
    G: Any
    concept: Any
    question: str
    tool_map: Dict[str, Any]
    # None = demandeur identity unavailable this turn (state["user_groups"] key
    # absent -- distinct from an explicit [], meaning identity known, no
    # groups). See todo/contexte.txt section 888/889. Every consumer treats
    # None the same as [] (fail closed) via `or []` -- the distinction exists
    # for correct logging/diagnostics, not for a different authorization
    # outcome.
    resolved_user_group_xmlids: Optional[List[str]]
    trace_logger: Any
    trace_id: str
    hop_cap: int

    tool_observations: List[str] = field(default_factory=list)
    tool_observation_models: List[str] = field(default_factory=list)
    tool_observation_tools: List[str] = field(default_factory=list)
    omitted_items: List[Any] = field(default_factory=list)
    seen_calls: Set[Any] = field(default_factory=set)
    system_prompt_suffix: str = ""
    hop_count: int = 0
    hop_index: int = 0

    
    llm_call_count: int = 0
    groq_wait: float = 0.0
    per_hop_times: List[float] = field(default_factory=list)
    synthesis_time: float = 0.0

    # Set once the security-distinction application-layer reminder (see
    # dispatch_guards.py::_maybe_build_application_layer_reminder,
    # todo/contexte.txt section 778) has been injected into the ReAct loop
    # for this turn, so it is only ever sent once per question.
    security_distinction_reminder_sent: bool = False

    # Section 861 (2a, mandat 4.4/trajectory recall): names of the
    # predispatch dispatch_X functions whose predicate matched this turn's
    # question, in the order run_predispatch_chain() ran them. Empty means
    # no predicate matched -- the question fell through to free ReAct
    # routing (previously silent, now explicitly loggable via
    # trace_logger.log_routing()).
    matched_dispatchers: List[str] = field(default_factory=list)

    # Section 888/889: benchmark-only, harness-declared hypothetical security
    # personas -- principal_id -> resolved group xml_ids -- immutable context
    # a question can compare against (e.g. SAL-Q1's "vendeur" vs "portail").
    # Strictly separate from resolved_user_group_xmlids (the real, actually
    # authenticated demandeur): never merged, never used as a fallback for
    # each other. Empty outside benchmark runs that declare security_principals
    # -- production behavior for the real demandeur is untouched by this field.
    security_principals: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def hop_budget_exhausted(self) -> bool:
        return self.hop_count >= self.hop_cap

    def record_observation(
        self, tool_name: str, tool_args: dict, observation: str,
        model_name: Optional[str], call_key: Optional[Any], elapsed_s: float,
    ) -> None:
        self.tool_observations.append(observation)
        self.tool_observation_models.append(model_name)
        self.tool_observation_tools.append(tool_name)
        self.hop_count += 1
        if call_key is not None:
            self.seen_calls.add(call_key)
        self.trace_logger.log_hop(
            trace_id=self.trace_id, hop_index=self.hop_index,
            tool_name=tool_name, tool_args=tool_args,
            observation=observation, elapsed_ms=elapsed_s * 1000,
        )
        self.hop_index += 1

# ── Early Refusal ───────────────────────────────────────────────────────

"""

Shared builder for the 3 early-refusal paths of the CI agent (out-of-scope,
prompt injection, massive extraction) 
"""

import time

def build_early_refusal_response(
    answer: str, trace_logger, trace_id: str, question: str,
    start_time: float, state: dict, hop_cap: int,
) -> dict:
    from core.schemas import AssistantResponse
    response = AssistantResponse(answer=answer, sources=[], confidence=0.0)
    timing = state.get("timing", {}).copy()
    timing["code_intelligence_time"] = time.time() - start_time
    trace_logger.log_summary(
        trace_id=trace_id, branch="code_intelligence", question=question,
        hop_count=0, llm_call_count=0,
        total_time_ms=timing["code_intelligence_time"] * 1000,
        hop_cap=hop_cap,
    )
    return {"response": response, "raw_answer": response.answer, "timing": timing}

# ── Group Resolution ───────────────────────────────────────────────────

"""
core.graph.graph keeps an independent copy of these globals
(re-imported by name from code_intelligence.agent.loop), and
_get_admin_rpc_client() explicitly syncs against core.graph.graph's copy via
sys.modules so a reset on either side is mirrored on the other.
"""

import logging

logger = logging.getLogger(__name__)

_GROUP_XMLID_CACHE: dict = {}
_ADMIN_RPC_CLIENT = None
_ADMIN_RPC_UID = None


def _get_admin_rpc_client():
    """Lazy singleton admin XML-RPC client + uid, reused across requests --
    pure static-metadata lookups only (group xml_id resolution), never used
    for anything requiring the actual requester's own rights.

    core.graph.graph holds an independent copy of these globals (re-imported by
    name).
    """
    global _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID
    import sys
    g_mod = sys.modules.get("core.graph.graph")
    if g_mod is not None:
        target_client = getattr(g_mod, "_ADMIN_RPC_CLIENT", None)
        target_uid = getattr(g_mod, "_ADMIN_RPC_UID", None)
        if target_client is not None:
            _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID = target_client, target_uid
            return target_client, target_uid
        _ADMIN_RPC_CLIENT = None
        _ADMIN_RPC_UID = None

    if _ADMIN_RPC_CLIENT is None:
        from code_intelligence.agent.rpc_client import OdooRpcClient
        client = OdooRpcClient()
        _ADMIN_RPC_UID = client.authenticate_admin()
        _ADMIN_RPC_CLIENT = client
        if g_mod is not None:
            g_mod._ADMIN_RPC_CLIENT = client
            g_mod._ADMIN_RPC_UID = _ADMIN_RPC_UID
    return _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID


def _resolve_user_group_xmlids(group_ids) -> list:
    global _GROUP_XMLID_CACHE
    import sys
    g_mod = sys.modules.get("core.graph.graph")
    cache = getattr(g_mod, "_GROUP_XMLID_CACHE", None) if g_mod is not None else _GROUP_XMLID_CACHE
    if cache is None:
        cache = _GROUP_XMLID_CACHE

    if not group_ids:
        return []

    # If any group_id is already an xml_id string (contains a dot or non-numeric), populate cache directly
    for g in group_ids:
        if isinstance(g, str) and ("." in g or not g.isdigit()):
            cache[g] = g
            _GROUP_XMLID_CACHE[g] = g

    uncached = [g for g in group_ids if g not in cache]
    if uncached:
        try:
            client, admin_uid = _get_admin_rpc_client()
            resolved = client.get_group_xmlids(admin_uid, uncached)
            cache.update(resolved)
            _GROUP_XMLID_CACHE.update(resolved)
        except Exception as e:
            logger.error(
                "Group ID -> xml_id resolution failed for %s: %s. "
                "These groups will be treated as unresolved (fail closed).",
                uncached, e,
            )

    return [cache[g] for g in group_ids if g in cache]

# ── Heuristics & Truncation ─────────────────────────────────────────────

"""
System prompt, hop limits, tool call deduplication, and observation truncation helpers.
"""

import logging
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

from code_intelligence.utils import _TRUNCATION_MARKER, _match_near_truncation



import os as _os
import config.settings  # noqa: F401 -- ensures .env is loaded before reading env vars
CI_MAX_HOPS = int(_os.getenv("CI_MAX_HOPS", "20"))

# Composite tools whose dedup key is only (tool_name, model_name).
_MODEL_KEYED_TOOLS = frozenset({
    "analyze_security_locks",
    "analyze_server_actions",
    "who_has_access_to",
    "evaluate_record_rules",
    "describe_workflow",
    "trace_full_inheritance",
    "list_involved_modules",
    "analyze_data_constraints",
})


def _tool_call_key(tool_name: str, tool_args: "Dict[str, Any]") -> "Optional[Tuple]":
    """Single source of truth for the seen_calls dedup key.

    Section 888/889: when the call names a benchmark persona via
    principal_id, that id is folded into the key so distinct personas on
    the same model are never treated as duplicates of each other (SAL-Q1
    needs one real evaluate_record_rules call per persona on the same
    'sale.order'). A call with no principal_id keeps the exact key shape
    used before this section -- the real-demandeur path is unaffected.

    Section 908: evaluate_record_rules's key never included permission --
    harmless while every call site always used the same fixed "read", but
    dispatch_evaluate_record_rules_for_personas (908) needs to evaluate
    read/write/create/unlink for the SAME model+principal, and without this
    the 2nd/3rd/4th calls would be silently skipped as "already seen" and
    their observations never recorded -- the exact kind of data loss this
    whole thread (892-908) has been fighting. Folded in the same way as
    principal_id: included only for evaluate_record_rules (the tool that
    actually varies output by permission at the ir.rule level -- who_has_
    access_to already returns every permission in one matrix, Bug A/894),
    defaulted to "read" (the tool's own default) so a call with no explicit
    permission keeps the exact key shape used before this section."""
    model_name = tool_args.get("model_name")
    if not model_name:
        return None
    principal_id = tool_args.get("principal_id")
    if tool_name == "analyze_method_override_chain":
        method_name = tool_args.get("method_name")
        return (tool_name, model_name, method_name) if method_name else None
    if tool_name == "button_execution_path":
        btn = tool_args.get("button_name") or tool_args.get("button_identifier")
        if not btn:
            return None
        return (tool_name, model_name, btn, principal_id) if principal_id else (tool_name, model_name, btn)
    if tool_name == "evaluate_record_rules":
        permission = tool_args.get("permission") or "read"
        return (tool_name, model_name, principal_id, permission)
    if tool_name in _MODEL_KEYED_TOOLS:
        return (tool_name, model_name, principal_id) if principal_id else (tool_name, model_name)
    return None


def _truncate_observation(text: str, limit: int) -> str:
    """Truncate text to at most limit characters without cutting inside a token."""
    if len(text) <= limit:
        return text

    cut = text[:limit]
    newline = cut.rfind("\n")
    if newline > 0:
        cut = cut[:newline]
    else:
        space = cut.rfind(" ")
        if space > 0:
            cut = cut[:space]

    return cut + _TRUNCATION_MARKER


# Ceiling on the combined size of every tool observation recorded for a
# single question, regardless of how many tools contribute or how each
# one's own per-tool cap is set. Per-tool caps (2200-45000, see the
# dispatch_* modules) were each calibrated against a single worst-case
# model measured in isolation (todo/contexte.txt sections 801/803/808) --
# but on models with unusually broad surface area (account.move: measured
# up to 23401/42589/4014/2578 chars across 4 different tools, section 810)
# several of these per-tool caps can be hit in the same turn, and their sum
# can exceed the request-size limit enforced by the LLM provider (a real
# Groq 413 was observed at ~45000-50000 total chars of request content,
# including the ~4700-char CI_SYSTEM_PROMPT -- section 809). This budget
# keeps total observation content safely under that measured failure zone.
MAX_TOTAL_OBSERVATION_CHARS = 35000

# Per-tool observation caps -- single source of truth. Each was calibrated
# against a single worst-case model measured in isolation (sections
# 801/803/808/810). Consumed by the dispatch loop (below) and by any tool
# that needs to budget its own output internally instead of relying purely
# on the naive head-truncation applied here (see
# assemble_security_lock_blocks, code_intelligence/rules/security_evidence.py,
# section 824).
# Section 867/868: evaluate_record_rules was missing from this dict despite
# its own 2578-char account.move measurement already being on record in the
# comment above since section 810 -- it silently fell back to
# DEFAULT_OBSERVATION_CAP (2500), 78 chars short on that exact model, naive
# head-truncation dropping its closing CONCLUSION sentence (ACC-Q1 rejeu,
# section 867). Measured directly across the 12 real models referenced by
# the N1 question bank (account.move/maintenance.equipment/maintenance.
# request/purchase.order[.line]/sale.order[.line]/stock.lot/stock.move[.
# line]/stock.picking/stock.quant, permissions read/write/all): account.move
# is by far the worst case at 2578, everything else <=1041 -- 3000 gives
# ~16% headroom above the only real value observed near the old cap instead
# of shaving the default down to the exact measured byte.
# Section 893/894: who_has_access_to had the same gap (absent from this
# dict, silently falling back to DEFAULT_OBSERVATION_CAP) -- but its real
# worst case is far larger than evaluate_record_rules', because its output
# lists EVERY group in the system whose access derives from the queried
# model's permissions via implied_ids, and base.group_user is implied by
# almost every employee group -- so any model where base.group_user itself
# holds a permission repeats "(via implied_ids <- base.group_user)" for
# dozens of unrelated groups before ever reaching base.group_user's own
# direct entry. Confirmed root cause of STK-Q1's wrong answer (section
# 893): base.group_user's own direct WRITE grant on stock.move.line sits
# at byte 2639, past the old 2500-char DEFAULT_OBSERVATION_CAP, so the LLM
# synthesis never saw it and reported read-only access -- not a reasoning
# failure, the data was truncated away before reaching it. Measured
# directly across the same 12 models, permissions read/write/all:
# maintenance.request is the worst case at 9137 (stock.move.line close
# behind at 8837), everything else <=2664. 11000 gives >16% headroom above
# the measured worst case, same margin-over-measurement approach as above
# rather than an arbitrary round number.
PER_TOOL_OBSERVATION_CAPS: Dict[str, int] = {
    "read_source_code": 9000,
    "analyze_data_constraints": 45000,
    "analyze_method_override_chain": 2200,
    "analyze_server_actions": 3500,
    "analyze_security_locks": 3500,
    "evaluate_record_rules": 3000,
    "who_has_access_to": 11000,
}
DEFAULT_OBSERVATION_CAP = 2500


def _truncate_observation_for_budget(
    ctx: "DispatchContext", text: str, per_tool_limit: int,
) -> str:
    """Truncate an observation to the smaller of its own per-tool cap and
    the budget still remaining across every observation already recorded
    this turn (ctx.tool_observations) -- prevents any combination of tools
    from cumulatively producing a request large enough to trigger the LLM
    provider's payload-size limit, independently of each tool's own cap."""
    already_used = sum(len(o) for o in ctx.tool_observations)
    remaining = MAX_TOTAL_OBSERVATION_CHARS - already_used
    if remaining <= 0:
        logger.warning(
            "Node [code_intelligence_agent]: cumulative observation budget "
            "(%d chars) already exhausted by prior tools this turn -- this "
            "observation is dropped to a bare marker to protect against a "
            "provider payload-size error (see todo/contexte.txt section 810).",
            MAX_TOTAL_OBSERVATION_CHARS,
        )
        return _TRUNCATION_MARKER
    return _truncate_observation(text, min(per_tool_limit, remaining))
