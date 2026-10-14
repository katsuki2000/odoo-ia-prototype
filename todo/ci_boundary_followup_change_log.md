# Code Intelligence source-boundary follow-up

Date: 2026-10-14
Branch: `fix/ci-api-errors`
Starting commit: `d869986d57fdf790543dd84d623ffe69127cdcf0`

The user's request is to continue on the same branch with separate commits, correcting reproducible anomalies without requiring live Odoo or inference services. The rules and principal journal tail were reviewed. Section 1337 documents unpublished model-resolution work in a local worktree unavailable here. No files from that tranche are changed by this lot.

This temporary annex follows the already authorized journal exception. It is not a claim that `todo/contexte.txt` has been updated; its history remains untouched. The entries below must eventually be added to that principal journal.

## Correction 1: source provenance ranges

Commit: `8ffd672574894d455d7b80b2477f8ee5bddb7627`.

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

## Correction 2: fenced source bypasses

Published separately from correction 1 with this commit.

Changed files: `code_intelligence/agent/source_boundary.py`, `tests/test_ci_source_fences.py`, and this annex.

Root cause: the previous whole-block regex only recognized column-zero opening fences followed by an exactly equal closing fence. Indented/container blocks, valid longer closing fences, CRLF lines, and truncated blocks could escape evidence checking and remain in the final answer.

A line-oriented scanner now identifies these fence forms, checks closing character/length, and treats an unclosed fence as extending to the end of the answer. Only closed top-level blocks with up to three leading spaces can be verified and preserved, after indentation normalization and exact comparison with contiguous authorized observations. Fences within detected list/quote containers, tab/four-space-prefixed fences, and incomplete blocks are omitted conservatively, even if their text happens to match evidence. A shorter fence or a fence of another character cannot close a top-level block. Following prose and separately closed blocks retain their boundaries.

This is a conservative source-fence guard, not a general Markdown parser. Inline code, delimiter-free indented code, semantic truth of prose, and every possible nested-Markdown form are not validated by it. No source is read from disk during rendering.

Reproduction: the 14 new test methods produced 25 failures including parameterized subtests before correction. After correction: all 41 targeted tests passed (19 original + 8 range tests + 14 fence tests). Compilation passed. Both diffs reviewed locally. The full MIRO/FastAPI/Odoo environment and repository-wide suite were not executed.

No change to model-resolution files, runtime authorization/group semantics, evidence sufficiency/confidence, main, or miro_ai_discuss. Deployment, graph reconstruction, and live inference testing remain outside this lot.
