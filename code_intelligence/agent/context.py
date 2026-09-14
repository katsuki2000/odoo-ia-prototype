"""
code_intelligence/ci_agent_node/constants.py

Static text/display constants for the CI agent node, extracted from the
former ci_agent_node.py monolith (refactor, see todo/contexte.txt).
"""

_EXECUTION_FAILURE_NOTICE = (
    "\n\n[ATTENTION] Une ou plusieurs analyses Code Intelligence n'ont pas pu "
    "s'ex\u00e9cuter correctement pour cette question (panne technique d'un ou "
    "plusieurs outils). La r\u00e9ponse ci-dessus peut donc \u00eatre incompl\u00e8te ; "
    "n'y voyez pas une absence confirm\u00e9e d'information."
)

# ── Human-readable labels for sources built from tool observations ─────────
# (section: réponses trop techniques, todo/contexte.txt) -- used only for
# SourceReference.title in the dépliant; falls back to the raw tool name
# for anything not listed here (e.g. new tools added later).
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

"""
code_intelligence/ci_agent_node/dispatch_context.py
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class DispatchContext:
    G: Any
    concept: Any
    question: str
    tool_map: Dict[str, Any]
    resolved_user_group_xmlids: List[str]
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

    # Populated during the ReAct loop (react_loop.py), not by the
    # pre-dispatch blocks -- kept here so both phases share one place for
    # the per-turn metrics eventually written into `timing` (runner.py).
    llm_call_count: int = 0
    groq_wait: float = 0.0
    per_hop_times: List[float] = field(default_factory=list)
    synthesis_time: float = 0.0

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
code_intelligence/ci_agent_node/early_refusal.py

Shared builder for the 3 early-refusal paths of the CI agent (out-of-scope,
prompt injection, massive extraction) -- these were 3 duplicated blocks in
the former ci_agent_node.py monolith, unified here (refactor, see
todo/contexte.txt). Behavior unchanged.
"""

import time

from core.schemas import AssistantResponse


def build_early_refusal_response(
    answer: str, trace_logger, trace_id: str, question: str,
    start_time: float, state: dict, hop_cap: int,
) -> dict:
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
code_intelligence/ci_agent_node/group_resolution.py

Real Odoo group DB ID -> xml_id resolution, extracted from the former
ci_agent_node.py monolith (refactor, see todo/contexte.txt). Behavior
unchanged: core.graph.graph keeps an independent copy of these globals
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
    name); a reset on that copy is now mirrored here too, so a stale client
    left over from an earlier test can never leak through (contexte.txt
    section 256).
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
code_intelligence/ci_prompt_and_heuristics.py

System prompt, hop limits, tool call deduplication, and observation truncation helpers.
"""

import logging
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

from code_intelligence.utils import _TRUNCATION_MARKER, _match_near_truncation


# Maximum hops allowed per question.
CI_MAX_HOPS = 4

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
    """Single source of truth for the seen_calls dedup key."""
    model_name = tool_args.get("model_name")
    if not model_name:
        return None
    if tool_name == "analyze_method_override_chain":
        method_name = tool_args.get("method_name")
        return (tool_name, model_name, method_name) if method_name else None
    if tool_name == "button_execution_path":
        btn = tool_args.get("button_name") or tool_args.get("button_identifier")
        return (tool_name, model_name, btn) if btn else None
    if tool_name in _MODEL_KEYED_TOOLS:
        return (tool_name, model_name)
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
