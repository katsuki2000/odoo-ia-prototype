# Runtime metadata graph PoC

## Design before code — 20 October 2026

Branch `feat/runtime-metadata-graph-poc`, from `feat/system-poc-source-investigation` at `48774c2a4b9ebfa58abf97d0e792f8da48472a27`. User approved a simpler graph-generation route for the limited PoC. This annex uses the previously approved journal exception.

Add an explicit Odoo-shell export of selected installed modules and their effective model/field metadata, relevant interface/security records and source method locations. Convert those facts to the current graph node conventions without parsing every addon or guessing workflows. Keep the existing source-investigation tools and legacy constructor. No Discuss changes and no migration of FastAPI.

Runtime-snapshot loading is opt-in, with a configured snapshot path and expected instance key. An invalid/mismatched snapshot fails instead of silently rebuilding a different graph. Missing source files/metadata and unsupported analysis capabilities must remain explicit. Building/updating the snapshot is an operator command, not part of each question. Technical metadata export never substitutes for requester-authorized live ORM reads.

Reuse NetworkX and standard Python introspection/XML/JSON where needed. Retain existing extractors for the legacy path. No new dependency, graph database, background synchronization or dynamic Python execution analysis. Scope must be supplied explicitly, not inferred from a hardcoded module list. Preserve citations and addon-root confinement; snapshot/source metadata is for approved PoC users.

Validate snapshot conversion, scoping, identity and schema checks, provenance and absence of speculative workflow edges offline. Actual Odoo 17 export and agent/evaluation replay require the user's environment and remain a distinct validation gate.
