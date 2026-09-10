"""
code_intelligence/ci_agent_node/__init__.py

Package facade for the CI agent node -- replaces the former
ci_agent_node.py monolith (refactor: orchestrator ReAct loop, deterministic
pre-dispatch, and synthesis split into dedicated submodules, see
todo/contexte.txt). Re-exports the same public surface the monolith used
to expose, so `from code_intelligence.ci_agent_node import ...` (used by
core/graph.py and elsewhere) keeps working unchanged.
"""

from code_intelligence.ci_agent_node.context.group_resolution import (
    _GROUP_XMLID_CACHE,
    _ADMIN_RPC_CLIENT,
    _ADMIN_RPC_UID,
    _get_admin_rpc_client,
    _resolve_user_group_xmlids,
)
from code_intelligence.ci_agent_node.context.constants import (
    _EXECUTION_FAILURE_NOTICE,
    _CI_TOOL_DISPLAY_NAMES,
)
from code_intelligence.ci_agent_node.loop.runner import (
    CodeIntelligenceAgentRunner,
    code_intelligence_agent,
)

__all__ = [
    "_GROUP_XMLID_CACHE",
    "_ADMIN_RPC_CLIENT",
    "_ADMIN_RPC_UID",
    "_get_admin_rpc_client",
    "_resolve_user_group_xmlids",
    "_EXECUTION_FAILURE_NOTICE",
    "_CI_TOOL_DISPLAY_NAMES",
    "CodeIntelligenceAgentRunner",
    "code_intelligence_agent",
]
