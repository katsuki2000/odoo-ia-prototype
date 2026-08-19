"""
Test script for Step 7 Day 3: Evaluate routing accuracy on benchmark questions.

2026-08-19 (H1 prototype session): reranker disabled by default here.
On this dev machine (no AVX2, see EMBEDDING_BACKEND=local_light warning in
vectorstore/chroma_manager.py), the cross-encoder rerank in
vectorstore/search.py's retrieve() (a real PyTorch forward pass, not
cached per-query) made the un-modified eval_routing_accuracy.py take over
30 minutes for 37 questions and eventually crash the terminal. This is an
infra/hardware issue, unrelated to routing logic. use_reranker=False skips
only that final re-ranking step -- vector search + BM25 + RRF still run
for real, which is what route()'s chunk-dependent branches actually look
at. Pass RERANK=1 as an env var to run the original (slow, faithful)
path if you specifically need reranked chunk ordering for this check.
"""
import json
import logging
import os
from rag.graph import build_graph, retrieve, route
from vectorstore.search import get_retriever, retrieve as search_retrieve

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
        print("✅ Target achieved (>= 90%)")
    else:
        print("❌ Target missed (< 90%)")

if __name__ == "__main__":
    test_routing_accuracy()
