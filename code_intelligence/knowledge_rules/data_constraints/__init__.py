"""
Data Constraints Subpackage -- Semgrep-backed detection of _sql_constraints
and relational domain= declarations (Evidence tool 10/24).
"""

from code_intelligence.knowledge_rules.data_constraints.runner import SemgrepMatch, run_semgrep_analysis
from code_intelligence.knowledge_rules.data_constraints.analyzer import (
    DataConstraintsAnalysis,
    analyze_data_constraints_from_filepaths,
)

__all__ = [
    "SemgrepMatch",
    "run_semgrep_analysis",
    "DataConstraintsAnalysis",
    "analyze_data_constraints_from_filepaths",
]
