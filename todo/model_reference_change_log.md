# Indexed model resolution

Date: 2026-10-14
Branch: `fix/ci-api-errors`
Base: `09dd0bb9cd1cd620dd24c1e26ef36b1a48fec530`

Mandate: proceed even when earlier local work is not published; treat the repository as the source of truth. Main and the user's local worktrees are not modified. Rules and the principal journal tail were reviewed. This annex follows the already authorized temporary journal exception; `todo/contexte.txt` remains unchanged and must later receive these entries.

## Commit 1: deterministic corpus index

Files: `code_intelligence/model_references.py`, `tests/test_ci_model_references.py`, this annex.

Added a standard-library index of technical names and Odoo-generated `model_` XML-ID suffixes. It uses the forward dot-to-underscore formula and retains every candidate when suffixes collide. Lookup accepts exactly one indexed target; it does not invert underscores to dots or accept unknown technical names. Duplicate declarations of the same name are not collisions. Module-qualified generated suffixes are supported; this is static corpus matching, not a runtime `ir.model.data` namespace/alias verification.

Executed: 11 dependency-free unit tests passed; Python compilation passed. No dependency installed. This foundational commit does not yet change graph construction; wiring is a separate commit.

Kaggle: fetching the supplied notebook URL from this environment returned unavailable content (404). This does not establish that the user's running inference service is down. No notebook execution, private credential retrieval, inference request, or model change was performed.
