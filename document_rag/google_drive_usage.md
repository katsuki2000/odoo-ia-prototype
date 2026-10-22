# Shared Google Drive corpus

One approved shared Drive corpus per target RAG collection. No mapping between Google accounts and Odoo users is required: a technical identity reads the folders, and the selected documents must be approved for every reader of that RAG collection. This is not per-user Drive authorization.

## Install and authenticate

Inside the project virtual environment:

```bash
pip install -r requirements-google-drive.txt
```

Enable Google Drive API in your Google Cloud project. Use Application Default Credentials (ADC), preferably a dedicated service account with reader access only to the approved folders. Share those folders with the service account. On AWS, use supported workload identity federation or a credential file provisioned outside the repository. Authorized-user ADC is also supported; there is no interactive OAuth setup in this feature.

Never commit credential JSON, index it as a document, or paste keys into chat. Configuration is centralized in `config/google_drive.py`; the existing Chroma and embedding settings remain authoritative.

```dotenv
GOOGLE_DRIVE_FOLDER_IDS=your_folder_id
GOOGLE_APPLICATION_CREDENTIALS=path_to_external_credentials.json
GOOGLE_DRIVE_APPROVED_FOR_RAG=true
GOOGLE_DRIVE_SYNC_INTERVAL_SECONDS=300
GOOGLE_DRIVE_TIMEOUT=30
GOOGLE_DRIVE_MAX_BYTES=20971520
GOOGLE_DRIVE_MAX_FILES=10000
```

Replace placeholders. Folder IDs can be comma-separated. Keep one Drive corpus per collection; use separate storage/collections for distinct audiences or tenants. Changing the folder set authorizes reconciliation against the new set, including removal of old out-of-scope Drive chunks.

## Run

One reconciliation:

```bash
python -m document_rag.ingestion.google_drive_cli
```

Continuous worker, immediate scan then every configured interval:

```bash
python -m document_rag.ingestion.google_drive_cli --watch
```

Run this worker under your deployment supervisor if it must survive logout/restart. No server or supervisor was configured by this change. A lock in the target Chroma directory excludes another instance of this CLI worker. Distributed hosts need a shared locking/storage strategy or one designated writer; a local file lock is not a distributed lease.

Without folders the command skips without initializing Google or Chroma. An approved corpus is required. Single-run exit codes: 0 complete/skipped; 1 per-file errors or blocked corpus; 2 configuration/authentication/inventory/storage failure. Watch mode emits a result every cycle, retries failures at the configured interval, and stops on interruption; supervise its reports, not only its process exit code.

## Synchronization and retrieval

Each cycle uses a full paginated folder inventory, not Drive Changes or a persistent cursor. File revisions avoid unnecessary downloads. Inventory limits or incomplete listings abort before removal. Timeouts, generic 403/quota errors and other ambiguous failures do not imply deletion.

After a complete inventory, Drive chunks for files absent from the selected corpus, unsupported files or files explicitly marked non-downloadable are deactivated before physical deletion. Local filesystem sources are untouched. Ingestion of current readable files reuses the original loaders and adds replacement chunks before deleting old ones.

If a configured root returns 404, it is missing or inaccessible; the entire Drive corpus of that collection is deactivated and purged rather than guessing which roots own old chunks. Local documents remain. Recovery can reindex the shared corpus. Generic 403 errors remain ambiguous and pause synchronization without purging; investigate them operationally. A download error occurring after inventory does not automatically revoke an existing indexed copy.

The main retrieval pipeline checks current chunk IDs and the `drive_active` flag for vector/lexical candidates, before and after contiguous expansion. Stale BM25 entries for removed/deactivated Drive chunks are excluded. Availability lookup failures drop Drive candidates rather than trusting cached text. Tombstones stay effective if physical cleanup fails after deactivation; failure of deactivation itself aborts and requires operator intervention. New documents are visible to vector retrieval after ingestion; an existing cached BM25 index still needs rebuilding/restarting to include new lexical entries.

This is periodic shared-corpus reconciliation, not instantaneous revocation or an end-user permission check. Detection waits until a successful cycle; outages can extend that delay. Already generated answers, chat history and requests already in flight are not erased by chunk removal. Do not use a private/dynamically restricted corpus with this shared-reader model.

## Formats and safety

PDF, TXT, Markdown and DOCX reuse existing loaders. Google Docs export as DOCX. Other Google-native types and shortcuts are skipped. Subfolders and shared-drive listing flags are supported, subject to a live shared-drive validation. Downloads are bounded and temporary. Redirects are refused to avoid forwarding bearer tokens. Sources retain stable Drive file URLs.

## Tests and outstanding validation

```bash
python -m unittest discover -s tests -p 'test_google_drive*.py' -v
```

29 offline tests passed: the original 15 plus 14 synchronization/availability tests. HTTP, manager and parser interfaces use fixtures; two local-inventory helpers are executed in isolation from their parsed source. Compilation and the disabled CLI path passed. The full retrieval pipeline, real Chroma metadata updates, inter-process locking, live Drive credentials/downloads, production parsers and embeddings still need integration tests in the project environment. No live ingestion was started here.
