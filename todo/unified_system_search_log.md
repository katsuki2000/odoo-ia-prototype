# One system search entry point

## Design before code — 20 October 2026

User approval: simplify model/code discovery if it remains simple and useful. Work stays on `feat/system-poc-source-investigation`, starting at `3bf42d14f6b1932b67f8628a45e1d0098f831e22`. This annex uses the previously approved journal exception.

Expose one discovery tool to the system agent, reusing the existing instance-object and source-fragment search functions internally. Query and optional exact model scope are shared. Return typed mixed candidates with preserved provenance, source coverage and backend failure status. Keep each backend's order and alternate results; do not compare BM25 and vector scores or introduce a new scoring engine. Source reading remains a separate verification step.

Remove the two previous discovery tools from the active tool list and prompts, not their compatibility implementations. Treat the unified result as discovery only under the same execution/output budgets. Bound the combined response and report result clipping. Add no package, service, index or extra LLM call.

This reduces the search choices exposed to the LLM and can avoid a separate model-search/code-search decision. It does not prove better retrieval, lower wall time or better answers: both existing backends still do work, and native/Odoo/Kaggle validation remains necessary. Do not expand this small change into an indexing redesign.

## Implementation and validation

- Added `search_system` in the existing source-tool adapter, reusing `find_instance_candidates` and `search_source_fragments`. It alternates typed object/source candidates without comparing incompatible scores. Optional exact model scope applies to both searches. The old source-only module filter remains on the compatibility implementation, not on the unified entry point.
- The system agent registers the unified search and fragment reader, not the two old general discovery tools. Prompts and discovery budgets refer to the unified tool. Existing technical-identifier analysis tools remain available.
- Source fingerprints, line bounds, source coverage and semantic-backend status are preserved. One backend failure does not hide the other's candidates. Responses are valid JSON bounded to 5,500 characters and the requested combined candidate count; clipping is explicit. Search output is still excluded from behavior evidence.
- Added 14 offline tests of the actual extracted unified function, with backend fixtures, plus one of those tests using the real AST/SQLite source backend on a temporary custom file. Updated the existing non-frozen source-agent tests for the new entry point; no benchmark cases or thresholds changed.
- Actual isolated-worktree result: 69 tests discovered, 68 passed, 1 skipped; compileall passed. These include inherited single-loop/source tests and the new unified tests, not the full repository suite.
- Native LangGraph smoke test remains skipped because the required dependencies are unavailable in this sandbox. No live Odoo/Kaggle, full-suite, retrieval-quality or wall-time improvement is claimed. Both backends still run sequentially inside the one discovery call; the change simplifies tool choice, not backend computation.

No `.env`, provider configuration, package requirement, Discuss addon, main/integration branch, merge or deployment changes. Continue with the unchanged small PoC evaluation protocol documented in `todo/system_poc_source_log.md`.
