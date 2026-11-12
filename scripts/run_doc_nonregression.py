#!/usr/bin/env python3
"""Check that the documentary questions of the benchmark still get a correct, sourced answer."""

import argparse
import json
import logging
import re
import sys
import time
import xmlrpc.client
from pathlib import Path

from tqdm import tqdm

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from config import settings
from core.graph.graph import query_graph
from core.schemas import QueryRoute
from erp_data.connector.odoo_connector import OdooConnectorError
from evaluation.odoo_auth import authenticate_odoo
from evaluation.preflight import BackendUnavailable

QUESTIONS_PATH = project_root / "evaluation" / "data" / "benchmark_questions.json"
CAPTURES_DIR = project_root / "captures"
CATEGORY = "documentaire"
TARGET_PERCENT = 85
RETRY_MAX = 3
RETRY_BASE_DELAY_SECONDS = 35
INTER_QUESTION_DELAY_SECONDS = 5
SOURCE_FILE = re.compile(r"[\w_]+\.(?:pdf|txt|md)")
ODOO_ERRORS = (BackendUnavailable, OSError, xmlrpc.client.Error, OdooConnectorError)


def load_questions():
    with QUESTIONS_PATH.open(encoding="utf-8") as file:
        return [item for item in json.load(file)["questions"] if item["category"] == CATEGORY]


def ask(question, uid, password):
    return query_graph(
        question, QueryRoute.DOCUMENTARY.value, uid=uid, api_key=password, db=settings.ODOO_DB,
    )


def ask_with_retry(question, uid, password):
    for attempt in range(1, RETRY_MAX + 1):
        try:
            return ask(question, uid, password)
        except Exception as error:
            if "429" not in str(error) and "rate_limit" not in str(error):
                raise
            wait = RETRY_BASE_DELAY_SECONDS * attempt
            tqdm.write(f"  [Rate limit] Waiting {wait}s before retry {attempt}/{RETRY_MAX}...")
            time.sleep(wait)
    return ask(question, uid, password)


def squash(text):
    return "".join(char for char in text if char.isalnum()).lower()


def evaluate(question, response):
    answer = response.answer.lower()
    squashed_answer = squash(answer)
    keywords = [keyword.lower() for keyword in question.get("expected_answer_contains", [])]
    matched = [keyword for keyword in keywords if keyword in answer or squash(keyword) in squashed_answer]
    expected_files = SOURCE_FILE.findall(question.get("source_reference", ""))
    source_found = any(
        name in source.source or name in source.title
        for source in response.sources
        for name in expected_files
    )
    return {
        "id": question["id"],
        "question": question["question"],
        "answer_snippet": response.answer[:200],
        "passed": len(matched) >= max(1, len(keywords) // 2) and source_found,
        "matched_keywords": matched,
        "missing_keywords": [keyword for keyword in keywords if keyword not in matched],
        "source_expected": expected_files,
        "source_found": source_found,
        "confidence": response.confidence,
    }


def accuracy(results):
    return sum(result["passed"] for result in results) / len(results) * 100


def verdict(results):
    return "PASS" if accuracy(results) >= TARGET_PERCENT else "FAIL"


def print_summary(results):
    rule = "=" * 50
    print(f"\n\n{rule}\n  DOCUMENTARY NON-REGRESSION RESULTS\n{rule}")
    print(f"  Total Questions:  {len(results)}")
    print(f"  Correct Answers:  {sum(result['passed'] for result in results)}")
    print(f"  Accuracy Score:   {accuracy(results):.1f}%")
    print(f"  Target:           >= {TARGET_PERCENT}%")
    print(f"  Status:           {verdict(results)}\n{rule}\n")
    failed = [result for result in results if not result["passed"]]
    if not failed:
        print("All documentary questions passed!")
        return
    print("--- FAILED QUESTIONS ---")
    for result in failed:
        print(f"[{result['id']}] {result['question']}")
        print(f"  Missing keywords: {result['missing_keywords']}")
        print(f"  Source found: {result['source_found']} (expected: {result['source_expected']})")


def write_reports(results):
    CAPTURES_DIR.mkdir(exist_ok=True)
    correct = sum(result["passed"] for result in results)
    lines = [
        "# Documentary Non-Regression Report\n",
        f"**Score: {correct}/{len(results)} ({accuracy(results):.1f}%) - {verdict(results)}**\n",
        "---\n",
    ]
    for result in results:
        lines += [
            f"### [{result['id']}] {result['question']}",
            f"**Status:** {'PASS' if result['passed'] else 'FAIL'}",
            f"**Answer:** {result['answer_snippet']}...",
            f"**Matched keywords:** {result['matched_keywords']}",
            *([f"**Missing keywords:** {result['missing_keywords']}"] if result["missing_keywords"] else []),
            f"**Source found:** {result['source_found']} (expected: {result['source_expected']})\n",
            "---\n",
        ]
    report_path = CAPTURES_DIR / "doc_nonregression_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    (CAPTURES_DIR / "doc_nonregression_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(f"\nReport written to {report_path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Documentary non-regression of the question benchmark.")
    parser.add_argument("--login", required=True, help="Odoo user login the questions are asked as")
    args = parser.parse_args(argv)
    password = settings.ODOO_BENCH_PASSWORD
    if not password:
        parser.error("ODOO_BENCH_PASSWORD must be set in the backend .env")
    questions = load_questions()
    if not questions:
        parser.error(f"No '{CATEGORY}' question in {QUESTIONS_PATH.name}.")

    try:
        uid = authenticate_odoo(args.login, password)
    except ODOO_ERRORS as error:
        print(f"[ERROR] Odoo authentication failed: {type(error).__name__}: {error}")
        return 2
    print(f"Authenticated to Odoo as {args.login} (uid {uid}).\nRunning {len(questions)} documentary questions...\n")

    results = []
    for index, question in enumerate(tqdm(questions, desc="Evaluating documentary questions")):
        if index:
            time.sleep(INTER_QUESTION_DELAY_SECONDS)
        results.append(evaluate(question, ask_with_retry(question["question"], uid, password)))
    print_summary(results)
    write_reports(results)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    sys.exit(main())
