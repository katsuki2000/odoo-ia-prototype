# Code Intelligence source-boundary follow-up

Date: 2026-10-14
Branch: `fix/ci-api-errors`
Starting commit: `d869986d57fdf790543dd84d623ffe69127cdcf0`

The user's request is to continue on the same branch with separate commits, correcting reproducible anomalies without requiring live Odoo or inference services. The rules and principal journal tail were reviewed. Section 1337 documents unpublished model-resolution work in a local worktree unavailable here. No files from that tranche are changed by this lot.

This temporary annex follows the already authorized journal exception. It is not a claim that `todo/contexte.txt` has been updated; its history remains untouched. The entries below must eventually be added to that principal journal.

## Correction 1: source provenance ranges

Changed files: `code_intelligence/agent/source_boundary.py`, `tests/test_ci_citation_ranges.py`, and this annex.

Root cause: rendering trusted citation bounds without checking that lines start at 1, and directly converted arbitrarily large decimal strings. A zero-based observation/citation could authorize a rendered block; a malformed numeric bound could raise ValueError and interrupt rendering.

The same range parser now validates observation citations and nearby answer citations. Only positive ascending ranges are accepted. Numbered observation rows also require a positive, parseable number. Oversized/unparseable numbers are ignored rather than crashing. Contiguous observed-source matching, path identity, and no-filesystem-read behavior are preserved.

Reproduction before correction: 26 targeted tests ran, with 3 failures on zero-based provenance and 1 error on an oversized numeric citation. After correction and an additional oversized-row regression: all 27 tests passed (19 existing, 8 new). Python compilation passed. No dependency installed.

Validation command, run in an isolated source/test subset, not a full repository checkout:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q code_intelligence tests
```

No live Odoo, LLM, embedding calls, complete repository suite, model-resolution validation, or graph rebuild was performed. The separate citation-verification logic in `dispatch_guards.py` is not changed by this correction. No change to main or miro_ai_discuss.
