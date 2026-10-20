# Source extraction simplification

## Design before code — 20 October 2026

User asked to inspect and simplify code extraction. Continue on `feat/runtime-metadata-graph-poc`, starting from `1520e26988dcd77bad43c409ce899e5f69ac525b`. Read current runtime exporter, source search/adapters, runtime journal, rules and the principal context tail. Use the already-approved journal annex exception.

The runtime exporter currently unwraps every method, reads its source line bounds and hashes its file; the source search later reads/parses the same files again with Python AST. The reduced agent does not expose method-override analysis. Maintaining a second complete method inventory is unnecessary for this PoC.

Plan: let Odoo export the effective models/fields, composing modules and approved source file locations of loaded model classes only. Preserve ordered class source locations as file provenance, not as a claimed method override chain. Do not unwrap methods, read method bodies, hash source files or add Method nodes in this export path. Keep the existing bounded AST/XML source search as the single fragment extraction path, with its current source fingerprints, citation reader and scope controls. Teach the inventory adapter to consume the class-source locations while retaining compatibility with old graph paths and override sites. Correct the reader's outdated discovery-tool reference.

No new crawler, source index service, dependency, caching engine or LLM call. This intentionally does not solve discovery of arbitrary helper/XML files absent from the recorded source inventory. Installed modules are not equivalent to complete source coverage. Decorated/dynamic behavior must not be inferred from a declared method body. Legacy graph constructor/extractors remain untouched.

Validate that the export does not read method source or create Method nodes, that exported class locations feed the existing real AST/FTS search with correct model/module scope, that multiple class sites and legacy override sites still work, and that existing fingerprint/confinement tests pass. Record actual test counts and native environment limitations after execution. No changes to main, `.env`, Discuss, evaluation cases or deployment.
