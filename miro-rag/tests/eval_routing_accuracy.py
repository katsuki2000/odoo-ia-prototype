"""
Test script for Step 7 Day 3: Evaluate routing accuracy on benchmark questions.
"""
import json
import logging
from rag.graph import build_graph, retrieve, route

# Setup basic logging to suppress noisy output
logging.basicConfig(level=logging.WARNING)

def test_routing_accuracy():
    with open("tests/benchmark_questions.json", "r") as f:
        data = json.load(f)
        
    app = build_graph()
    correct = 0
    total = len(data["questions"])
    
    print(f"Testing {total} questions for routing accuracy...\n")
    
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
            # 1. Retrieve
            state.update(retrieve(state))
            
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
