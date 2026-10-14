# Google Drive document ingestion

Manual, read-only ingestion of an approved folder corpus into the existing document RAG Chroma collection. This feature does not change Odoo addons, the local ingestion scheduler, the API or the graph.

## Configure

In the project virtual environment:

```bash
pip install -r requirements-google-drive.txt
```

Enable the Google Drive API in your Google Cloud project. Use Application Default Credentials (ADC), preferably a dedicated service account whose access is limited to the selected corpus. Share the selected folders with that account as a reader. On AWS, use supported workload identity federation or provision the credential file outside the repository. An authorized-user ADC profile is also supported by google-auth; this feature does not provide an interactive OAuth browser flow.

Keep credentials outside Git and outside the document ingestion directories. Do not paste keys or tokens into chat, commit them, or index the credential JSON. `GOOGLE_APPLICATION_CREDENTIALS` is the standard ADC environment variable, not a file that the connector creates.

Add to your local `.env` (replace placeholders with your own configuration):

```dotenv
GOOGLE_DRIVE_FOLDER_IDS=your_folder_id
GOOGLE_APPLICATION_CREDENTIALS=path_to_external_credentials.json
GOOGLE_DRIVE_APPROVED_FOR_RAG=true
GOOGLE_DRIVE_TIMEOUT=30
GOOGLE_DRIVE_MAX_BYTES=20971520
GOOGLE_DRIVE_MAX_FILES=10000
```

Multiple folder identifiers may be comma-separated. Use identifiers from the folder URLs, not the full URLs. Configuration is centralized in `config/google_drive.py`. Existing `CHROMA_PATH`, `DOCS_COLLECTION_NAME` and embedding configuration remain authoritative. No credentials or account-specific configuration are included in the branch.

## Audience and retention

Only set `GOOGLE_DRIVE_APPROVED_FOR_RAG=true` after confirming that every document in the selected folders and their descendants can be exposed to every reader of the target RAG collection. Service-account access is not end-user authorization. There is no per-user Drive ACL filtering at retrieval time. Use a curated shared knowledge corpus, never arbitrary private employee folders. Keep separate Chroma storage/collections for audiences or tenants that must not share documents.

This is manual import/refresh, not continuous permission synchronization. Absent, deleted, inaccessible or unsupported files are not automatically purged from Chroma. A previously imported file may remain searchable after access changes or after it leaves the folder. Review and remove affected indexed sources before changing the approved corpus or its audience. Do not use this mode for a corpus requiring immediate permission revocation. The scope is read-only; the connector never edits or deletes remote files.

## Run

```bash
python -m document_rag.ingestion.google_drive_cli
```

Without folders configured, the command reports `skipped` without initializing Google authentication or Chroma. With folders configured but no explicit corpus approval, it refuses to ingest. Exit codes: 0 successful/skipped; 1 per-file failures; 2 configuration, authentication, inventory or startup failure.

PDF, TXT, Markdown and DOCX files use the existing document loaders. Native Google Docs are exported as DOCX and passed through the existing DOCX loader. Other Google-native types (Sheets, Slides, shortcuts) are skipped. Subfolders are traversed, with pagination and bounded inventory; shortcuts are not followed outside the chosen corpus. Shared-drive listing flags are included, but a live shared-drive run still needs validation.

Downloads are bounded, stored in temporary directories, and removed after parsing. Redirects are refused so bearer credentials are never forwarded to another host; deployments that encounter download redirects fail rather than silently relaxing this protection. Sources point to stable Drive file URLs, not temporary paths. Metadata records the Drive file ID, revision, title, origin and chunk profile. Unchanged revisions skip downloads; changes to chunk size/overlap also trigger refresh.

New chunks are added before obsolete chunks of the same source are deleted. Parser/read/write failures preserve the previous chunks. Chroma updates are not cross-operation transactions; partial writes or cleanup failures can leave extra chunks. Retry and inspect failures. Run a single ingestion writer per target collection. This command does not claim to repair the local ingestion pipeline's existing transaction behavior.

## Validation

```bash
python -m unittest discover -s tests -p test_google_drive_ingestion.py -v
```

The connector was exercised with 15 offline tests using fake HTTP responses, credentials, collection and parser interfaces. The real connector and ingestion code run in those tests. The no-folder CLI path also passed. No live Google authentication, Drive download, production PDF/DOCX parsing, embeddings or Chroma integration was performed here. Test those in the project virtual environment before enabling ingestion against your real corpus.
