"""Synchronize an approved shared Google Drive document corpus."""

import argparse
import json
from pathlib import Path
from config.settings import RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chunk-size', type=int, default=RAG_CHUNK_SIZE)
    parser.add_argument('--chunk-overlap', type=int, default=RAG_CHUNK_OVERLAP)
    parser.add_argument('--watch', action='store_true', help='Synchronize immediately, then periodically')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')
    from config.google_drive import GoogleDriveSettings
    try:
        settings = GoogleDriveSettings.from_environment()
        if not settings.folderIds:
            print(json.dumps({'status': 'skipped', 'reason': 'GOOGLE_DRIVE_FOLDER_IDS is not configured'}))
            return 0
        if not settings.approvedForRag:
            parser.exit(2, 'Approve the selected corpus for all RAG readers with GOOGLE_DRIVE_APPROVED_FOR_RAG=true.\n')
        if args.chunk_size <= 0 or not 0 <= args.chunk_overlap < args.chunk_size:
            raise ValueError('Invalid chunk size or overlap.')
        from filelock import FileLock
        from document_rag.ingestion.google_drive import GoogleDriveClient
        from document_rag.ingestion.google_drive_sync import synchronize_google_drive, run_periodic_sync
        from document_rag.vectorstore.chroma_manager import ChromaManager
        client = GoogleDriveClient(timeout=settings.timeout, maxBytes=settings.maxBytes)
        manager = ChromaManager()
        def synchronize():
            return synchronize_google_drive(client, settings.folderIds, manager,
                                            chunkSize=args.chunk_size, chunkOverlap=args.chunk_overlap, maxFiles=settings.maxFiles)
        def emit(result):
            print(json.dumps(result, ensure_ascii=False), flush=True)
        with FileLock(str(manager.db_path / '.google_drive_sync.lock'), timeout=0):
            if args.watch:
                run_periodic_sync(synchronize, settings.syncInterval, emit)
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
