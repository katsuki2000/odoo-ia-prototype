# API error boundary - change log

Date: 2026-10-14
Branch: `fix/ci-api-errors`
Base: `981a7258abb63dcb2df08afea8b0371747e73ddc` (main)

## Journal exception

The user authorized publication with a temporary journal annex in response to the explicit approval question: "Vas y, tu avais deja mon accord". This annex documents the lot; it does not claim to update `todo/contexte.txt`. The principal journal remains unchanged and must receive this entry before the lot is considered fully journaled there. Its complete history was preserved in the local preparation. The current remote writer requires full-file replacement rather than append; no journal history was truncated and no permission restriction was bypassed.

## Changes published with this commit

- `api/public_errors.py`: one standard-library public error classifier shared by the updated routes. Fixed client-facing messages replace raw exception text. Typed connection/timeout failures, selected network errno values, and XML-RPC HTTP 429/5xx responses yield 503; other unexpected failures yield 500. Causal chains are traversed with cycle detection. Message keywords no longer decide availability status.
- `api/routes_ask.py`: use the common boundary for unexpected processing failures and log diagnostics on the server. Preserve explicit HTTP validation errors. No changes to identity, group or company selection, session ownership, or evidence processing.
- `api/routes_system.py`: require administrators for detailed `/api/v1/health`; retain public lightweight `/health`; remove the configured LLM endpoint from the response and explicitly mark its availability as not checked. Apply the common error boundary to module coverage and statistics.
- `tests/test_api_public_errors.py`: 14 dependency-free unit tests.
- `tests/test_api_error_routes_structure.py`: 5 structural checks, not HTTP integration tests.

## Validation

Executed on the locally prepared Python files before publication:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q api tests
```

Result: 19 checks passed (14 unit tests and 5 structural checks); Python compilation passed. No dependency installed. FastAPI/LangChain/Odoo integration tests and the complete repository suite were not executed in this sandbox. This lot does not claim ERP runtime validation.

## Limitations and review points

- Monitoring that uses detailed health must authenticate as an administrator or use `/health` for public liveness. The LLM is not probed by the health route.
- Server exception logs retain private diagnostic details; access and retention must be protected.
- Third-party transport failures without a recognized causal exception may be classified as 500, not 503. Their exception text is still not returned by this boundary.
- Ingestion error/status payloads are not included in this lot.
- Source visibility policy, access/approval backfills, confidence/evidence sufficiency, shared global request state, and evidence budgets remain outside this lot.
- No changes to the model-resolution tranche B or `miro_ai_discuss`. No migration to native Odoo and no modification or merge into `main`.
