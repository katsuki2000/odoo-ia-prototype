"""
tests/eval_rag.py

Run full benchmark on all questions from benchmark_questions.json.
Goal: >= 90% correctly sourced answers containing expected keywords.
"""

import json
import os
import sys
import logging
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import ODOO_DB
from core.graph.graph import query_graph

logging.basicConfig(level=logging.ERROR) # keep it clean for progress bar

def run_evaluation():
    with open("tests/benchmark_questions.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    questions = data["questions"]
    total = len(questions)
    correct = 0
    
    print(f"Starting RAG evaluation on {total} questions...\n")
    
    from erp_data.odoo_connector import OdooConnector
    _conn = OdooConnector(db=ODOO_DB)
    _charlie_password = "password123"
    charlie_uid = _conn.common.authenticate(_conn.db, "charlie@alpha.com", _charlie_password, {})
    if not charlie_uid:
        print("ERROR: Could not authenticate as charlie@alpha.com")
        sys.exit(1)
    print(f"Authenticated as Charlie CRM (UID: {charlie_uid})")
    
    results_log = []
    
    for q in tqdm(questions, desc="Evaluating RAG Pipeline"):
        response = query_graph(q["question"], uid=charlie_uid, api_key=_charlie_password, db=ODOO_DB)
        
        answer_lower = response.answer.lower()
        
        # 1. Check out-of-scope logic
        if q["category"] == "hors_perimetre":
            is_correct = "this question is outside my scope" in answer_lower
            
            results_log.append({
                "id": q["id"],
                "question": q["question"],
                "passed": is_correct,
                "reason": "Out of scope handled correctly" if is_correct else f"Failed to refuse. Answer: {response.answer}",
                "confidence": response.confidence
            })
            if is_correct:
                correct += 1
            continue

        # 2. Check in-scope questions
        # Criteria 1: Expected keywords
        keywords = [k.lower() for k in q.get("expected_answer_contains", [])]
        
        # Helper to normalize strings for flexible matching (e.g. "sale.order" -> "saleorder")
        def _norm(s):
            return "".join(c for c in s if c.isalnum()).lower()
            
        norm_answer = _norm(answer_lower)
        matched_keywords = [k for k in keywords if (k in answer_lower or _norm(k) in norm_answer)]
        
        # Allow passing if at least 50% of the keywords are present to account for LLM paraphrasing
        has_keywords = len(matched_keywords) >= max(1, len(keywords) // 2)
        
        # Criteria 2: Correct source
        # Extract filename (e.g. "manuel_facturation.pdf" from "manuel_facturation.pdf — section 1")
        expected_source = q.get("source_reference", "").split("—")[0].strip()
        has_source = any(expected_source in s.source or expected_source in s.title for s in response.sources)
        
        is_correct = has_keywords and has_source
        if is_correct:
            correct += 1
            
        results_log.append({
            "id": q["id"],
            "question": q["question"],
            "passed": is_correct,
            "reason": (
                "Pass" if is_correct else 
                f"Missing keywords: {set(keywords) - set(matched_keywords)} or Source mismatch (Expected: {expected_source})"
            ),
            "confidence": response.confidence
        })

    score = (correct / total) * 100
    print(f"\n\n--- RESULTS ---")
    print(f"Total Questions: {total}")
    print(f"Correct Answers: {correct}")
    print(f"Accuracy Score:  {score:.1f}%\n")
    
    print("--- FAILED QUESTIONS ---")
    failed = [r for r in results_log if not r["passed"]]
    if failed:
        for r in failed:
            print(f"[{r['id']}] {r['question']}")
            print(f"  -> {r['reason']}")
    else:
        print("None! 100% perfect.")
            
    # Make sure captures directory exists relative to project root
    os.makedirs(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures"), exist_ok=True)
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures", "rag_eval_results.json"), "w", encoding="utf-8") as f:
        json.dump(results_log, f, indent=2)

if __name__ == "__main__":
    run_evaluation()
