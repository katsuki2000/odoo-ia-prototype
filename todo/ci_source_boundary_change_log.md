# Source-evidence boundary — publication record

Date: 2026-10-14. Branch: `fix/ci-source-evidence-boundary`.

Read `todo/rules.md`, architecture and journal through section 1331. User authorized branch edits, never direct edits to `main`.

Published commits:
- `76ff66dcc6b3ba05abc0f9e19072ce925d87d971`: evidence-only rendering helper, 19 offline regressions and section870 test migration.
- `fe87cb6b17b7265ae8f7a8668cc45993495601bc`: postprocess passes gated observations; generated code is never reconstructed from disk; invalid source bounds are rejected before filesystem resolution; section917 expectations/documentation updated.

The renderer preserves only exact contiguous numbered source from authorized observations backed by a matching scoped citation. Masked gaps and separate observations are not joined. Without observations, code is omitted. All fenced blocks use the stricter contract. The source reader rejects non-integer, non-positive, reversed and oversized ranges. Existing path allowlist, dependencies, permission policy, plan, rules and `miro_ai_discuss` are unchanged.

Validation: 19 dependency-free unit tests passed in preparation; bundle syntax checks passed; integration commit diff was retrieved and reviewed. `main` was checked after publication and remained at `491afe2c87444d68909289f7ae9d99eff3b0cb63`. No integrated pytest suite, Odoo runtime, LLM inference or benchmark was run. Run the new unittest suite, the section870/917/922 targeted pytest tests and the offline project suite before merging. Section1331 fixture/symlink issues remain.

## Required journal append still pending

This file does not replace `todo/contexte.txt`: that journal has NOT been updated. Its complete existing content was preserved. A supported programmable connection attempt was denied; no restriction was bypassed and the large journal was not truncated or archived. Append this publication record, validation and limits to the latest journal using an authorized append-capable environment, selecting the next free section number (1332 at reviewed base), before declaring full compliance with `rules.md`.

Remaining audit: sensitive-source elevated access policy, overbroad security backfills, sufficiency/confidence, concurrency globals, evidence budgets and API error disclosure. Full-file read memory and section1331 root/symlink/fixture defects remain. This first tranche is not a complete audit remediation.
