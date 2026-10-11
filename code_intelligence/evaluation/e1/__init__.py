"""E1 offline hybrid-retrieval experiment (protocol section 1227).

Does not change MIRO production behaviour. Compares resolution systems R0-R5
on a calibration set C, then a single frozen held-out pass after config lock.
"""

from .bm25_index import Bm25CardIndex
from .cards import NodeCard, build_node_cards
from .cases import E1Case, dataset_digest, load_calibration_cases
from .config import load_e1_config
from .dense_index import DenseCardIndex
from .metrics import score_resolution_case, summarize_system_scores
from .systems import run_system

__all__ = [
    "Bm25CardIndex",
    "DenseCardIndex",
    "E1Case",
    "NodeCard",
    "build_node_cards",
    "dataset_digest",
    "load_calibration_cases",
    "load_e1_config",
    "run_system",
    "score_resolution_case",
    "summarize_system_scores",
]
