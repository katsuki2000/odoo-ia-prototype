"""
Retrieval Evaluation — recall@5 on benchmark questions.

Evaluates the hybrid search + re-ranking pipeline against the
benchmark question set from tests/benchmark_questions.json.

Computes:
- recall@5 for document questions
- recall@5 for code questions
- Overall recall@5
- Per-question detailed results

Outputs results to captures/retrieval_config.md
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from document_rag.vectorstore.chroma_manager import ChromaManager
from document_rag.vectorstore.search import BM25Index, retrieve

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
BENCHMARK_PATH = BASE_DIR / "tests" / "benchmark_questions.json"
OUTPUT_PATH = BASE_DIR / "captures" / "retrieval_config.md"


def load_benchmark() -> list[dict]:
    """Load benchmark questions."""
    if not BENCHMARK_PATH.exists():
        logger.error("Benchmark file not found: %s", BENCHMARK_PATH)
        return []

    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Handle both list format and dict with "questions" key
    if isinstance(data, dict):
        return data.get("questions", [])
    return data


def evaluate_recall(
    questions: list[dict],
    chroma_manager: ChromaManager,
    bm25_index: BM25Index,
    top_k: int = 5,
    use_reranker: bool = True,
) -> dict:
    """
    Evaluate recall@k on benchmark questions.

    For each question with expected source files, check if the expected
    source appears in the top-k retrieved results.

    Args:
        questions: List of benchmark question dicts
        chroma_manager: ChromaManager instance
        bm25_index: BM25Index instance
        top_k: Number of results to evaluate
        use_reranker: Whether to use cross-encoder

    Returns:
        Evaluation results dict
    """
    results_by_type = {"doc": [], "code": [], "erp": [], "edge": [], "other": []}
    detailed = []
    total_time = 0.0

    for i, q in enumerate(questions):
        question_text = q.get("question", q.get("q", ""))
        source_ref = q.get("source_reference", "")
        expected_sources = [source_ref.split(" — ")[0]] if source_ref else []
        q_type = q.get("type", q.get("category", "other"))
        expected_answer_contains = q.get("expected_answer_contains", [])

        if not question_text:
            continue

        # Skip ERP questions (they need ORM, not RAG)
        if q_type == "erp":
            continue

        # Retrieve
        start = time.time()
        try:
            retrieved = retrieve(
                query=question_text,
                top_k=top_k,
                chroma_manager=chroma_manager,
                bm25_index=bm25_index,
                use_reranker=use_reranker,
            )
        except Exception as e:
            logger.error("Retrieval failed for Q%d: %s", i + 1, e)
            retrieved = []
        elapsed = time.time() - start
        total_time += elapsed

        # Check recall: did any expected source appear in results?
        retrieved_sources = [
            r.get("metadata", {}).get("source", "") for r in retrieved
        ]
        retrieved_docs = [r.get("document", "") for r in retrieved]

        hit = False
        if expected_sources:
            for exp_src in expected_sources:
                # Partial match — expected source may be a substring
                for ret_src in retrieved_sources:
                    if exp_src in ret_src or ret_src in exp_src:
                        hit = True
                        break
                if hit:
                    break
        else:
            # No expected sources — check if any result is relevant
            # (contains keywords from the expected answer)
            if expected_answer_contains:
                for doc in retrieved_docs:
                    doc_lower = doc.lower()
                    matches = sum(1 for kw in expected_answer_contains if kw.lower() in doc_lower)
                    if matches >= min(2, len(expected_answer_contains)):
                        hit = True
                        break

        # Categorize
        if q_type in ["pdf", "wiki"]:
            category = "doc"
        else:
            category = q_type if q_type in results_by_type else "other"
        
        results_by_type[category].append(hit)

        detailed.append({
            "index": i + 1,
            "question": question_text[:80],
            "type": q_type,
            "hit": hit,
            "expected_sources": expected_sources,
            "retrieved_sources": retrieved_sources[:top_k],
            "time_ms": round(elapsed * 1000),
        })

        status = "✅" if hit else "❌"
        logger.info(
            "Q%d %s [%s] (%.0fms): %s",
            i + 1, status, q_type, elapsed * 1000, question_text[:60]
        )

    # Compute recall per type
    recall_by_type = {}
    for qtype, hits in results_by_type.items():
        if hits:
            recall_by_type[qtype] = sum(hits) / len(hits)

    # Overall recall (doc + code only, as per plan)
    doc_code_hits = results_by_type["doc"] + results_by_type["code"]
    overall_recall = sum(doc_code_hits) / len(doc_code_hits) if doc_code_hits else 0.0

    return {
        "overall_recall_at_k": overall_recall,
        "recall_by_type": recall_by_type,
        "top_k": top_k,
        "use_reranker": use_reranker,
        "total_questions": len(detailed),
        "total_time_ms": round(total_time * 1000),
        "avg_time_ms": round(total_time * 1000 / max(len(detailed), 1)),
        "detailed": detailed,
    }


def generate_report(results: dict, config: dict) -> str:
    """Generate Markdown report."""
    lines = [
        "# Retrieval Configuration & Evaluation — Step 3",
        "",
        "## Configuration",
        "",
        "| Parameter | Value |",
        "|-----------|-------|",
        f"| Vector search `top_k` | {config.get('vector_top_k', 12)} |",
        f"| BM25 search `top_k` | {config.get('bm25_top_k', 12)} |",
        f"| Vector weight | {config.get('vector_weight', 0.6)} |",
        f"| BM25 weight | {config.get('bm25_weight', 0.4)} |",
        f"| RRF constant `k` | {config.get('rrf_k', 60)} |",
        f"| Relevance threshold | {config.get('relevance_threshold', 0.3)} |",
        f"| Cross-encoder | `{config.get('cross_encoder', 'ms-marco-MiniLM-L-6-v2')}` |",
        f"| Final `top_k` | {results['top_k']} |",
        f"| Re-ranker enabled | {results['use_reranker']} |",
        "",
        "## Results",
        "",
        f"**Overall recall@{results['top_k']}**: {results['overall_recall_at_k']:.1%}",
        f"  (target: ≥ 80%)",
        "",
        "### Recall by Question Type",
        "",
        "| Type | Recall | Count |",
        "|------|--------|-------|",
    ]

    for qtype, recall in results["recall_by_type"].items():
        count = len([d for d in results["detailed"] if d["type"] == qtype])
        if count > 0:
            status = "✅" if recall >= 0.8 else "⚠️"
            lines.append(f"| {qtype} | {status} {recall:.1%} | {count} |")

    lines.extend([
        "",
        "### Latency",
        "",
        f"- **Total questions evaluated**: {results['total_questions']}",
        f"- **Total time**: {results['total_time_ms']}ms",
        f"- **Average per question**: {results['avg_time_ms']}ms",
        "",
        "### Detailed Results",
        "",
        "| # | Type | Hit | Time | Question |",
        "|---|------|-----|------|----------|",
    ])

    for d in results["detailed"]:
        status = "✅" if d["hit"] else "❌"
        lines.append(
            f"| {d['index']} | {d['type']} | {status} | {d['time_ms']}ms | {d['question']} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Collection Decision",
        "",
        "> Based on evaluation results. If text/code confusion is observed,",
        "> split into separate ChromaDB collections. Otherwise, keep one.",
        "",
    ])

    # Decision based on results
    doc_recall = results["recall_by_type"].get("doc", 0)
    code_recall = results["recall_by_type"].get("code", 0)

    if doc_recall >= 0.8 and code_recall >= 0.8:
        lines.append("**Decision**: ✅ Keep single collection — both doc and code recall are adequate.")
    elif abs(doc_recall - code_recall) > 0.3:
        lines.append(
            f"**Decision**: ⚠️ Consider splitting — doc recall ({doc_recall:.1%}) vs "
            f"code recall ({code_recall:.1%}) shows significant gap."
        )
    else:
        lines.append("**Decision**: Keep single collection for now, monitor after further data ingestion.")

    return "\n".join(lines)


def main():
    """Run the evaluation."""
    logger.info("Loading benchmark questions from %s", BENCHMARK_PATH)
    questions = load_benchmark()

    if not questions:
        logger.error("No benchmark questions found. Exiting.")
        sys.exit(1)

    logger.info("Loaded %d questions", len(questions))

    # Initialize retrieval components
    logger.info("Initializing ChromaManager (odoo_docs + odoo_code)...")
    chroma = [
        ChromaManager(collection_name="odoo_docs"),
        ChromaManager(collection_name="odoo_code"),
    ]

    logger.info("Building BM25 index...")
    bm25 = BM25Index()
    count = bm25.build_from_chroma(chroma)
    logger.info("BM25 index built with %d documents", count)

    if count == 0:
        logger.error(
            "ChromaDB is empty. Run ingestion first: python ingestion/ingest_all.py"
        )
        sys.exit(1)

    # Run evaluation
    config = {
        "vector_top_k": 12,
        "bm25_top_k": 12,
        "vector_weight": 0.6,
        "bm25_weight": 0.4,
        "rrf_k": 60,
        "relevance_threshold": 0.3,
        "cross_encoder": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    }

    use_reranker = "--reranker" in sys.argv or (os.getenv("USE_RERANKER", "false").lower() in ("true", "1", "yes") and "--no-reranker" not in sys.argv)
    logger.info(f"Running evaluation (reranker enabled: {use_reranker})...")
    results = evaluate_recall(
        questions, chroma, bm25,
        top_k=5,
        use_reranker=use_reranker,
    )

    # Generate and save report
    report = generate_report(results, config)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info("Report saved to %s", OUTPUT_PATH)
    logger.info("Overall recall@5: %.1f%%", results["overall_recall_at_k"] * 100)

    # Print summary
    print("\n" + "=" * 60)
    print(f"  recall@5 = {results['overall_recall_at_k']:.1%}")
    target_met = results["overall_recall_at_k"] >= 0.8
    print(f"  Target (≥ 80%): {'✅ MET' if target_met else '❌ NOT MET'}")
    print("=" * 60)

    return 0 if target_met else 1


if __name__ == "__main__":
    sys.exit(main())
