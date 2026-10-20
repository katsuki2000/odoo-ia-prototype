# Source extraction simplification

## Design before code — 20 October 2026

User asked to inspect and simplify code extraction. Continue on `feat/runtime-metadata-graph-poc`, starting from `1520e26988dcd77bad43c409ce899e5f69ac525b`. Read current runtime exporter, source search/adapters, runtime journal, rules and the principal context tail. Use the already-approved journal annex exception.

The runtime exporter currently unwraps every method, reads its source line bounds and hashes its file; the source search later reads/parses the same files again with Python AST. The reduced agent does not expose method-override analysis. Maintaining a second complete method inventory is unnecessary for this PoC.

Plan: let Odoo export the effective models/fields, composing modules and approved source file locations of loaded model classes only. Preserve ordered class source locations as file provenance, not as a claimed method override chain. Do not unwrap methods, read method bodies, hash source files or add Method nodes in this export path. Keep the existing bounded AST/XML source search as the single fragment extraction path, with its current source fingerprints, citation reader and scope controls. Teach the inventory adapter to consume the class-source locations while retaining compatibility with old graph paths and override sites. Correct the reader's outdated discovery-tool reference.

No new crawler, source index service, dependency, caching engine or LLM call. This intentionally does not solve discovery of arbitrary helper/XML files absent from the recorded source inventory. Installed modules are not equivalent to complete source coverage. Decorated/dynamic behavior must not be inferred from a declared method body. Legacy graph constructor/extractors remain untouched.

Validate that the export does not read method source or create Method nodes, that exported class locations feed the existing real AST/FTS search with correct model/module scope, that multiple class sites and legacy override sites still work, and that existing fingerprint/confinement tests pass. Record actual test counts and native environment limitations after execution. No changes to main, `.env`, Discuss, evaluation cases or deployment.

## Implemented and validated

The source-method extraction described in the earlier `runtime_metadata_graph_log.md` is superseded by this simplification. Its activation commands and environment settings are unchanged. Re-export the snapshot to obtain class-source locations without eager Method nodes; older snapshots remain readable but still contain the earlier eager method inventory until regenerated.

- Removed per-method unwrapping, source line extraction, source hashing, Method-node construction and HAS_METHOD edges from the opt-in exporter. It now uses Python introspection only to locate source files of installed composing classes, inside approved addon roots. Missing/out-of-root class locations are reported as unavailable source coverage. Runtime exporter length changed from 219 to 196 lines, with no new production module.
- Source locations retain their owning module on the Model node. `graph_source_inventory` combines these class sites with legacy file paths/override sites. The real AST parser and SQLite FTS5 then discover methods in those files at search time. Each distinct source file is parsed once per search, not permanently indexed or cached. Subsequent searches still rebuild the bounded in-memory index; no latency improvement was benchmarked.
- The runtime metadata inspector exposes class source file locations and no longer advertises eager method locations. Reading remains explicit through the existing fingerprint-checked cited reader. No fingerprint check or path/range/size protection was removed.
- A test exports the fixture model, passes its actual class source locations into the real AST/FTS search, checks the resulting method bounds/fingerprint and asserts one parse for the shared source file. Additional tests check exact model/module scope and compatibility with legacy override sites. The exporter test fails if method source extraction or source-file hashing is attempted.

Final isolated run: `python -m unittest discover -s tests -v`: 93 discovered, 91 passed, 2 skipped. Selected production/scripts/tests compilation passed. This is not the full repository suite. Skips remain the native NetworkX graph/model-fact smoke test and native LangGraph smoke test because those dependencies are unavailable in this sandbox. The real Odoo 17 export, normal-venv imports, frozen evaluation and end-to-end answer quality were not run.

Trade-offs: this mode no longer provides a method-level runtime override chain. An AST method is a declared source candidate, not proof of which decorated/dynamic implementation executes. The inventory still does not cover arbitrary helpers, XML files or external decorator implementations not referenced by recorded class source locations. An empty search is not proof of absence. Source access remains limited to approved PoC users and requires filesystem access to the configured roots. No all-instance, completeness or performance guarantee is claimed.

Changes are confined to the existing experimental branch, with design, production and tests/journal commits separated. No change to main, the parent branch, `.env`, `miro_ai_discuss`, dependencies, frozen cases or deployment.
