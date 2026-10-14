# Indexed model resolution

Date: 2026-10-14
Branch: `fix/ci-api-errors`
Base: `09dd0bb9cd1cd620dd24c1e26ef36b1a48fec530`

Mandate: proceed even when earlier local work is not published; treat the repository as the source of truth. Main and the user's local worktrees are not modified. Rules and the principal journal tail were reviewed. This annex follows the already authorized temporary journal exception; `todo/contexte.txt` remains unchanged and must later receive these entries.

## Commit 1: deterministic corpus index

Commit: `5abd8156b4106321a5456ad3d178987530ad5ded`.

Files: `code_intelligence/model_references.py`, `tests/test_ci_model_references.py`, this annex.

Added a standard-library index of technical names and Odoo-generated `model_` XML-ID suffixes. It uses the forward dot-to-underscore formula and retains every candidate when suffixes collide. Lookup accepts exactly one indexed target; it does not invert underscores to dots or accept unknown technical names. Duplicate declarations of the same name are not collisions. Module-qualified generated suffixes are supported; this is static corpus matching, not a runtime `ir.model.data` namespace/alias verification.

Executed: 11 dependency-free unit tests passed; Python compilation passed. No dependency installed. This foundational commit does not yet change graph construction; wiring is a separate commit.

Kaggle: fetching the supplied notebook URL from this environment returned unavailable content (404). This does not establish that the user's running inference service is down. No notebook execution, private credential retrieval, inference request, or model change was performed.

## Commit 2: registry, graph, query lookup, and schema

Files: `graph/nodes.py`, `graph/symbols.py`, `graph/version.py`, `agent/tool_helpers.py` under `code_intelligence/`, `tests/test_ci_model_graph_refs.py`, this annex.

- The symbol registry caches the shared model index and refreshes it if the key set changes, including same-size replacement. Checking the key set is linear in the number of models; the index is not rebuilt/sorted for unchanged keys.
- Rules, ACLs, server actions, automations, and menu model targets use actual indexed names. Unresolved/ambiguous references do not create inferred model target edges; original references, module, and file are recorded without duplicate model diagnostics.
- Server actions and automations store `target_model`. Query-time action lookup uses that resolved attribute or a typed `TARGETS_MODEL` edge, not a reverse underscore heuristic or an unrelated edge.
- Symbol pass 2 uses the same resolution/diagnostics. Unresolved categorization is shared in nodes and re-exported by symbols; stale file-header/history commentary was removed and public graph exports consolidated. Other workflow, merge, rename, source-tracing, and global-state algorithms are not redesigned by this lot.
- Graph schema 10 -> 11 so old cached graphs are not considered equivalent by schema-aware loaders. The current cache-validation test imports the constant rather than hardcoding 10. Graph reconstruction and service reload must still be performed on the deployment host.

Validation: 11 resolver tests passed natively using the standard library. The 11 graph/query tests also passed with sandbox-only dependency adapters for unavailable NetworkX, extractor annotation imports, ontology/workflow imports, and unrelated resolver utilities. The production node and query-helper implementations were executed, but this is isolated unit-fixture validation, not native NetworkX, parser, full-module integration, or Odoo validation. The published graph tests use the project's native dependencies; the sandbox adapter runner is not published. All prepared Python files compiled. No package installed. The full repository suite and graph rebuild were not executed.

Remaining: the unused legacy utility `utils.resolve_model_xmlref` and its old tests still exist; removing/migrating that public API is a separate cleanup. Translation attachment currently retains its existing correct but repeated graph-scan resolver; sharing the new index there remains a separate optimization. Runtime XML-ID aliases/namespaces, unresolved inheritance/fields, global request state, confidence, and live inference validation are not solved by this lot. No change to main or miro_ai_discuss.
