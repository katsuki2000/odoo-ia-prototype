# Evidence-first cleanup — delivered batch, 21 October 2026

Design before code: `todo/evidence_first_cleanup_log.md`, committed at `70e6fd12ee82e61027e330f0c2818adb50d1d52e`. Branch: `refactor/evidence-first-cleanup`, base `integration/final-merge` at `21be3f259314a5cd089e603ee439609be5ab31a1`. This is the already-authorized annex for the 1 MB central journal. No central history was truncated. Read its tail through section 1500; no outcome of the external 98-question benchmark is assumed.

## Changes actually delivered

- `code_intelligence/agent/instance_search.py`: deterministic semantic/lexical rank round-robin and deduplication before the existing unified object/source facade limit. No comparison of cosine and fuzzy scores; accent normalization, score threshold and bounded candidates retained. With a very small final limit or oversized candidates, not every channel can be guaranteed a slot. No claimed quality/speed gain without measurement.
- `config/settings.py`: operator policy `SENSITIVE_EVIDENCE_GROUP_XMLIDS` (comma-separated exact XML-IDs, empty denies marked sensitive evidence), plus `SOURCE_SELECTION_MIN_CONFIDENCE` (default 0.75, range checked). Existing connection/model/path/ORM defaults retained. No `.env` was opened, changed or printed.
- `code_intelligence/rules/security_locks.py`: disclosure is no longer inferred from arbitrary source `has_group` calls, write ACLs or unlink ACLs. Explicit configured membership, including implied groups, controls marked evidence. The legacy helper names remain but do not grant business rights. Omission labels no longer derive from the withheld secret. Added filtering for evidence explicitly tagged `scope.sensitive`.
- `code_intelligence/rules/security_evidence.py`: group checks are located observations, not unconditional group requirements or approval verdicts. Exact exception conditions, methods, lines and OR alternatives remain available; no OR alternative is presented as sufficient for the whole action. Hardcoded-login evidence is tagged sensitive so the structured dossier cannot evade text redaction. Existing bounded block allocation and exception reservation retained. New scope keys are `sensitive` (disclosure classification) and `authorization_verdict: not_evaluated` (a group-call observation is not an effective-rights result).
- `code_intelligence/agent/postprocess.py`: retired seven stages from active execution: required-group backfill, core-only group stripping, group-escalation blanket verdict, security-lock currency/amount backfill, approval-specific reconstruction, fiscal-lock canned verdict, and threshold permission correction. The seventh extends the original bounded plan because an unrestricted group rule does not cancel global record rules. Kept 25 unreviewed legacy stages for a measured follow-up; did not blindly remove all 32. Citation, code-block grounding, source ranges, conflict detection, evidence sufficiency, authorization omissions and truncation provenance remain. Response state carries the actual `ctx.G` and its disclosure decision.
- `core/state.py`, `core/graph/verify_node.py`: verifier reuses the request graph by identity; standalone fallback uses the snapshot-aware public selector, not the legacy loader. Documentation does not load a code graph. User question text is no longer included as factual verification evidence. Sensitive structured evidence is filtered before verification.
- `core/graph/graph.py`: terminal clarification edge and structured-dossier disclosure filtering. Requester API key/UID/company ContextVars and finally cleanup retained. No migration of business ORM to administrative execution.
- `core/routing/source_selection.py`, `core/routing/routing.py`: source selection has documentation/system/uncertain with validated confidence. Explicit UI selection bypasses classification. Invalid UI input, low confidence, malformed output or provider failure asks for source clarification; no automatic keyword choice of another corpus. Model confidence is not calibrated factual certainty. The old nine-intent classifier is no longer on this routing path.
- `core/graph/graph_nodes.py`: retrieval calls its own dependencies, not monkey-patches discovered through `sys.modules`.
- `code_intelligence/agent/context.py`: sole live owner of metadata RPC client/cache, protected by a reentrant lock; removed synchronization with copied globals in `core.graph.graph`. This remains a single configured-instance process cache, not a validated multi-tenant cache. Hypothetical security principals remain separate from requester groups.
- `tests/test_evidence_first_cleanup.py`: 37 new isolated regressions executing production function bodies with explicit substitutes for unavailable dependencies.

## Validation actually executed

In an isolated partial workspace, using the existing test virtual environment:

```sh
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q core code_intelligence config tests
```

Final selected run: **145 tests run, 143 passed, 2 skipped**, 0.397 seconds. The 108 pre-existing selected tests cover source search, unified search, single-loop boundaries, runtime metadata and source coverage using the local partial feature fixtures; only `source_tools.py`, graph/routing and loop base hashes were checked against final-merge during preparation. Do not present that as a full checkout or complete final-merge suite. The new 37 tests specifically cover this delivered batch. Compilation succeeded. The sandbox test venv has Pydantic 2.13.5, not an assertion that every pinned project dependency is installed. No new package installed or requirement changed.

Intermediate failures were test-fixture issues: AST extraction retained a tool decorator; removed decorators in the loader. The old explicit-source routing fixture lacked new globals; production explicit mode was kept independent of automatic confidence/clarification globals, restoring the unchanged original test. Final run is green. SQLite connection ResourceWarnings in existing isolated fixtures remain; not claimed fixed.

## Limits and work not claimed complete

NetworkX, native LangGraph and RapidFuzz are absent from this test venv. Two existing native smoke tests were skipped; lexical scoring/semantic provider/graph in new boundary tests use explicit substitutes. No native Odoo, real BGE/LLM, live ORM, full project suite, CI result, deployment or frozen benchmark validation is claimed. Git transport failed DNS; publication used the existing GitHub connection.

This is a bounded cleanup, not complete elimination of the audit debt. The 25 retained postprocessors, unused legacy correction APIs, compatibility re-exports and the old classifier's compatibility hooks still exist. Legacy tests patching `core.graph.graph` or `investigation_planner` instead of the owning modules must be migrated before full compatibility removal. Existing tests expecting unconditional 'required group' assertions must be reviewed against the corrected observation contract; the full native suite was not run and must not be represented as green. No proof of complete call-graph coverage, per-request source ACL enforcement, or sensitivity classification of every possible source fragment is provided by this batch.

No changes to source/MRO/helper/XML inventory, frozen cases, frozen thresholds, Discuss, main, integration, merges, PRs or deployment. The branch is for review and native validation before integration.
