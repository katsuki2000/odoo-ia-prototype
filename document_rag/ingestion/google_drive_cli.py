"""Synchronize an approved shared Google Drive document corpus."""

import argparse
import json
from config.settings import RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chunk-size', type=int, default=RAG_CHUNK_SIZE)
    parser.add_argument('--chunk-overlap', type=int, default=RAG_CHUNK_OVERLAP)
    parser.add_argument('--watch', action='store_true', help='Synchronize immediately, then periodically')
    args = parser.parse_args()
    from config.google_drive import GoogleDriveSettings
    try:
        settings = GoogleDriveSettings.current()
        if not settings.folder_ids:
            print(json.dumps({'status': 'skipped', 'reason': 'GOOGLE_DRIVE_FOLDER_IDS is not configured'}))
            return 0
        if not settings.approved_for_rag:
            parser.exit(2, 'Approve the selected corpus for all RAG readers with GOOGLE_DRIVE_APPROVED_FOR_RAG=true.\n')
        if args.chunk_size <= 0 or not 0 <= args.chunk_overlap < args.chunk_size:
            raise ValueError('Invalid chunk size or overlap.')
        from filelock import FileLock
        from document_rag.ingestion.google_drive import GoogleDriveClient
        from document_rag.ingestion.google_drive_sync import synchronize_google_drive
        from document_rag.ingestion.periodic import run_periodically
        from document_rag.vectorstore.chroma_manager import ChromaManager
        client = GoogleDriveClient(timeout=settings.timeout, max_bytes=settings.max_bytes)
        manager = ChromaManager()
        def synchronize():
            return synchronize_google_drive(client, settings.folder_ids, manager,
                                            chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap, max_files=settings.max_files)
        def emit(result):
            print(json.dumps(result, ensure_ascii=False), flush=True)
        with FileLock(str(manager.db_path / '.google_drive_sync.lock'), timeout=0):
            if args.watch:
                run_periodically(synchronize, settings.sync_interval, emit)
                return 0
            result = synchronize()
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        parser.exit(2, f'Google Drive synchronization failed ({type(error).__name__}). Check configuration and credentials.\n')
    emit(result)
    return 1 if result.get('failed') or result.get('status') == 'blocked' else 0


if __name__ == '__main__':
    raise SystemExit(main())
