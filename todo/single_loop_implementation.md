# Single investigation loop — implementation journal

Branch: `refactor/single-investigation-loop`, based on `integration/fusion-15oct` at `228f3b9d2d7066504f0c9fdf03099bef3159c1e9`.
Design recorded before code in `todo/single_loop_architecture.md`. This annex uses the previously approved journal exception; the large principal journal is preserved.

## Implemented

- Explicit documentation/system selections route without model resolution, intent calls or capability planning. With no source selection, the existing classifier is reduced to a documentation/system decision.
- All system route variants enter one agent. Documentation retrieval/generation, verification and output nodes remain in place.
- The active agent uses the existing LangGraph prebuilt ReAct implementation. The capability planner/predispatch and separate manual ORM loop are no longer invoked by this path. Historical modules are retained for compatibility, not deleted indiscriminately.
- One guarded execution boundary wraps CI tools, instance discovery and all seven existing read-only ORM tools. Original tool schemas and the ERP runtime authorization remain authoritative. Failed/refused calls are not promoted into usable observations. Attempt budgets, canonical-argument deduplication, group overrides, authorization gating, observation caps and tracing remain centralized.
- Instance discovery reuses RapidFuzz, graph labels/technical names and the configured semantic model retriever. It returns candidates, not proofs; those results are excluded from the evidence observations. It searches metadata, not source bodies. There is no new semantic source-body index and no new retrieval framework.
- Graph, LLM and question references use ContextVars, reset in a context manager. Introspection reads the request-local graph through its accessor. Guarded native tools explicitly enter that context and serialize operations on the per-request dispatch state.
- Unknown requester groups remain `None`, distinct from known-empty groups. Incomplete hypothetical persona groups are not silently accepted. Personas do not authorize live ORM calls.
- Existing source-root confinement and final business/citation guards remain. ERP source references are corrected after the retained postprocessor. The former automatic confidence of 1.0 for any observation is replaced by a conservative placeholder (0.5 with observations, otherwise 0); it is not calibrated confidence.
- FastAPI, JWT, provider configuration, `.env`, `miro_ai_discuss`, benchmark cases and thresholds are not modified. No merge, deployment or PR.

## Validation actually executed in this sandbox

Command: `.venv/bin/python -m unittest discover -s tests -p test_single_investigation_loop.py -v`.
Initial result: 20 tests discovered, 19 passed, 1 skipped. Includes extracted production execution-boundary functions, explicit-source routing, concurrent/nested ContextVars and structural route assertions. Dependencies at the boundaries are fixtures, not real Odoo/LLM tools.
Compilation: `.venv/bin/python -m compileall -q code_intelligence core tests` passed.

The native smoke test is present but skipped because LangGraph/LangChain are unavailable. Installation of the project-pinned dependencies in an isolated venv failed with `No matching distribution found for langchain==1.3.12` (index returned no versions). Project dependency pins are not changed to fit this sandbox. No claim of native integration or full-suite success is made.

The existing non-frozen capability test is adapted only for the extracted executor's added globals and the superseded active-runner assertion; all legacy plan tests are retained. Its baseline was verified against the current remote blob before adapting it. The legacy suite has not been run here against the complete integration source tree.

## Required before merging

1. Install the repository requirements in the normal project venv and run the native smoke test and full suite. Confirm dynamic-model support in the pinned `langgraph-prebuilt` and tool-message/schema behavior.
2. Replay the unchanged evaluation bank against the configured Kaggle LLM/BGE and the actual Odoo instance; measure quality, tool choices, latency, tool budgets, source coverage and persona comparisons. No performance or accuracy improvement is claimed yet.
3. Validate mixed CI/ORM answers, evidence dossiers across native worker contexts, refusal/truncation handling and the retained postprocessor's code-oriented evidence-sufficiency/footer behavior. ERP source kind is adapted, but that legacy postprocessor is not fully redesigned.
4. Audit retained legacy imports/tests before deleting old orchestration modules. `graph_compat` still exposes historical functions and keyword names; they are not part of active routing.
5. Request-local CI context does not fix the historical global metadata group cache or every inner composite-tool LLM call. Those remain separate limitations. No full multi-instance portability guarantee.

Status: experimental implementation on a separate branch; not production-ready and not a validated replacement for the integration branch.
