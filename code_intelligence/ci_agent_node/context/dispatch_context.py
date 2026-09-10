"""
code_intelligence/ci_agent_node/dispatch_context.py

Mutable state threaded through every deterministic pre-dispatch block of
the CI agent's ReAct orchestration. Extracted from the former
ci_agent_node.py monolith (refactor, see todo/contexte.txt) -- each
pre-dispatch block used to repeat the same
append-observation/increment-hop/log-hop sequence inline; record_observation()
below is the single place that sequence now lives, called identically by
every predispatch_*.py module. Behavior unchanged.
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
