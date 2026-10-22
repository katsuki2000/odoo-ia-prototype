"""Benchmark routing accuracy; cross-encoder reranking is opt-in via RERANK=1."""
import json
import logging
import os
from core.graph.graph import route
from document_rag.vectorstore.search import get_retriever, retrieve as search_retrieve

# Setup basic logging to suppress noisy output
logging.basicConfig(level=logging.WARNING)

USE_RERANKER = os.environ.get("RERANK") == "1"


def test_routing_accuracy():
    with open("tests/benchmark_questions.json", "r") as f:
        data = json.load(f)
        
    correct = 0
    total = len(data["questions"])
    
    print(f"Testing {total} questions for routing accuracy (reranker={'on' if USE_RERANKER else 'off, fast mode'})...\n")
    
    chroma_manager, bm25_index = get_retriever()

    for q in data["questions"]:
        question = q["question"]
        category = q["category"]
        
        state = {
            "question": question,
            "chat_history": [],
            "retrieved_chunks": [],
            "raw_answer": "",
            "route": None,
            "response": None,
            "uid": 1
        }
        
        try:
            # 1. Retrieve (reranker skipped by default -- see module docstring)
            chunks = search_retrieve(
                query=question,
                top_k=10,
                chroma_manager=chroma_manager,
                bm25_index=bm25_index,
                use_reranker=USE_RERANKER,
            )
            state["retrieved_chunks"] = chunks
            
            # 2. Route
            state.update(route(state))
            chosen_route = state.get("route")
            
            # Determine expected route
            expected_route = "donnees_erp" if category == "erp_chiffre" else "documentaire"
            
            is_correct = (chosen_route == expected_route)
            if is_correct:
                correct += 1
            else:
                print(f"[FAIL] Q: {question}")
                print(f"       Expected: {expected_route}, Got: {chosen_route}")
                
        except Exception as e:
            print(f"[ERROR] Q: {question} -> {str(e)}")
            
    accuracy = (correct / total) * 100
    print(f"\nAccuracy: {correct}/{total} ({accuracy:.1f}%)")
    
    if accuracy >= 90.0:
        print(" Target achieved (>= 90%)")
    else:
        print(" Target missed (< 90%)")

if __name__ == "__main__":
    test_routing_accuracy()
