"""pytest plugin (section 1480): run with the exact-mention finders of matching.avant_1480.py."""
import importlib.util
from pathlib import Path

from code_intelligence.agent.resolution import exact_mention

_saved_path = Path(__file__).resolve().parent / "matching.avant_1480.py"
_spec = importlib.util.spec_from_file_location("code_intelligence.agent.matching_avant_1480", _saved_path)
_saved = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_saved)
exact_mention._find_exact_technical_model_mentions = _saved._find_exact_technical_model_mentions
exact_mention._find_exact_technical_module_mentions = _saved._find_exact_technical_module_mentions
