# Source coverage correction

## Design before code — 20 October 2026

User requested correction after identifying that the preceding simplification removed useful method-override information and left helper/XML coverage too narrow. Continue on `feat/runtime-metadata-graph-poc` from `5e0273f53ccccb68cf5ef8594357bd1ec7a0844d`. Read current rules, context tail, export/search/reader contracts. The already-approved journal annex exception applies. This journal supersedes the source coverage trade-off accepted in `source_extraction_simplification_log.md`.

Retain the simpler separation, not the loss of evidence: export ordered method-definition provenance from actual loaded class MRO using function code locations, without reading method bodies or determining their end lines. Cache location lookup within the export. Preserve missing locations explicitly. Expose a requested method's ordered definitions through the existing runtime metadata inspector; do not restore legacy tools that infer full execution chains or approval verdicts from an incomplete graph.

Inventory Python/XML file paths throughout the explicitly selected installed modules and installed modules contributing classes to those effective models. This is a bounded operator-time directory inventory, not a per-question whole-filesystem crawler. Do not traverse directory symlinks or paths outside resolved module roots. Count missing paths/symlinks; refuse oversized inventories. Do not open arbitrary source files during export. No invented association between a helper and a particular model: module context permits discovery but is not proof of ownership or execution.

At query time retain the existing bounded AST/XML extraction, fingerprints and cited reader. Include module-context files under model-scoped search, prioritize direct model files then selected-module files before inherited-module context, and report budgets/gaps rather than claim absence or complete instance coverage. Preserve compatibility with older snapshots and legacy graph metadata. No new package or source indexing service.

Test actual multi-class MRO order, helper/XML discovery through an exported inventory, scope exclusion, symlink confinement, inventory bounds, no source-body read in export, inspector visibility and existing citation/fingerprint regressions. Real Odoo 17/native graph/agent/full frozen evaluation still require the normal deployment environment. No main, parent-branch, `.env`, Discuss or frozen-case edits; no merge/deploy.
