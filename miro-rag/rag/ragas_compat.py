"""
miro-rag/rag/ragas_compat.py

Compatibility helper ensuring `ragas` imports cleanly with modern `langchain-community` (0.4.x)
and `langchain-google-vertexai` where `ChatVertexAI` and `VertexAI` were moved out of `langchain_community`.
"""

import sys

def init_ragas_compatibility():
    """Injects vertexai shims into sys.modules before importing ragas."""
    try:
        import langchain_google_vertexai
        sys.modules["langchain_community.chat_models.vertexai"] = langchain_google_vertexai
        import langchain_community.llms
        if not hasattr(langchain_community.llms, "VertexAI"):
            setattr(langchain_community.llms, "VertexAI", langchain_google_vertexai.VertexAI)
    except Exception as e:
        pass

# Auto-initialize when imported
init_ragas_compatibility()
