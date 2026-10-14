"""Periodic reconciliation of one approved Drive corpus per RAG collection."""

import json
from threading import Event
from urllib.error import HTTPError

from document_rag.ingestion.google_drive import document_suffix, ingest_google_drive, validate_drive_id


class DriveScopeUnavailable(Exception):
    pass


def verify_folders(client, folderIds):
    for folderId in folderIds:
        validate_drive_id(folderId)
        try:
            with client._request('/' + folderId, {'fields': 'id,mimeType', 'supportsAllDrives': 'true'}) as response:
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


def deactivate_chunks(manager, chunkIds):
    if not chunkIds:
        return 0
    manager.collection.update(ids=chunkIds, metadatas=[{'drive_active': False} for _ in chunkIds])
    return manager.delete_by_ids(chunkIds)


class InventorySnapshotClient:
    def __init__(self, client, records):
        self.client = client
        self.records = records

    def list_documents(self, folderIds, maxFiles):
        return self.records

    def download(self, record, destination):
        self.client.download(record, destination)


def synchronize_google_drive(client, folderIds, manager, loader=None, chunkSize=512, chunkOverlap=50, maxFiles=10000):
    if not folderIds:
        raise ValueError('Configure at least one approved Drive folder.')
    if chunkSize <= 0 or not 0 <= chunkOverlap < chunkSize or maxFiles <= 0:
        raise ValueError('Invalid Drive synchronization settings.')
    try:
        verify_folders(client, folderIds)
    except DriveScopeUnavailable:
        inventory = drive_inventory(manager)
        deleted = deactivate_chunks(manager, [chunkId for chunkId, _metadata in inventory])
        return {'status': 'blocked', 'reason': 'configured_folder_unavailable', 'chunks_deleted': deleted, 'failed': {}}
    records = client.list_documents(folderIds, maxFiles=maxFiles)
    allowedIds = {record['id'] for record in records if document_suffix(record) is not None
                  and record.get('capabilities', {}).get('canDownload') is not False}
    inventory = drive_inventory(manager)
    obsoleteIds = [chunkId for chunkId, metadata in inventory
                   if metadata['drive_file_id'] not in allowedIds or metadata.get('drive_active', True) is False]
    deleted = deactivate_chunks(manager, obsoleteIds)
    readableRecords = [record for record in records if record['id'] in allowedIds]
    result = ingest_google_drive(InventorySnapshotClient(client, readableRecords), folderIds, manager,
                                 loader=loader, chunkSize=chunkSize, chunkOverlap=chunkOverlap, maxFiles=maxFiles)
    result['chunks_deleted'] += deleted
    result['status'] = 'partial' if result['failed'] else 'complete'
    return result


def run_periodic_sync(action, intervalSeconds, emit, stopEvent=None):
    if intervalSeconds <= 0:
        raise ValueError('Synchronization interval must be positive.')
    stopEvent = stopEvent or Event()
    while not stopEvent.is_set():
        try:
            emit(action())
        except Exception as error:
            emit({'status': 'failed', 'error_type': type(error).__name__})
        if stopEvent.wait(intervalSeconds):
            break
