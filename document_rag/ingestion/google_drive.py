"""Read-only Google Drive ingestion using the existing document loaders."""

from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from config.google_drive import DEFAULT_MAX_BYTES, DEFAULT_MAX_FILES, DEFAULT_TIMEOUT
from document_rag.ingestion.file_formats import is_supported_document

DRIVE_API = 'https://www.googleapis.com/drive/v3/files'
DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
FOLDER_MIME = 'application/vnd.google-apps.folder'
DOC_MIME = 'application/vnd.google-apps.document'
DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def validate_drive_id(file_id):
    if not isinstance(file_id, str) or not ID_PATTERN.fullmatch(file_id):
        raise ValueError('Invalid Google Drive identifier.')
    return file_id


def document_suffix(record):
    if record.get('mimeType') == DOC_MIME:
        return '.docx'
    if record.get('mimeType', '').startswith('application/vnd.google-apps.'):
        return None
    name = record.get('name', '')
    return Path(name).suffix.lower() if is_supported_document(name) else None


class GoogleDriveClient:
    def __init__(self, credentials=None, opener=None, timeout=DEFAULT_TIMEOUT, max_bytes=DEFAULT_MAX_BYTES):
        if credentials is None:
            import google.auth
            credentials, _project = google.auth.default(scopes=[DRIVE_SCOPE])
        self.credentials = credentials
        self.opener = opener or build_opener(NoRedirect()).open
        self.timeout = timeout
        self.max_bytes = max_bytes
        if timeout <= 0 or max_bytes <= 0:
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

    def list_documents(self, folder_ids, max_files=DEFAULT_MAX_FILES):
        queue = deque(validate_drive_id(value) for value in folder_ids)
        visited = set()
        documents = {}
        while queue:
            folder_id = queue.popleft()
            if folder_id in visited:
                continue
            visited.add(folder_id)
            page_token = None
            tokens = set()
            while True:
                parameters = {'q': f"'{folder_id}' in parents and trashed = false", 'pageSize': 1000,
                              'supportsAllDrives': 'true', 'includeItemsFromAllDrives': 'true',
                              'fields': 'nextPageToken,incompleteSearch,files(id,name,mimeType,modifiedTime,version,size,capabilities(canDownload))'}
                if page_token:
                    parameters['pageToken'] = page_token
                with self._request(parameters=parameters) as response:
                    payload = json.load(response)
                if payload.get('incompleteSearch'):
                    raise RuntimeError('Google Drive returned an incomplete inventory.')
                for record in payload.get('files', []):
                    file_id = validate_drive_id(record['id'])
                    if record.get('mimeType') == FOLDER_MIME:
                        queue.append(file_id)
                    else:
                        documents[file_id] = record
                    if len(documents) + len(visited) + len(queue) > max_files:
                        raise ValueError('Google Drive inventory limit exceeded.')
                page_token = payload.get('nextPageToken')
                if not page_token:
                    break
                if page_token in tokens:
                    raise RuntimeError('Google Drive pagination did not advance.')
                tokens.add(page_token)
        return list(documents.values())

    def download(self, record, destination):
        file_id = validate_drive_id(record['id'])
        if record.get('capabilities', {}).get('canDownload') is False:
            raise PermissionError('Google Drive download is not permitted.')
        if int(record.get('size') or 0) > self.max_bytes:
            raise ValueError('Google Drive document exceeds the download limit.')
        export = record.get('mimeType') == DOC_MIME
        path = '/' + file_id + ('/export' if export else '')
        parameters = {'mimeType': DOCX_MIME} if export else {'alt': 'media', 'supportsAllDrives': 'true'}
        total = 0
        with self._request(path, parameters) as response, Path(destination).open('wb') as stream:
            while chunk := response.read(65536):
                total += len(chunk)
                if total > self.max_bytes:
                    raise ValueError('Google Drive document exceeds the download limit.')
                stream.write(chunk)
