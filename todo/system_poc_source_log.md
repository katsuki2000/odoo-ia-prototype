# System PoC: source-backed investigation

## Design before code — 20 October 2026

New branch `feat/system-poc-source-investigation`, based on the single-loop branch at `ef66eb55c3916e0afc96593ecbd927d45cfdb22d`. Scope follows `todo/architecture.md`: a limited Odoo 17 PoC, not universal coverage. This annex uses the previously approved journal exception; the principal context journal is preserved.

Deliver a missing concrete step: discover relevant installed source fragments without requiring successful model arbitration, then let the existing bounded source reader inspect them. Keep the one investigation loop and existing ORM tools. No second planner, service, new dependency, migration, or Discuss work.

Use Python AST and SQLite FTS5 (standard library) for bounded source discovery. Search only source paths evidenced by the active instance graph and confined to configured/graph addon roots. Python chunks follow actual AST definitions; XML chunks use real parser positions. Search returns candidate locations, not behavior evidence or raw source bodies. Existing source reader, tool guards and postprocessing remain authoritative for returned evidence.

For PoC scale, build a per-search in-memory index from bounded source files; no shared persistent index or cache invalidation subsystem. Include content fingerprints and explicit coverage/parse/read/budget gaps. Support model/module scoping without hardcoded module names. Large/unsupported/dynamic sources produce limitations, not confirmed absence. No code embeddings in this lot: reuse current semantic model discovery, add lexical source-body search first, and measure before expanding.

Test parsing/ranges, custom modules, model-independent search, source-root/symlink confinement, content changes and truncation. Retain the existing frozen cases and thresholds. Native LangGraph/Odoo/LLM evaluation remains separate from offline tests, with dependency failures reported honestly.

Non-goals: full registry synchronization redesign, complete Python execution/MRO simulation, universal source disclosure policy, per-company source ACL system, distributed indexes or production deployment. Sources must already be approved as inspectable by the deployment; root confinement alone is not user-level source authorization.
