# One system search entry point

## Design before code — 20 October 2026

User approval: simplify model/code discovery if it remains simple and useful. Work stays on `feat/system-poc-source-investigation`, starting at `3bf42d14f6b1932b67f8628a45e1d0098f831e22`. This annex uses the previously approved journal exception.

Expose one discovery tool to the system agent, reusing the existing instance-object and source-fragment search functions internally. Query and optional exact model scope are shared. Return typed mixed candidates with preserved provenance, source coverage and backend failure status. Keep each backend's order and alternate results; do not compare BM25 and vector scores or introduce a new scoring engine. Source reading remains a separate verification step.

Remove the two previous discovery tools from the active tool list and prompts, not their compatibility implementations. Treat the unified result as discovery only under the same execution/output budgets. Bound the combined response and report result clipping. Add no package, service, index or extra LLM call.

This reduces the search choices exposed to the LLM and can avoid a separate model-search/code-search decision. It does not prove better retrieval, lower wall time or better answers: both existing backends still do work, and native/Odoo/Kaggle validation remains necessary. Do not expand this small change into an indexing redesign.
