"""Offline shared-corpus reconciliation and retrieval safety tests."""

import ast
import io
import json
import logging
from pathlib import Path
import unittest
from urllib.error import HTTPError
from urllib.parse import urlsplit

from document_rag.ingestion.google_drive_sync import synchronize_google_drive
from document_rag.ingestion.periodic import run_periodically
from document_rag.vectorstore.drive_guard import filter_current_drive_chunks

ROOT = Path(__file__).resolve().parents[1]


class Collection:
    def __init__(self):
        self.rows = {'old': {'origin': 'google_drive', 'drive_file_id': 'old_file', 'source': 'old_source'},
                     'local': {'source': 'local.txt'}}
        self.fail_deletes = False

    def get(self, ids=None, where=None, include=None):
        keys = list(self.rows) if ids is None else [key for key in ids if key in self.rows]
        if where and 'origin' in where:
            keys = [key for key in keys if self.rows[key].get('origin') == 'google_drive']
        if where and 'source' in where:
            source = where['source']['$eq']
            keys = [key for key in keys if self.rows[key]['source'] == source]
        return {'ids': keys, 'metadatas': [dict(self.rows[key]) for key in keys]}

    def update(self, ids, metadatas):
        for key, patch in zip(ids, metadatas):
            self.rows[key].update(patch)


class Manager:
    def __init__(self):
        self.collection = Collection()

    def delete_by_ids(self, ids):
        if self.collection.fail_deletes and ids:
            raise RuntimeError('cleanup failed')
        for key in ids:
            self.collection.rows.pop(key, None)
        return len(ids)

    def add_chunks(self, chunks, metadatas, ids):
        self.collection.rows.update({key: dict(metadata) for key, metadata in zip(ids, metadatas)})
        return ids


class Client:
    def __init__(self):
        self.records = []
        self.error = None
        self.folder_error = None

    def _request(self, path, parameters):
        if self.folder_error:
            raise self.folder_error
        return io.BytesIO(json.dumps({'mimeType': 'application/vnd.google-apps.folder'}).encode())

    def list_documents(self, folder_ids, max_files):
        if self.error:
            raise self.error
        return self.records

    def download(self, record, path):
        Path(path).write_text('Current guide')


def loader(path, *args):
    return [path.read_text()], [{'chunk_index': 0}]


def candidate(chunk_id='old', origin='google_drive'):
    return {'id': chunk_id, 'document': 'Cached text', 'metadata': {'origin': origin}}


def load_function(relative_path, name, namespace):
    tree = ast.parse((ROOT / relative_path).read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, relative_path, 'exec'), namespace)
    return namespace[name]


class SharedDriveSyncTests(unittest.TestCase):
    def setUp(self):
        self.manager = Manager()
        self.client = Client()

    def sync(self):
        return synchronize_google_drive(self.client, ['folder_a'], self.manager, loader=loader)

    def test_complete_inventory_removes_absent_drive_but_not_local_chunks(self):
        result = self.sync()
        self.assertNotIn('old', self.manager.collection.rows)
        self.assertIn('local', self.manager.collection.rows)
        self.assertEqual(result['chunks_deleted'], 1)

    def test_incomplete_inventory_never_deactivates_chunks(self):
        self.client.error = RuntimeError('incomplete inventory')
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertNotIn('drive_active', self.manager.collection.rows['old'])

    def test_network_failure_does_not_delete(self):
        self.client.folder_error = TimeoutError()
        with self.assertRaises(TimeoutError):
            self.sync()
        self.assertIn('old', self.manager.collection.rows)

    def test_missing_folder_blocks_shared_corpus_only(self):
        self.client.folder_error = HTTPError('fixture', 404, 'missing', {}, None)
        result = self.sync()
        self.assertEqual(result['status'], 'blocked')
        self.assertNotIn('old', self.manager.collection.rows)
        self.assertIn('local', self.manager.collection.rows)

    def test_generic_forbidden_is_not_confused_with_deletion(self):
        self.client.folder_error = HTTPError('fixture', 403, 'quota or access error', {}, None)
        with self.assertRaises(HTTPError):
            self.sync()
        self.assertIn('old', self.manager.collection.rows)

    def test_download_disabled_file_is_removed(self):
        self.client.records = [{'id': 'old_file', 'name': 'guide.txt', 'capabilities': {'canDownload': False}}]
        self.sync()
        self.assertNotIn('old', self.manager.collection.rows)

    def test_cleanup_failure_leaves_tombstone_and_guard_excludes_cached_text(self):
        self.manager.collection.fail_deletes = True
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertIs(self.manager.collection.rows['old']['drive_active'], False)
        self.assertEqual(filter_current_drive_chunks([candidate()], self.manager), [])

    def test_current_documents_are_indexed(self):
        self.client.records = [{'id': 'new_file', 'name': 'guide.txt', 'version': '1'}]
        result = self.sync()
        self.assertEqual(len(result['added']), 1)
        self.assertTrue(any(row.get('drive_file_id') == 'new_file' for row in self.manager.collection.rows.values()))

    def test_deleted_chunk_cannot_survive_in_bm25_cache(self):
        self.manager.delete_by_ids(['old'])
        self.assertEqual(filter_current_drive_chunks([candidate(), candidate('local', 'local')], self.manager), [candidate('local', 'local')])

    def test_availability_read_failure_drops_drive_candidates_only(self):
        self.manager.collection.get = lambda **kwargs: (_ for _ in ()).throw(RuntimeError('storage failure'))
        self.assertEqual(filter_current_drive_chunks([candidate(), candidate('local', 'local')], self.manager), [candidate('local', 'local')])

    def test_local_inventory_excludes_remote_sources(self):
        function = load_function('document_rag/ingestion/incremental.py', '_get_existing_sources',
                                 {'ChromaManager': object, 'Any': object, 'logger': logging.getLogger(__name__), 'urlsplit': urlsplit})
        self.assertEqual(function(self.manager), {'local.txt'})

    def test_local_root_check_rejects_remote_urls(self):
        function = load_function('document_rag/ingestion/incremental.py', '_is_under_roots',
                                 {'Path': Path, 'logger': logging.getLogger(__name__), 'urlsplit': urlsplit,
                                  'DEFAULT_SCAN_ROOT_CANDIDATES': [ROOT]})
        self.assertFalse(function('https://' + 'drive.google.com/file/d/file_a/view', [ROOT]))

    def test_periodic_worker_retries_and_stops(self):
        class Stop:
            waits = 0
            def is_set(self):
                return self.waits >= 2
            def wait(self, interval):
                self.waits += 1
                return self.is_set()
        calls = []
        def action():
            calls.append(True)
            if len(calls) == 1:
                raise TimeoutError()
            return {'status': 'complete'}
        reports = []
        run_periodically(action, 300, reports.append, Stop())
        self.assertEqual([report['status'] for report in reports], ['failed', 'complete'])

    def test_post_expansion_guard_removes_an_inactive_neighbor(self):
        self.manager.collection.rows['neighbor'] = {'origin': 'google_drive', 'drive_file_id': 'old_file', 'drive_active': False}
        returned = filter_current_drive_chunks([candidate('old'), candidate('neighbor')], self.manager)
        self.assertEqual([item['id'] for item in returned], ['old'])


if __name__ == '__main__':
    unittest.main()
