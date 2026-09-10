"""
tests/test_doc_nonregression.py

S13 non-regression test for the documentary RAG pipeline.
Verifies that adding ERP function calling did not degrade
answers on documentary questions (DOC-01 to DOC-10).

Usage:
    python3 tests/test_doc_nonregression.py
"""

import json
import os
import sys
import time
import logging
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.graph.graph import query_graph

logging.basicConfig(level=logging.ERROR)

RETRY_MAX = 3
RETRY_BASE_DELAY = 35  # seconds (Groq free tier resets every ~30s)
INTER_QUESTION_DELAY = 5  # seconds between questions to stay under TPM limit


def _query_with_retry(question, uid, api_key):
    """Call query_graph with retry and exponential backoff on rate limit errors."""
    for attempt in range(1, RETRY_MAX + 1):
        try:
            return query_graph(question, uid=uid, api_key=api_key)
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e):
                wait = RETRY_BASE_DELAY * attempt
                tqdm.write(f"  [Rate limit] Waiting {wait}s before retry {attempt}/{RETRY_MAX}...")
                time.sleep(wait)
            else:
                raise
    # Final attempt without catch
    return query_graph(question, uid=uid, api_key=api_key)


def run_doc_nonregression():
    with open("tests/benchmark_questions.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    # Filter to documentary questions only (DOC-01 to DOC-10)
    questions = [q for q in data["questions"] if q["category"] == "documentaire"]
    total = len(questions)
    correct = 0

    print(f"S13 Documentary Non-Regression Test")
    print(f"Running {total} documentary questions...\n")

    from erp_data.odoo_connector import OdooConnector
    _conn = OdooConnector()
    _password = "password123"
    uid = _conn.common.authenticate(_conn.db, "manager@miro.com", _password, {})
    if not uid:
        print("ERROR: Could not authenticate as manager@miro.com")
        sys.exit(1)
    print(f"Authenticated as Manager (UID: {uid})\n")

    results_log = []

    for i, q in enumerate(tqdm(questions, desc="Evaluating DOC")):
        if i > 0:
            time.sleep(INTER_QUESTION_DELAY)

        response = _query_with_retry(q["question"], uid=uid, api_key=_password)
        answer_lower = response.answer.lower()

        # Criteria 1: Expected keywords (at least 50% matched)
        keywords = [k.lower() for k in q.get("expected_answer_contains", [])]

        def _norm(s):
            return "".join(c for c in s if c.isalnum()).lower()

        norm_answer = _norm(answer_lower)
        matched_keywords = [k for k in keywords if (k in answer_lower or _norm(k) in norm_answer)]
        has_keywords = len(matched_keywords) >= max(1, len(keywords) // 2)

        # Criteria 2: Correct source document referenced
        import re
        raw_ref = q.get("source_reference", "")
        expected_files = re.findall(r"[\w_]+\.(?:pdf|txt|md)", raw_ref)
        
        has_source = any(
            any(ef in s.source or ef in s.title for ef in expected_files)
            for s in response.sources
        )

        is_correct = has_keywords and has_source
        if is_correct:
            correct += 1

        results_log.append({
            "id": q["id"],
            "question": q["question"],
            "answer_snippet": response.answer[:200],
            "passed": is_correct,
            "matched_keywords": matched_keywords,
            "missing_keywords": list(set(keywords) - set(matched_keywords)),
            "source_expected": expected_files,
            "source_found": has_source,
            "confidence": response.confidence
        })

    score = (correct / total) * 100

    print(f"\n\n{'='*50}")
    print(f"  S13 NON-REGRESSION RESULTS")
    print(f"{'='*50}")
    print(f"  Total Questions:  {total}")
    print(f"  Correct Answers:  {correct}")
    print(f"  Accuracy Score:   {score:.1f}%")
    print(f"  Target:           >= 85%")
    print(f"  Status:           {'PASS' if score >= 85 else 'FAIL'}")
    print(f"{'='*50}\n")

    failed = [r for r in results_log if not r["passed"]]
    if failed:
        print("--- FAILED QUESTIONS ---")
        for r in failed:
            print(f"[{r['id']}] {r['question']}")
            print(f"  Missing keywords: {r['missing_keywords']}")
            print(f"  Source found: {r['source_found']} (expected: {r['source_expected']})")
    else:
        print("All documentary questions passed!")

    # Write report
    captures_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures")
    os.makedirs(captures_dir, exist_ok=True)

    report_path = os.path.join(captures_dir, "doc_nonregression_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# S13 Documentary Non-Regression Report\n\n")
        f.write(f"**Score: {correct}/{total} ({score:.1f}%) - {'PASS' if score >= 85 else 'FAIL'}**\n\n")
        f.write("---\n\n")
        for r in results_log:
            status = "PASS" if r["passed"] else "FAIL"
            f.write(f"### [{r['id']}] {r['question']}\n")
            f.write(f"**Status:** {status}\n")
            f.write(f"**Answer:** {r['answer_snippet']}...\n")
            f.write(f"**Matched keywords:** {r['matched_keywords']}\n")
            if r["missing_keywords"]:
                f.write(f"**Missing keywords:** {r['missing_keywords']}\n")
            f.write(f"**Source found:** {r['source_found']} (expected: {r['source_expected']})\n\n")
            f.write("---\n\n")

    print(f"\nReport written to {report_path}")

    # Also save raw JSON
    json_path = os.path.join(captures_dir, "doc_nonregression_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results_log, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_doc_nonregression()
