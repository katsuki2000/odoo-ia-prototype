import importlib.util, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from code_intelligence.agent.resolution import exact_mention
from code_intelligence.agent.text_normalization import normalize_query_text
from code_intelligence.graph import get_code_intelligence_graph

spec = importlib.util.spec_from_file_location("code_intelligence.agent.matching_avant_1480", ROOT / ".scratch" / "matching.avant_1480.py")
saved = importlib.util.module_from_spec(spec); spec.loader.exec_module(saved)
current = (exact_mention._find_exact_technical_model_mentions, exact_mention._find_exact_technical_module_mentions)

QUESTIONS = [
    "Est-ce qu'une règle de gestion bloque la validation des congés urgents ?",
    "Quelles sont les règles de visibilité pour les prêts de matériel ?",
    "Un employé peut-il voir les documents deep sans autorisation ?",
]
graph = get_code_intelligence_graph()

def decide(question):
    concept = exact_mention.resolve_exact_mention(normalize_query_text(question.lower().strip()), question, graph)
    return None if concept is None else (list(concept.resolved_modules), list(concept.resolved_models))

for question in QUESTIONS:
    after = decide(question)
    exact_mention._find_exact_technical_model_mentions = saved._find_exact_technical_model_mentions
    exact_mention._find_exact_technical_module_mentions = saved._find_exact_technical_module_mentions
    before = decide(question)
    exact_mention._find_exact_technical_model_mentions, exact_mention._find_exact_technical_module_mentions = current
    print(f"{question[:60]!r}\n   avant : {before}\n   apres : {after}\n   identique : {before == after}")
