"""Graph integrity verification: cycles, topological sort, event logging."""

"""
code_intelligence/graph/cycle_detector.py

Inheritance cycle detection across Odoo models.
"""

import logging
from typing import Dict, List, Set

from .nodes import ResolvedSymbolRegistry

_logger = logging.getLogger(__name__)


def _detect_inheritance_cycles(registry: ResolvedSymbolRegistry):
    """
    Detect inheritance cycles across models using visited: set().
    Fills registry.detected_cycles with detected cycle paths.
    Note: In-place model extensions (_inherit = 'model.name') where parent == model_name
    are excluded from cycle detection.
    """
    # Build model dependency graph excluding self-extensions (in-place module extensions)
    inheritance_graph: Dict[str, List[str]] = {}
    for model_name, decls in registry.models.items():
        parents = []
        for decl in decls:
            parents.extend(decl.inherit)
            parents.extend(decl.inherits.keys())
        # Exclude self-references (in-place _inherit = 'same.model')
        inheritance_graph[model_name] = [p for p in parents if p != model_name]

    visited: Set[str] = set()
    rec_stack: Set[str] = set()

    def dfs(node: str, path: List[str]):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for parent in inheritance_graph.get(node, []):
            if parent == node:
                continue
            if parent not in visited:
                dfs(parent, path)
            elif parent in rec_stack:
                cycle_start_idx = path.index(parent)
                cycle_path = path[cycle_start_idx:] + [parent]
                _logger.warning("Inheritance cycle detected: %s", " -> ".join(cycle_path))
                registry.detected_cycles.append(cycle_path)

        path.pop()
        rec_stack.remove(node)

    for model_name in list(inheritance_graph.keys()):
        if model_name not in visited:
            dfs(model_name, [])


__all__ = ["_detect_inheritance_cycles"]

# ── Topological Sort ─────────────────────────────────────────────────────

"""
code_intelligence/graph/topological_sort.py

Topological sort for Odoo module dependency resolution.
"""

import logging
from typing import Dict, List, Set

from .nodes import ParsedModule

_logger = logging.getLogger(__name__)


def topological_sort_modules(modules_dict: Dict[str, ParsedModule]) -> List[str]:
    """
    Topologically sort module names based on manifest 'depends'.
    Ensures parent modules are indexed before dependent modules.
    """
    sorted_modules: List[str] = []
    visited: Set[str] = set()

    def visit(m_name: str, chain: List[str]):
        if m_name in chain:
            _logger.warning("Circular dependency detected in manifests: %s", " -> ".join(chain + [m_name]))
            return
        if m_name not in visited:
            visited.add(m_name)
            mod = modules_dict.get(m_name)
            if mod and mod.manifest:
                for dep in mod.manifest.depends:
                    visit(dep, chain + [m_name])
            elif mod is not None:
                _logger.warning(
                    "Module '%s' has no manifest (or no manifest.depends) -- "
                    "treating it as having NO dependencies for load-order "
                    "purposes. If '%s' actually depends on other modules, this "
                    "will silently produce a wrong load_order and a wrong "
                    "method-override execution order for any method it shares "
                    "with those dependencies.",
                    m_name, m_name,
                )
            sorted_modules.append(m_name)

    for name in modules_dict:
        visit(name, [])

    return sorted_modules


__all__ = ["topological_sort_modules"]

# ── Event Logger ─────────────────────────────────────────────────────────

"""
code_intelligence/incremental_event_logger.py

Incremental Event Logger & Recalculation Performance Budget:
- Logs structured graph events (STALENESS_CHECK, INCREMENTAL_RECALC, FULL_REBUILD, ATOMIC_SWAP)
  to an append-only JSONL log file.
- Tracks fine-grained latency per recalculation phase.
- Enforces partial recalculation performance budget target.
"""

import datetime
import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Any, Optional

_logger = logging.getLogger(__name__)

LATENCY_BUDGET_PARTIAL_RECALC_SECONDS = 2.0  # 2.0s target for partial recalculation on 1 modified module


@dataclass
class IncrementalEvent:
    event_type: str                  # "STALENESS_CHECK", "INCREMENTAL_RECALC", "FULL_REBUILD", "ATOMIC_SWAP"
    timestamp: str
    staleness_level: int
    dirty_nodes_count: int
    propagated_nodes_count: int
    affected_cross_edges_count: int
    detection_time_ms: float
    recalc_time_ms: float
    swap_time_ms: float
    total_time_ms: float
    reason: str
    changed_files: List[str]
    within_budget: bool


class IncrementalEventLogger:
    """Appends structured incremental graph events to a JSONL file."""

    def __init__(self, log_filepath: Optional[Path] = None):
        if log_filepath is None:
            log_filepath = Path(__file__).resolve().parent.parent / "captures" / "incremental_events.jsonl"
        self.log_filepath = Path(log_filepath)
        self.log_filepath.parent.mkdir(parents=True, exist_ok=True)

    def log_event(self, event: IncrementalEvent) -> None:
        """Append an event record to the JSONL log file."""
        try:
            line = json.dumps(asdict(event), ensure_ascii=False)
            with open(self.log_filepath, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            _logger.info(
                "Incremental Event [%s]: level=%d total=%.2fms (within_budget=%s)",
                event.event_type, event.staleness_level, event.total_time_ms, event.within_budget,
            )
        except Exception as e:
            _logger.error("Failed to write incremental event log: %s", e)

    def read_recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Read the N most recent event records from the log file."""
        if not self.log_filepath.exists():
            return []
        events = []
        try:
            with open(self.log_filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
        except Exception as e:
            _logger.error("Failed to read incremental event log: %s", e)
        return events[-limit:]


def record_incremental_update(
    event_type: str,
    staleness_level: int,
    dirty_nodes: List[str],
    propagated_nodes: List[str],
    affected_cross_edges: List[Any],
    detection_time_ms: float,
    recalc_time_ms: float,
    swap_time_ms: float,
    reason: str,
    changed_files: List[str],
    logger_instance: Optional[IncrementalEventLogger] = None,
) -> IncrementalEvent:
    """
    Constructs an IncrementalEvent, evaluates budget compliance (< 2.0s),
    and records it to the event journal.
    """
    total_time_ms = detection_time_ms + recalc_time_ms + swap_time_ms
    within_budget = (total_time_ms / 1000.0) <= LATENCY_BUDGET_PARTIAL_RECALC_SECONDS

    event = IncrementalEvent(
        event_type=event_type,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        staleness_level=staleness_level,
        dirty_nodes_count=len(dirty_nodes),
        propagated_nodes_count=len(propagated_nodes),
        affected_cross_edges_count=len(affected_cross_edges),
        detection_time_ms=round(detection_time_ms, 3),
        recalc_time_ms=round(recalc_time_ms, 3),
        swap_time_ms=round(swap_time_ms, 3),
        total_time_ms=round(total_time_ms, 3),
        reason=reason,
        changed_files=changed_files,
        within_budget=within_budget,
    )

    if logger_instance is None:
        logger_instance = IncrementalEventLogger()

    logger_instance.log_event(event)
    return event
