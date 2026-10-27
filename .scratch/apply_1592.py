import re
from pathlib import Path

root = Path('.')
IMPORT = 'from config.settings import RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE\n'


def edit(path, substitutions, import_after=None):
    file = root / path
    text = file.read_text()
    for pattern, replacement in substitutions:
        text, count = re.subn(pattern, replacement, text)
        assert count, (path, pattern)
    if import_after:
        assert import_after in text, (path, import_after)
        text = text.replace(import_after, import_after + IMPORT, 1)
    file.write_text(text)


size = (r'chunk_size: int = 512', 'chunk_size: int = RAG_CHUNK_SIZE')
overlap = (r'chunk_overlap: int = 50', 'chunk_overlap: int = RAG_CHUNK_OVERLAP')

settings = root / 'config/settings.py'
text = settings.read_text()
anchor = "RAG_DOCS_PATH = str(_ROOT / 'document_rag' / 'documents')\n"
assert anchor in text
settings.write_text(text.replace(anchor, anchor + "RAG_CHUNK_SIZE = 512\nRAG_CHUNK_OVERLAP = 50\n", 1))

edit('document_rag/ingestion/pdf_loader.py', [size, overlap,
     (r'\(512 tokens, 50 overlap\)', '(sizes from config.settings)')], 'from __future__ import annotations\n\n')
edit('document_rag/ingestion/wiki_loader.py', [size, overlap], 'from __future__ import annotations\n\n')
edit('document_rag/ingestion/incremental.py', [size, overlap], 'from urllib.parse import urlsplit\n')
edit('document_rag/ingestion/watcher.py', [size, overlap], None)
edit('document_rag/ingestion/ingest_all.py', [size, overlap,
     (r'from config.settings import CHROMA_PATH, DOCS_COLLECTION_NAME\n',
      'from config.settings import CHROMA_PATH, DOCS_COLLECTION_NAME, RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE\n')])
edit('document_rag/ingestion/ingest_cli.py', [
     (r'default=512', 'default=RAG_CHUNK_SIZE'), (r'default=50', 'default=RAG_CHUNK_OVERLAP'),
     (r'from config.settings import CHROMA_PATH\n', 'from config.settings import CHROMA_PATH, RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE\n')])
edit('document_rag/ingestion/google_drive.py', [
     (r'chunkSize=512, chunkOverlap=50', 'chunkSize=RAG_CHUNK_SIZE, chunkOverlap=RAG_CHUNK_OVERLAP')], 'from urllib.request import HTTPRedirectHandler, Request, build_opener\n\n')
edit('document_rag/ingestion/google_drive_sync.py', [
     (r'chunkSize=512, chunkOverlap=50', 'chunkSize=RAG_CHUNK_SIZE, chunkOverlap=RAG_CHUNK_OVERLAP')], 'from urllib.error import HTTPError\n\n')
edit('document_rag/ingestion/google_drive_cli.py', [
     (r"'--chunk-size', type=int, default=512", "'--chunk-size', type=int, default=RAG_CHUNK_SIZE"),
     (r"'--chunk-overlap', type=int, default=50", "'--chunk-overlap', type=int, default=RAG_CHUNK_OVERLAP"),
     (r'    from config.google_drive import GoogleDriveSettings\n',
      '    from config.google_drive import GoogleDriveSettings\n')])
edit('scripts/run_scalability_test.py', [
     (r'chunk_size=512,', 'chunk_size=RAG_CHUNK_SIZE,'), (r'chunk_overlap=50,', 'chunk_overlap=RAG_CHUNK_OVERLAP,')],
     'from pathlib import Path\nfrom typing import Any\n')
