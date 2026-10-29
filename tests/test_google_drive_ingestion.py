"""Offline Google Drive connector and ingestion regression tests."""

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, urlsplit

from document_rag.ingestion import google_drive as drive
from document_rag.ingestion.google_drive_sync import refresh_documents, synchronize_google_drive



class FakeCollection:
    def __init__(self):
        self.rows = {}

    def get(self, where, include):
        source = where['source']['$eq']
        selected = [(key, row) for key, row in self.rows.items() if row[1]['source'] == source]
        return {'ids': [key for key, _row in selected], 'metadatas': [row[1] for _key, row in selected]}


class FakeManager:
    def __init__(self):
        self.collection = FakeCollection()
        self.fail_writes = False

    def add_chunks(self, texts, metadatas, ids):
        if self.fail_writes:
            raise RuntimeError('write failed')
        self.collection.rows.update({key: (text, dict(metadata)) for key, text, metadata in zip(ids, texts, metadatas)})
        return ids

    def delete_by_ids(self, ids):
        for key in ids:
            self.collection.rows.pop(key, None)
        return len(ids)


class FakeClient:
    def __init__(self):
        self.record = {'id': 'file_a', 'name': 'guide.txt', 'mimeType': 'text/plain', 'version': '1'}
        self.downloads = 0
        self.content = 'Guide'

    def list_documents(self, folder_ids, max_files):
        return [self.record]

    def download(self, record, destination):
        self.downloads += 1
        Path(destination).write_text(self.content)


def loader(path, chunk_size, chunk_overlap, scan_root):
    return [path.read_text()], [{'source': str(path), 'type': 'doc_wiki', 'chunk_index': 0}]


class GoogleDriveTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.manager = FakeManager()

    def ingest(self):
        return refresh_documents(self.client, [self.client.record], self.manager, loader=loader)

    def test_source_is_drive_url_not_temporary_file(self):
        result = self.ingest()
        metadata = next(iter(self.manager.collection.rows.values()))[1]
        self.assertEqual(metadata['source'], 'https://' + 'drive.google.com/file/d/file_a/view')
        self.assertEqual(metadata['drive_file_id'], 'file_a')
        self.assertEqual(len(result['added']), 1)

    def test_unchanged_revision_skips_download_and_duplicates(self):
        self.ingest()
        result = self.ingest()
        self.assertEqual(self.client.downloads, 1)
        self.assertEqual(len(self.manager.collection.rows), 1)
        self.assertEqual(len(result['skipped']), 1)

    def test_changed_revision_replaces_only_after_successful_write(self):
        self.ingest()
        self.client.record['version'] = '2'
        self.client.content = 'Updated'
        result = self.ingest()
        self.assertEqual(len(self.manager.collection.rows), 1)
        self.assertEqual(result['chunks_deleted'], 1)
        self.assertEqual(len(result['updated']), 1)

    def test_write_failure_keeps_previous_chunks(self):
        self.ingest()
        original = dict(self.manager.collection.rows)
        self.client.record['version'] = '2'
        self.manager.fail_writes = True
        result = self.ingest()
        self.assertEqual(self.manager.collection.rows, original)
        self.assertEqual(len(result['failed']), 1)

    def test_parser_failure_keeps_previous_chunks(self):
        self.ingest()
        original = dict(self.manager.collection.rows)
        self.client.record['version'] = '2'
        result = refresh_documents(self.client, [self.client.record], self.manager, loader=lambda *args: ([], []))
        self.assertEqual(self.manager.collection.rows, original)
        self.assertTrue(result['failed'])

    def test_new_chunk_settings_refresh_metadata(self):
        self.ingest()
        refresh_documents(self.client, [self.client.record], self.manager, loader=loader, chunk_size=256)
        result = refresh_documents(self.client, [self.client.record], self.manager, loader=loader, chunk_size=256)
        self.assertEqual(self.client.downloads, 2)
        self.assertEqual(len(result['skipped']), 1)

    def test_native_docs_export_as_docx_and_shortcuts_are_skipped(self):
        self.assertEqual(drive.document_suffix({'mimeType': drive.DOC_MIME}), '.docx')
        self.assertIsNone(drive.document_suffix({'mimeType': 'application/vnd.google-apps.shortcut', 'name': 'guide.pdf'}))
        self.assertIsNone(drive.document_suffix({'name': '~$guide.docx'}))

    def test_invalid_ids_and_empty_scope_are_rejected(self):
        for value in ('../outside', "a' or trashed=false", ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                drive.validate_drive_id(value)
        with self.assertRaises(ValueError):
            synchronize_google_drive(self.client, [], self.manager, loader=loader)

    def test_download_is_bounded_and_uses_media_endpoint(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            return io.BytesIO(b'large file')
        client = drive.GoogleDriveClient(credentials=SimpleNamespace(valid=True, token='fixture'), opener=opener, max_bytes=4)
        with TemporaryDirectory() as directory, self.assertRaises(ValueError):
            client.download(self.client.record, Path(directory) / 'document.txt')
        self.assertEqual(parse_qs(urlsplit(requests[0].full_url).query)['alt'], ['media'])
        self.assertEqual(requests[0].get_header('Authorization'), 'Bearer fixture')

    def test_docs_download_uses_export_endpoint(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            return io.BytesIO(b'document')
        client = drive.GoogleDriveClient(credentials=SimpleNamespace(valid=True, token='fixture'), opener=opener)
        with TemporaryDirectory() as directory:
            client.download({'id': 'file_a', 'mimeType': drive.DOC_MIME}, Path(directory) / 'document.docx')
        self.assertTrue(urlsplit(requests[0].full_url).path.endswith('/file_a/export'))
        self.assertEqual(parse_qs(urlsplit(requests[0].full_url).query)['mimeType'], [drive.DOCX_MIME])

    def test_pagination_and_recursive_folder_inventory(self):
        responses = iter([{'files': [{'id': 'child', 'mimeType': drive.FOLDER_MIME}], 'nextPageToken': 'next'},
                          {'files': [self.client.record]}, {'files': [self.client.record]}])
        requests = []
        def opener(request, timeout):
            requests.append(request)
            return io.BytesIO(json.dumps(next(responses)).encode())
        client = drive.GoogleDriveClient(credentials=SimpleNamespace(valid=True, token='fixture'), opener=opener)
        records = client.list_documents(['folder_a'])
        self.assertEqual(len(records), 1)
        self.assertEqual(len(requests), 3)
        self.assertEqual(parse_qs(urlsplit(requests[1].full_url).query)['pageToken'], ['next'])

    def test_incomplete_inventory_fails_closed(self):
        client = drive.GoogleDriveClient(credentials=SimpleNamespace(valid=True, token='fixture'),
                                         opener=lambda *args, **kwargs: io.BytesIO(b'{"incompleteSearch":true}'))
        with self.assertRaises(RuntimeError):
            client.list_documents(['folder_a'])

    def test_repeated_page_token_is_rejected(self):
        client = drive.GoogleDriveClient(credentials=SimpleNamespace(valid=True, token='fixture'),
                                         opener=lambda *args, **kwargs: io.BytesIO(b'{"nextPageToken":"same"}'))
        with self.assertRaises(RuntimeError):
            client.list_documents(['folder_a'])

    def test_permission_denied_download_is_not_attempted(self):
        client = drive.GoogleDriveClient(credentials=SimpleNamespace(valid=True, token='fixture'),
                                         opener=lambda *args, **kwargs: self.fail('Network request should not occur'))
        with self.assertRaises(PermissionError):
            client.download({'id': 'file_a', 'capabilities': {'canDownload': False}}, 'unused')

    def test_absent_files_are_not_deleted_automatically(self):
        self.ingest()
        self.client.list_documents = lambda *args, **kwargs: []
        self.ingest()
        self.assertEqual(len(self.manager.collection.rows), 1)


if __name__ == '__main__':
    unittest.main()
