"""Modeles attendus par question et classement d'une resolution (journal D-14).

Mesure l'exactitude d'une resolution, pas seulement le fait qu'elle ait abouti : un assistant
choisi a la place du bon modele est « resolu » pour l'audit mais « faux » ici.
"""

import json
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = PROJECT_ROOT / "tests" / "expected_models.json"

EXACT, PARTIAL, ABSTENTION, WRONG = "exact", "partiel", "abstention", "faux"


def load_expected_models(path: Optional[Path] = None) -> Tuple[Dict[str, frozenset], Dict[str, frozenset]]:
    """Retourne (attendus, toleres) par identifiant de question ; les cles `_...` sont reservees."""
    data = json.loads(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
    tolerated = data.get("_tolerated", {})
    expected = {qid: frozenset(models) for qid, models in data.items() if not qid.startswith("_")}
    return expected, {qid: frozenset(tolerated.get(qid, ())) for qid in expected}


def classify_resolution(resolved: Iterable[str], expected: frozenset, tolerated: frozenset = frozenset()) -> str:
    """exact : tous les attendus et rien hors attendus + toleres ; partiel : rien de faux mais des
    attendus manquent (au moins un present) ; abstention : vide ; faux : le reste."""
    models = frozenset(resolved)
    if not models:
        return ABSTENTION
    if not models <= (expected | tolerated):
        return WRONG
    present = models & expected
    if present == expected:
        return EXACT
    return PARTIAL if present else WRONG
