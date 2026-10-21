"""Section 1480 probe: exact-mention decisions on the 48 bank questions, before and after option A.

Offline (no server, no LLM, no embeddings). "Before" loads the saved copy of matching.py.
Run: .venv/bin/python3 .scratch/probe_1480_exact_mention.py
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from run_bloc_n1_benchmark import build_agent_state, load_questions  # noqa: E402
from code_intelligence.agent.resolution import exact_mention  # noqa: E402
from code_intelligence.agent.text_normalization import normalize_query_text  # noqa: E402
from code_intelligence.graph import get_code_intelligence_graph  # noqa: E402

SAVED_MATCHING = ROOT / ".scratch" / "matching.avant_1480.py"


def loadSavedMatching():
    spec = importlib.util.spec_from_file_location("code_intelligence.agent.matching_avant_1480", SAVED_MATCHING)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decide(question, graph):
    concept = exact_mention.resolve_exact_mention(normalize_query_text(question.lower().strip()), question, graph)
    if concept is None:
        return None
    return {"models": list(concept.resolved_models), "modules": list(concept.resolved_modules)}


def main():
    questions, _ = load_questions(None, None, None, None)
    saved = loadSavedMatching()
    current = (exact_mention._find_exact_technical_model_mentions, exact_mention._find_exact_technical_module_mentions)
    graphs = {}
    rows = []
    for item in questions:
        state = build_agent_state(item, False)
        language = state.get("language")
        if language not in graphs:
            graphs[language] = get_code_intelligence_graph(translation_languages=[language] if language else None, request_language=language)
        graph = graphs[language]
        after = decide(state["question"], graph)
        exact_mention._find_exact_technical_model_mentions = saved._find_exact_technical_model_mentions
        exact_mention._find_exact_technical_module_mentions = saved._find_exact_technical_module_mentions
        try:
            before = decide(state["question"], graph)
        finally:
            exact_mention._find_exact_technical_model_mentions, exact_mention._find_exact_technical_module_mentions = current
        rows.append((item["id"], before, after))

    def label(decision):
        if decision is None:
            return "-"
        return f"modules={decision['modules']} models={decision['models']}"

    print(f"{len(rows)} questions")
    print(f"decisions avant : {sum(1 for _, b, _a in rows if b)} ; apres : {sum(1 for _, _b, a in rows if a)}")
    for qid, before, after in rows:
        if before != after:
            print(f"CHANGE {qid}\n   avant : {label(before)}\n   apres : {label(after)}")
    unchanged = [qid for qid, before, after in rows if before and before == after]
    print(f"decisions inchangees : {unchanged}")


if __name__ == "__main__":
    main()
