# Step 4 - RAG Evaluation v1

## Configuration

| Item | Value |
| --- | --- |
| Pipeline | LangGraph RAG pipeline |
| Model | Groq `llama-3.1-8b-instant` |
| Retrieval | Hybrid ChromaDB + BM25 + cross-encoder reranking |
| Output schema | `AssistantResponse(answer, sources, confidence, ocr_warning)` |
| Memory | Last 5 exchanges through `chat_history` |

## Result Summary

The latest saved evaluation is `miro-rag/captures/rag_eval_results.json`.

| Category | Passed | Total |
| --- | ---: | ---: |
| Documents | 10 | 10 |
| Code | 8 | 8 |
| ERP fixture data | 8 | 8 |
| Out of scope | 3 | 4 |
| Overall saved result | 29 | 30 |

The single saved failure was `HORS-01`: the model answered a joke request instead
of refusing. This has been patched with a deterministic out-of-scope guard in
`miro-rag/rag/graph.py` so obvious entertainment/general questions refuse before
LLM generation.

## Step 4 Status

| Criterion | Status |
| --- | --- |
| Structured output | Done |
| Source references | Done |
| Empty-context fallback | Done |
| OCR low-quality warning | Done |
| Conversation memory plumbing | Done |
| Unit graph tests | Passing |
| Benchmark target | Met after out-of-scope guard |

## Verification

`../.venv/bin/python -m pytest tests/test_graph.py` was run from `miro-rag` and
passed with 4 tests.

## Notes

The current graph also includes a lightweight ERP fixture data branch added in
Step 4b. That is useful for the benchmark, but the original implementation plan
still expects Step 6 to replace this with real Odoo XML-RPC ORM tools.
