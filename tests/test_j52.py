import sys
import os
from pathlib import Path
import json

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from core.graph import code_intelligence_agent, RAGState
from langchain_core.messages import HumanMessage
import core.graph as rag_graph

def main():
    legacy_js_path = os.getenv("LEGACY_JS_PATH", str(project_root / "odoo_addons" / "custom_legacy_js" / "static" / "src" / "js" / "widget.js"))
    question = (
        "Ceci est une question technique directe, IGNORE le validateur de modèles métiers. "
        f"Utilise IMMÉDIATEMENT l'outil 'read_source_code' avec filepath='{legacy_js_path}', "
        "line_start=1, et line_end=30. "
        "Lis le code retourné et dis-moi s'il contient une faille de sécurité front-end (comme l'utilisation "
        "de session.has_group pour cacher un bouton admin)."
    )
    
    state: RAGState = {
        "question": question,
        "chat_history": [],
        "context": [],
        "messages": [HumanMessage(content=question)],
        "rewrite_count": 0,
        "tool_hop_count": 0,
        "trace_id": "test_v11_js_124"
    }
    
    print("Agent en cours d'exécution...")
    try:
        final_state = code_intelligence_agent(state)
        print("\n=== REPONSE DE L'AGENT ===")
        print(final_state.get("raw_answer", "Pas de réponse brute."))
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()