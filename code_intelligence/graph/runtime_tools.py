"""Read-only agent access to explicitly exported runtime metadata."""

import json
from langchain_core.tools import tool

from code_intelligence.agent.tool_helpers import _require_graph
from .runtime_graph import runtime_model_facts


@tool
def inspect_runtime_model(model_name: str) -> str:
    """Inspect a scoped model's exported fields, class source files, UI and security metadata.

    This is a dated technical snapshot, not a live requester access or approval verdict.
    Missing, truncated or out-of-scope metadata never proves absence of functionality.
    Source reads and requester-authorized live ORM reads remain necessary for behavior claims.
    """
    graph = _require_graph()
    if graph.graph.get('generation_mode') != 'runtime_metadata':
        return 'Error: No explicit runtime metadata snapshot is active.'
    result = runtime_model_facts(graph, model_name)
    if 'error' in result:
        return 'Error: ' + result['error']
    return json.dumps(result, ensure_ascii=False)
