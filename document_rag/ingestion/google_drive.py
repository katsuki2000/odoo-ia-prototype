"""Read-only Google Drive ingestion using the existing document loaders."""

from __future__ import annotations

from collections import deque
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from config.settings import RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE


DRIVE_API = 'https://www.googleapis.com/drive/v3/files'
DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
FOLDER_MIME = 'application/vnd.google-apps.folder'
DOC_MIME = 'application/vnd.google-apps.document'
DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
SUPPORTED_SUFFIXES = {'.pdf', '.txt', '.md', '.docx'}
ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newUrl):
        return None


def validate_drive_id(fileId):
    if not isinstance(fileId, str) or not ID_PATTERN.fullmatch(fileId):
        raise ValueError('Invalid Google Drive identifier.')
    return fileId


def document_suffix(record):
    if record.get('mimeType') == DOC_MIME:
        return '.docx'
    if record.get('mimeType', '').startswith('application/vnd.google-apps.'):
        return None
    name = record.get('name', '')
    suffix = Path(name).suffix.lower()
    return suffix if suffix in SUPPORTED_SUFFIXES and not name.startswith('~$') else None


class GoogleDriveClient:
    def __init__(self, credentials=None, opener=None, timeout=30, maxBytes=20971520):
        if credentials is None:
            import google.auth
            credentials, _project = google.auth.default(scopes=[DRIVE_SCOPE])
        self.credentials = credentials
        self.opener = opener or build_opener(NoRedirect()).open
        self.timeout = timeout
        self.maxBytes = maxBytes
        if timeout <= 0 or maxBytes <= 0:
            raise ValueError('Timeout and download limit must be positive.')

    def _request(self, path='', parameters=None):
        if not self.credentials.valid:
            from google.auth.transport.requests import Request as AuthRequest
            self.credentials.refresh(AuthRequest())
        url = DRIVE_API + path
        if parameters:
            url += '?' + urlencode(parameters)
        request = Request(url, headers={'Authorization': 'Bearer ' + self.credentials.token})
        return self.opener(request, timeout=self.timeout)

    def list_documents(self, folderIds, maxFiles=10000):
        queue = deque(validate_drive_id(value) for value in folderIds)
        visited = set()
        documents = {}
        while queue:
            folderId = queue.popleft()
            if folderId in visited:
                continue
            visited.add(folderId)
            pageToken = None
            tokens = set()
            while True:
                parameters = {'q': f"'{folderId}' in parents and trashed = false", 'pageSize': 1000,
                              'supportsAllDrives': 'true', 'includeItemsFromAllDrives': 'true',
                              'fields': 'nextPageToken,incompleteSearch,files(id,name,mimeType,modifiedTime,version,size,capabilities(canDownload))'}
                if pageToken:
                    parameters['pageToken'] = pageToken
                with self._request(parameters=parameters) as response:
                    payload = json.load(response)
                if payload.get('incompleteSearch'):
                    raise RuntimeError('Google Drive returned an incomplete inventory.')
                for record in payload.get('files', []):
                    fileId = validate_drive_id(record['id'])
                    if record.get('mimeType') == FOLDER_MIME:
                        queue.append(fileId)
                    else:
                        documents[fileId] = record
                    if len(documents) + len(visited) + len(queue) > maxFiles:
                        raise ValueError('Google Drive inventory limit exceeded.')
                pageToken = payload.get('nextPageToken')
                if not pageToken:
                    break
                if pageToken in tokens:
                    raise RuntimeError('Google Drive pagination did not advance.')
                tokens.add(pageToken)
        return list(documents.values())

    def download(self, record, destination):
        fileId = validate_drive_id(record['id'])
        if record.get('capabilities', {}).get('canDownload') is False:
            raise PermissionError('Google Drive download is not permitted.')
        if int(record.get('size') or 0) > self.maxBytes:
            raise ValueError('Google Drive document exceeds the download limit.')
        export = record.get('mimeType') == DOC_MIME
        path = '/' + fileId + ('/export' if export else '')
        parameters = {'mimeType': DOCX_MIME} if export else {'alt': 'media', 'supportsAllDrives': 'true'}
        total = 0
        with self._request(path, parameters) as response, Path(destination).open('wb') as stream:
            while chunk := response.read(65536):
                total += len(chunk)
                if total > self.maxBytes:
                    raise ValueError('Google Drive document exceeds the download limit.')
                stream.write(chunk)


def ingest_google_drive(client, folderIds, manager, loader=None, chunkSize=RAG_CHUNK_SIZE, chunkOverlap=RAG_CHUNK_OVERLAP, maxFiles=10000):
    """Refresh readable documents; never automatically delete absent Drive files."""
    if not folderIds:
        raise ValueError('Configure at least one approved Google Drive folder.')
    if chunkSize <= 0 or not 0 <= chunkOverlap < chunkSize:
        raise ValueError('Invalid chunk size or overlap.')
    records = client.list_documents(folderIds, maxFiles=maxFiles)
    if loader is None:
        from document_rag.ingestion.incremental import _load_file
        loader = _load_file
    result = {'added': [], 'updated': [], 'skipped': [], 'failed': {}, 'chunks_added': 0, 'chunks_deleted': 0}
    profile = f'google-drive-v1:{chunkSize}:{chunkOverlap}'
    for record in records:
        fileId = validate_drive_id(record['id'])
        source = 'https://' + 'drive.google.com/file/d/' + fileId + '/view'
        suffix = document_suffix(record)
        if suffix is None:
            result['skipped'].append(source)
            continue
        revision = str(record.get('version') or record.get('modifiedTime') or '')
        try:
            existing = manager.collection.get(where={'source': {'$eq': source}}, include=['metadatas'])
            oldIds = existing.get('ids', [])
            oldMetadata = existing.get('metadatas', [])
            if revision and oldIds and len(oldMetadata) == len(oldIds) and all(
                item and item.get('drive_revision') == revision and item.get('drive_profile') == profile
                for item in oldMetadata
            ):
                result['skipped'].append(source)
                continue
            with TemporaryDirectory(prefix='miro-drive-') as temporary:
                path = Path(temporary) / ('document' + suffix)
                client.download(record, path)
                chunks, metadatas = loader(path, chunkSize, chunkOverlap, Path(temporary))
            if not chunks or len(chunks) != len(metadatas):
                raise ValueError('Document parsing did not return valid chunks and metadata.')
            newIds = []
            for index, (text, metadata) in enumerate(zip(chunks, metadatas)):
                metadata.update(source=source, title=record.get('name', ''), drive_file_id=fileId,
                                drive_revision=revision, drive_profile=profile, origin='google_drive')
                newIds.append('drive_' + hashlib.sha256(f'{source}\0{revision}\0{profile}\0{index}\0{text}'.encode()).hexdigest())
            oldIdSet = set(oldIds)
            pending = [index for index, chunkId in enumerate(newIds) if chunkId not in oldIdSet]
            if pending:
                added = manager.add_chunks([chunks[index] for index in pending],
                                           [metadatas[index] for index in pending], ids=[newIds[index] for index in pending])
                if set(added) != {newIds[index] for index in pending}:
                    raise RuntimeError('Document indexing did not confirm all new chunks.')
                result['chunks_added'] += len(added)
            newIdSet = set(newIds)
            result['chunks_deleted'] += manager.delete_by_ids([chunkId for chunkId in oldIds if chunkId not in newIdSet])
            result['updated' if oldIds else 'added'].append(source)
        except Exception as error:
            result['failed'][source] = type(error).__name__
    return result
