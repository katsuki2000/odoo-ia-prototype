# Runtime metadata graph PoC

## Design before code — 20 October 2026

Branch `feat/runtime-metadata-graph-poc`, from `feat/system-poc-source-investigation` at `48774c2a4b9ebfa58abf97d0e792f8da48472a27`. User approved a simpler graph-generation route for the limited PoC. This annex uses the previously approved journal exception.

Add an explicit Odoo-shell export of selected installed modules and their effective model/field metadata, relevant interface/security records and source method locations. Convert those facts to the current graph node conventions without parsing every addon or guessing workflows. Keep the existing source-investigation tools and legacy constructor. No Discuss changes and no migration of FastAPI.

Runtime-snapshot loading is opt-in, with a configured snapshot path and expected instance key. An invalid/mismatched snapshot fails instead of silently rebuilding a different graph. Missing source files/metadata and unsupported analysis capabilities must remain explicit. Building/updating the snapshot is an operator command, not part of each question. Technical metadata export never substitutes for requester-authorized live ORM reads.

Reuse NetworkX and standard Python introspection/XML/JSON where needed. Retain existing extractors for the legacy path. No new dependency, graph database, background synchronization or dynamic Python execution analysis. Scope must be supplied explicitly, not inferred from a hardcoded module list. Preserve citations and addon-root confinement; snapshot/source metadata is for approved PoC users.

Validate snapshot conversion, scoping, identity and schema checks, provenance and absence of speculative workflow edges offline. Actual Odoo 17 export and agent/evaluation replay require the user's environment and remain a distinct validation gate.

## Implemented

- `runtime_export.py` reads the initialized Odoo registry and whitelisted technical tables, with an explicit installed-module scope. Effective fields come from the actual model classes. Source method sites and order come from Python introspection over the loaded MRO, not inferred dependency order. No method is executed to determine behavior.
- The export includes selected model relations, module dependencies, relevant ACL/rule metadata, group relationships, window actions, direct menus, and declared view/button information. XML-IDs identify technical records; missing XML-IDs/sources and invalid views are coverage gaps. Related models outside scope are not synthesized into complete models. UI declarations are not claimed to be effective requester-visible views. Parent-menu ancestry and full implied-group closure in the bounded model fact response are not complete.
- `scripts/export_runtime_graph.py` runs inside a dedicated superuser Odoo shell, reads metadata only, writes a private atomic JSON snapshot and rolls the transaction back. It loads the exporter file with the standard library, avoiding a dependency on backend packages in the Odoo venv. No HTTP endpoint or new addon is installed.
- The public graph loader uses the snapshot only when explicitly configured. It validates schema, configured instance key, scope, node/edge integrity and fingerprints. There is no silent fallback to the old constructor on an invalid opted-in snapshot. Direct legacy-loader imports remain legacy; the system agent uses the public entry point.
- Runtime mode exposes unified search, source reading, live read-only ORM, a bounded dated model-metadata inspector, and only a small explicit subset of compatible legacy CI tools. Workflow, access-verdict and other analyses that assume the richer graph are not exposed in this mode. The old constructor/path is preserved for comparison and compatibility.
- Source/identity/proof protections remain inherited. An exported ACL or rule is not itself proof that an approval operation will succeed. Metadata observations use runtime-snapshot provenance, distinct from live ERP rows.

## Activation on the actual Odoo host

These commands are examples with placeholders, not commands executed here. Use the Odoo venv for export and the backend venv for the API. Start from the backend repository root so the exporter source file is available.

```bash
export CI_RUNTIME_GRAPH_MODULES='module_a,module_b,module_c'
export CI_RUNTIME_GRAPH_INSTANCE='your-instance-key'
export CI_RUNTIME_GRAPH_PATH="$PWD/var/runtime-graph.json"

# Replace the executable, configuration and database with the actual deployment values.
odoo shell -c "$ODOO_CONF_PATH" -d "$ODOO_DB" --no-http < scripts/export_runtime_graph.py
```

Supply real installed module names, including the custom module under evaluation. The script requires an explicitly privileged shell environment; it does not call sudo to elevate a requester. Defaults: 200 effective models and 20,000 rows per technical query. Adjust only if needed using `CI_RUNTIME_GRAPH_MAX_MODELS` and `CI_RUNTIME_GRAPH_MAX_ROWS`; exceeding a bound refuses the export rather than silently trimming it.

Review the snapshot's module scope, database, date, roots and coverage gaps before enabling it. Expose this metadata only to approved PoC users. Set the same `CI_RUNTIME_GRAPH_PATH` and `CI_RUNTIME_GRAPH_INSTANCE` in the backend process environment and restart it. No `.env` was read or modified by this work. Unset `CI_RUNTIME_GRAPH_PATH` to return to the legacy constructor. Re-run the export after installing/updating modules or modifying relevant technical configuration. `force_rebuild` does not regenerate an opted-in runtime snapshot.

The instance key is an operator-configured identity check, not automatic authentication against the live database. Correct backend/database configuration remains the operator's responsibility. Snapshot source paths must resolve inside approved addon roots on the backend host; no automatic cross-host path rewriting is implemented. The snapshot records the export language; per-question translation regeneration is not implemented. The loader reads the explicit snapshot on demand without a new persistent cache/synchronization service.

## Validation actually executed

Offline tests use a small explicit Odoo metadata/registry fixture, real Python class introspection and XML parsing, JSON schema/identity/integrity checks, and the extracted public loader wrapper. They do not execute real Odoo ORM domains or prove compatibility of every technical field on Odoo 17. The first wrapper test failed due to its missing fixture package context; that fixture was corrected and the suite rerun.

Final isolated worktree run: `python -m unittest discover -s tests -v`: 90 discovered, 88 passed, 2 skipped. This is 21 runtime-graph tests plus the 69 inherited selected tests, not the full repository suite. Compilation of selected production/scripts/tests passed.

Skipped: real NetworkX conversion/model-fact smoke test and native LangGraph smoke test. Installing the already-pinned NetworkX version failed with `No matching distribution found for networkx==3.6.1` (index returned no versions). No project dependency pin was changed and no new dependency was added. No live Odoo shell export, full API import, full suite, frozen evaluation or Kaggle/LLM answer-quality run was possible here. Native graph/model-fact behavior and the end-to-end agent path remain to validate.

## Next PoC check

Run the export on the selected installed modules, validate it in the normal backend venv, then replay the unchanged small evaluation bank: one custom approval/blocking question, one interface procedure and one requester-authorized aggregation. Confirm that unavailable graph analyses cannot be selected, coverage limitations remain visible and actual code/data—not inferred graph absence—support the answer. Compare against the legacy path before deleting any legacy constructor code.

No changes to `main`, integration/parent branches, `.env`, `miro_ai_discuss`, provider configuration or frozen cases/thresholds. No PR, merge or deployment. Status: experimental opt-in PoC implementation, not a validated replacement for the existing graph constructor.
