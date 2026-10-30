"""Reconciliation and refresh of one approved Drive corpus per RAG collection."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError

from config.google_drive import DEFAULT_MAX_FILES
from config.settings import RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE
from document_rag.ingestion.document_loader import load_document
from document_rag.ingestion.google_drive import document_suffix, validate_drive_id


class DriveScopeUnavailable(Exception):
    pass


def _source_url(file_id):
    return f'https://drive.google.com/file/d/{file_id}/view'


def verify_folders(client, folder_ids):
    for folder_id in folder_ids:
        validate_drive_id(folder_id)
        try:
            with client._request('/' + folder_id, {'fields': 'id,mimeType', 'supportsAllDrives': 'true'}) as response:
                record = json.load(response)
        except HTTPError as error:
            if error.code == 404:
                raise DriveScopeUnavailable('Configured folder is missing or inaccessible.') from error
            raise
        if record.get('mimeType') != 'application/vnd.google-apps.folder':
            raise ValueError('Configured Drive identifier is not a folder.')


def drive_inventory(manager):
    rows = manager.collection.get(where={'origin': {'$eq': 'google_drive'}}, include=['metadatas'])
    ids = rows.get('ids', [])
    metadatas = rows.get('metadatas', [])
    if len(ids) != len(metadatas) or any(not metadata or not metadata.get('drive_file_id') for metadata in metadatas):
        raise ValueError('Drive index inventory is incomplete.')
    return list(zip(ids, metadatas))


def deactivate_chunks(manager, chunk_ids):
    if not chunk_ids:
        return 0
    manager.collection.update(ids=chunk_ids, metadatas=[{'drive_active': False} for _ in chunk_ids])
    return manager.delete_by_ids(chunk_ids)


def _refresh_document(client, record, manager, loader, chunk_size, chunk_overlap, profile):
    """Index one readable document; return (status, chunks_added, chunks_deleted)."""
    file_id = validate_drive_id(record['id'])
    source = _source_url(file_id)
    revision = str(record.get('version') or record.get('modifiedTime') or '')
    existing = manager.collection.get(where={'source': {'$eq': source}}, include=['metadatas'])
    old_ids = existing.get('ids', [])
    old_metadata = existing.get('metadatas', [])
    if revision and old_ids and len(old_metadata) == len(old_ids) and all(
        item and item.get('drive_revision') == revision and item.get('drive_profile') == profile
        for item in old_metadata
    ):
        return 'skipped', 0, 0
    with TemporaryDirectory(prefix='miro-drive-') as temporary:
        path = Path(temporary) / ('document' + document_suffix(record))
        client.download(record, path)
        chunks, metadatas = loader(path, chunk_size, chunk_overlap, Path(temporary))
    if not chunks or len(chunks) != len(metadatas):
        raise ValueError('Document parsing did not return valid chunks and metadata.')
    new_ids = []
    for index, (text, metadata) in enumerate(zip(chunks, metadatas)):
        metadata.update(source=source, title=record.get('name', ''), drive_file_id=file_id,
                        drive_revision=revision, drive_profile=profile, origin='google_drive')
        new_ids.append('drive_' + hashlib.sha256(f'{source}\0{revision}\0{profile}\0{index}\0{text}'.encode()).hexdigest())
    old_id_set = set(old_ids)
    pending = [index for index, chunk_id in enumerate(new_ids) if chunk_id not in old_id_set]
    chunks_added = 0
    if pending:
        added = manager.add_chunks([chunks[index] for index in pending],
                                   [metadatas[index] for index in pending], ids=[new_ids[index] for index in pending])
        if set(added) != {new_ids[index] for index in pending}:
            raise RuntimeError('Document indexing did not confirm all new chunks.')
        chunks_added = len(added)
    new_id_set = set(new_ids)
    chunks_deleted = manager.delete_by_ids([chunk_id for chunk_id in old_ids if chunk_id not in new_id_set])
    return ('updated' if old_ids else 'added'), chunks_added, chunks_deleted


def refresh_documents(client, records, manager, loader=None, chunk_size=RAG_CHUNK_SIZE, chunk_overlap=RAG_CHUNK_OVERLAP):
    """Index new and changed readable documents; a failed document keeps its previous chunks."""
    if loader is None:
        loader = load_document
    result = {'added': [], 'updated': [], 'skipped': [], 'failed': {}, 'chunks_added': 0, 'chunks_deleted': 0}
    profile = f'google-drive-v1:{chunk_size}:{chunk_overlap}'
    for record in records:
        source = _source_url(validate_drive_id(record['id']))
        try:
            status, chunks_added, chunks_deleted = _refresh_document(
                client, record, manager, loader, chunk_size, chunk_overlap, profile)
        except Exception as error:
            result['failed'][source] = type(error).__name__
            continue
        result[status].append(source)
        result['chunks_added'] += chunks_added
        result['chunks_deleted'] += chunks_deleted
    return result


def synchronize_google_drive(client, folder_ids, manager, loader=None, chunk_size=RAG_CHUNK_SIZE,
                             chunk_overlap=RAG_CHUNK_OVERLAP, max_files=DEFAULT_MAX_FILES):
    if not folder_ids:
        raise ValueError('Configure at least one approved Drive folder.')
    if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size or max_files <= 0:
        raise ValueError('Invalid Drive synchronization settings.')
    try:
        verify_folders(client, folder_ids)
    except DriveScopeUnavailable:
        deleted = deactivate_chunks(manager, [chunk_id for chunk_id, _metadata in drive_inventory(manager)])
        return {'status': 'blocked', 'reason': 'configured_folder_unavailable', 'chunks_deleted': deleted, 'failed': {}}
    readable = [record for record in client.list_documents(folder_ids, max_files=max_files)
                if document_suffix(record) is not None and record.get('capabilities', {}).get('canDownload') is not False]
    readable_ids = {record['id'] for record in readable}
    obsolete_ids = [chunk_id for chunk_id, metadata in drive_inventory(manager)
                    if metadata['drive_file_id'] not in readable_ids or metadata.get('drive_active', True) is False]
    deleted = deactivate_chunks(manager, obsolete_ids)
    result = refresh_documents(client, readable, manager, loader, chunk_size, chunk_overlap)
    result['chunks_deleted'] += deleted
    result['status'] = 'partial' if result['failed'] else 'complete'
    return result
