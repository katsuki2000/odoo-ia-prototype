"""Manual ingestion of an approved Google Drive document corpus."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chunk-size', type=int, default=512)
    parser.add_argument('--chunk-overlap', type=int, default=50)
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
        from document_rag.ingestion.google_drive import GoogleDriveClient, ingest_google_drive
        from document_rag.vectorstore.chroma_manager import ChromaManager
        client = GoogleDriveClient(timeout=settings.timeout, maxBytes=settings.maxBytes)
        result = ingest_google_drive(client, settings.folderIds, ChromaManager(),
                                     chunkSize=args.chunk_size, chunkOverlap=args.chunk_overlap, maxFiles=settings.maxFiles)
    except Exception as error:
        parser.exit(2, f'Google Drive ingestion failed ({type(error).__name__}). Check configuration and credentials.\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
