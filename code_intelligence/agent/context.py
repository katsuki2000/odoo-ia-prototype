"""Agent execution context, metadata group lookup and observation budgets."""

import logging
import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, List, Optional, Set

from config.settings import CI_MAX_HOPS
from code_intelligence.utils import _TRUNCATION_MARKER

logger = logging.getLogger(__name__)
_EXECUTION_FAILURE_NOTICE = (
    "\n\n[ATTENTION] Une ou plusieurs analyses n'ont pas pu "
    "s'exécuter correctement pour cette question. La réponse ci-dessus peut donc être incomplète ; "
    "n'y voyez pas une absence confirmée d'information.")
_CI_TOOL_DISPLAY_NAMES = {
    'analyze_security_locks': 'Verrous de sécurité (code Python)',
    'analyze_server_actions': 'Actions serveur / automatisations',
    'analyze_method_override_chain': 'Chaîne de surcharge de méthode',
    'who_has_access_to': "Matrice d'accès (ACL)",
    'requester_acl_summary': 'Verdict ACL du demandeur',
    'evaluate_record_rules': "Règles d'enregistrement (ir.rule)",
    'analyze_data_constraints': 'Contraintes de données (Semgrep)',
    'field_change_impact': 'Impact de modification de champ',
    'button_execution_path': "Chemin d'exécution du bouton",
    'trace_full_inheritance': 'Héritage complet du modèle',
    'describe_workflow': 'Workflow (états)',
    'resolve_technical_name': 'Résolution de rôle technique',
    'list_involved_modules': 'Modules impliqués',
    'explain_decision_path': 'Explication du chemin de décision',
    'read_source_code': 'Lecture de code source',
}


@dataclass
class DispatchContext:
    G: Any
    concept: Any
    question: str
    tool_map: Dict[str, Any]
    resolved_user_group_xmlids: Optional[List[str]]
    trace_logger: Any
    trace_id: str
    hop_cap: int
    requester_groups_known: bool = False
    tool_observations: List[str] = field(default_factory=list)
    tool_observation_models: List[str] = field(default_factory=list)
    tool_observation_tools: List[str] = field(default_factory=list)
    omitted_items: List[Any] = field(default_factory=list)
    seen_calls: Set[Any] = field(default_factory=set)
    hop_count: int = 0
    hop_index: int = 0
    llm_call_count: int = 0
    llm_wait: float = 0.0
    per_hop_times: List[float] = field(default_factory=list)
    synthesis_time: float = 0.0
    security_principals: Dict[str, List[str]] = field(default_factory=dict)
    fallback_reason: Optional[str] = None
    final_message_preview: Optional[str] = None

    @property
    def hop_budget_exhausted(self) -> bool:
        return self.hop_count >= self.hop_cap

def build_early_refusal_response(answer: str, trace_logger, trace_id: str, question: str,
                                start_time: float, state: dict, hop_cap: int) -> dict:
    from core.schemas import AssistantResponse
    response = AssistantResponse(answer=answer, sources=[], confidence=0.0)
    timing = state.get('timing', {}).copy()
    timing['code_intelligence_time'] = time.time() - start_time
    trace_logger.log_summary(trace_id=trace_id, branch='code_intelligence', question=question,
        hop_count=0, llm_call_count=0, total_time_ms=timing['code_intelligence_time'] * 1000, hop_cap=hop_cap)
    return {'response': response, 'raw_answer': response.answer, 'timing': timing}


_GROUP_XMLID_CACHE: dict = {}
_ADMIN_RPC_CLIENT = None
_ADMIN_RPC_UID = None
_GROUP_RESOLUTION_LOCK = RLock()


def _get_admin_rpc_client():
    """Single owner of the configured instance's metadata-only RPC connection."""
    global _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID
    with _GROUP_RESOLUTION_LOCK:
        if _ADMIN_RPC_CLIENT is None:
            from code_intelligence.agent.rpc_client import OdooRpcClient
            client = OdooRpcClient()
            adminUid = client.authenticate_admin()
            _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID = client, adminUid
        return _ADMIN_RPC_CLIENT, _ADMIN_RPC_UID


def _resolve_user_group_xmlids(group_ids) -> list:
    if not group_ids:
        return []
    with _GROUP_RESOLUTION_LOCK:
        for group in group_ids:
            if isinstance(group, str) and ('.' in group or not group.isdigit()):
                _GROUP_XMLID_CACHE[group] = group
        uncached = [group for group in group_ids if group not in _GROUP_XMLID_CACHE]
        if uncached:
            try:
                client, adminUid = _get_admin_rpc_client()
                _GROUP_XMLID_CACHE.update(client.get_group_xmlids(adminUid, uncached))
            except Exception as error:
                logger.error('Group ID resolution failed (%s); unresolved groups remain unknown.', type(error).__name__)
        return [_GROUP_XMLID_CACHE[group] for group in group_ids if group in _GROUP_XMLID_CACHE]


def _truncate_observation(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    newline = cut.rfind('\n')
    if newline > 0:
        cut = cut[:newline]
    else:
        space = cut.rfind(' ')
        if space > 0:
            cut = cut[:space]
    return cut + _TRUNCATION_MARKER


MAX_TOTAL_OBSERVATION_CHARS = 35000
PER_TOOL_OBSERVATION_CAPS: Dict[str, int] = {
    'read_source_code': 9000, 'analyze_data_constraints': 45000,
    'analyze_method_override_chain': 2200, 'analyze_server_actions': 3500,
    'analyze_security_locks': 14600, 'evaluate_record_rules': 3000, 'who_has_access_to': 11000,
}
DEFAULT_OBSERVATION_CAP = 2500


def _truncate_observation_for_budget(ctx: DispatchContext, text: str, per_tool_limit: int) -> str:
    remaining = MAX_TOTAL_OBSERVATION_CHARS - sum(len(obs) for obs in ctx.tool_observations)
    if remaining <= 0:
        logger.warning('Cumulative observation budget exhausted; observation omitted.')
        return _TRUNCATION_MARKER
    return _truncate_observation(text, min(per_tool_limit, remaining))
