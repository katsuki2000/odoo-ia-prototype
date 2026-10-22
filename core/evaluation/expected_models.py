"""Expected models per question, and classification of a resolution.

Measures whether a resolution is exact, not just whether it succeeded: an assistant model
chosen in place of the right one counts as "resolved" for the audit but as "wrong" here.
"""

import json
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = PROJECT_ROOT / "tests" / "expected_models.json"

EXACT, PARTIAL, ABSTENTION, WRONG = "exact", "partiel", "abstention", "faux"


def load_expected_models(path: Optional[Path] = None) -> Tuple[Dict[str, frozenset], Dict[str, frozenset]]:
    """Return (expected, tolerated) by question id; keys starting with `_` are reserved."""
    data = json.loads(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
    tolerated = data.get("_tolerated", {})
    expected = {qid: frozenset(models) for qid, models in data.items() if not qid.startswith("_")}
    return expected, {qid: frozenset(tolerated.get(qid, ())) for qid in expected}


def classify_resolution(resolved: Iterable[str], expected: frozenset, tolerated: frozenset = frozenset()) -> str:
    """exact: every expected model and nothing outside expected + tolerated; partial: nothing wrong
    but some expected models are missing (at least one present); abstention: empty; wrong: the rest."""
    models = frozenset(resolved)
    if not models:
        return ABSTENTION
    if not models <= (expected | tolerated):
        return WRONG
    present = models & expected
    if present == expected:
        return EXACT
    return PARTIAL if present else WRONG
