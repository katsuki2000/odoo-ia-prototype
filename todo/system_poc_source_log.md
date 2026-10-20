# System PoC: source-backed investigation

## Design before code — 20 October 2026

New branch `feat/system-poc-source-investigation`, based on the single-loop branch at `ef66eb55c3916e0afc96593ecbd927d45cfdb22d`. Scope follows `todo/architecture.md`: a limited Odoo 17 PoC, not universal coverage. This annex uses the previously approved journal exception; the principal context journal is preserved.

Deliver a missing concrete step: discover relevant installed source fragments without requiring successful model arbitration, then let the existing bounded source reader inspect them. Keep the one investigation loop and existing ORM tools. No second planner, service, new dependency, migration, or Discuss work.

Use Python AST and SQLite FTS5 (standard library) for bounded source discovery. Search only source paths evidenced by the active instance graph and confined to configured/graph addon roots. Python chunks follow actual AST definitions; XML chunks use real parser positions. Search returns candidate locations, not behavior evidence or raw source bodies. Existing source reader, tool guards and postprocessing remain authoritative for returned evidence.

For PoC scale, build a per-search in-memory index from bounded source files; no shared persistent index or cache invalidation subsystem. Include content fingerprints and explicit coverage/parse/read/budget gaps. Support model/module scoping without hardcoded module names. Large/unsupported/dynamic sources produce limitations, not confirmed absence. No code embeddings in this lot: reuse current semantic model discovery, add lexical source-body search first, and measure before expanding.

Test parsing/ranges, custom modules, model-independent search, source-root/symlink confinement, content changes and truncation. Retain the existing frozen cases and thresholds. Native LangGraph/Odoo/LLM evaluation remains separate from offline tests, with dependency failures reported honestly.

Non-goals: full registry synchronization redesign, complete Python execution/MRO simulation, universal source disclosure policy, per-company source ACL system, distributed indexes or production deployment. Sources must already be approved as inspectable by the deployment; root confinement alone is not user-level source authorization.

## Implemented

- `source_search.py`: standard-library AST/XML fragmentation and in-memory FTS5/BM25 ranking over symbol, model, module and source-body text. Only graph-referenced Python/XML files are read; addon directories are never crawled. Optional model/module scopes work without a mandatory resolver decision. Method override-site paths are included.
- `source_tools.py`: agent adapters for discovery and fingerprint-checked reading. Discovery returns locations, SHA-256 and coverage, not raw bodies. Returned candidates are trimmed to a bounded JSON payload. Reads delegate to the existing confined/cited source reader after range, root and content checks; a changed file is refused and must be searched again.
- `loop.py`: both tools registered in the existing single native investigation loop. Discovery consumes the shared budget but is excluded from behavior evidence. Fragment reading uses the existing `read_source_code` authorization-gate/evidence kind and observation cap. No additional planner or nested agent.
- Existing semantic model discovery, read-only ORM execution, identity context and final proof guards remain inherited from the parent branch. This lot does not redesign registry extraction or claim that parent integration is validated.

## PoC defaults and configuration

No additional Python package was installed or added. Python's SQLite build must support FTS5; this was checked locally.

Defaults: 200 indexed files, 1 MB per file, 8 MB aggregate file bytes, 4,000 indexed fragments, 200 lines per fragment. Search returns at most 20 candidates and reports partial coverage. Budgets are adjustable using `CI_SOURCE_SEARCH_MAX_FILES`, `CI_SOURCE_SEARCH_MAX_FILE_BYTES`, `CI_SOURCE_SEARCH_MAX_TOTAL_BYTES` and `CI_SOURCE_SEARCH_MAX_FRAGMENTS`; existing addon-root configuration is reused. No `.env` was read or modified.

The in-memory index is rebuilt per search, deliberately avoiding persistent infrastructure for this PoC. It sees current content of graph-referenced files, but cannot discover newly installed files missing from a stale graph. `complete_scan` describes the selected source inventory and budget only; it is NOT proof of complete Odoo behavior or an up-to-date registry. Class/function head truncation, parser errors, blocked paths and size/budget skips are explicit.

## Validation executed

- Real temporary files, Python AST, Expat XML and SQLite FTS5/BM25: custom source-body and XML-button retrieval, parser ranges/decorators, module/model scopes, no directory crawl, source-root and symlink confinement, freshness/fingerprints, malformed XML/Python, DTD refusal and bounded search.
- Reader boundary tests use a fixture for the existing reader/range validator; they verify delegation, stale/changed-content refusal and root/range rejection, not a new full integration test of that reader.
- Agent boundary tests execute extracted production functions with tool/gate fixtures. They check that discovery is not evidence, fragment reads retain the existing source gate/kind, and stale reads do not become evidence.
- Command in the isolated work directory: `python -m unittest discover -s tests -v`: 55 discovered, 54 passed, 1 skipped. This combines 35 new source tests with the inherited 20 single-loop tests. Compilation of the selected production/test files passed.
- The native LangGraph smoke test remains skipped: the parent's isolated dependency install failed with `No matching distribution found for langchain==1.3.12`. No native, full-suite, real Odoo/Kaggle, latency or answer-quality success is claimed.

## Small next validation on the actual instance

Use the normal project venv and unchanged provider configuration. Run `python -m unittest discover -s tests -p test_system_source_search.py -v` and `python -m unittest discover -s tests -p test_single_investigation_loop.py -v`. Then replay the unchanged frozen evaluation on the selected 3–5 installed modules, including at least one custom module.

Check an approval/blocking question, a UI procedure and an authorized count/aggregation. Inspect that the agent actually chooses discovery/read tools when needed, uses live ORM data under the requester, cites the read locations, and qualifies missing evidence. Repeat a source question after changing/rebuilding the relevant test module: changed fingerprints must not produce stale reads. Run the full suite before any merge.

## Remaining boundaries

Lexical source search does not guarantee French business paraphrase recall; the existing BGE model search still helps identify objects. No semantic source-body embeddings are added. This is not a Python execution simulator, effective-view merger or complete inheritance resolver. Search follows existing graph metadata, not a new live-registry synchronization service. File hashes reduce stale-location errors but do not make filesystem access atomic under a hostile concurrent writer. The existing source-disclosure policy must be approved for PoC users; root confinement alone does not establish per-user permission to all source metadata.

`main`, `integration/fusion-15oct`, the parent branch, provider settings, `.env`, `miro_ai_discuss` and frozen benchmark cases/thresholds are not modified by this lot. No PR, merge or deployment.
