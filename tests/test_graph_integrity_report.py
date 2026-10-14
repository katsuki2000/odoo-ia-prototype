"""Dependency-free structural graph diagnostics tests."""

import copy
import importlib.util
from pathlib import Path
import unittest

modulePath = Path(__file__).resolve().parents[1] / 'code_intelligence/graph/integrity_report.py'
spec = importlib.util.spec_from_file_location('graph_integrity_report', modulePath)
reports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reports)


class GraphIntegrityReportTests(unittest.TestCase):
    def setUp(self):
        self.payload = {'graph': {'nodes': [{'id': 'model:demo.item', 'node_type': 'Model'},
                                          {'id': 'acl:demo.access', 'node_type': 'AccessEntry'}],
                                  'links': [{'source': 'model:demo.item', 'target': 'acl:demo.access', 'edge_type': 'GRANTED_BY'}]}}

    def test_valid_structure_is_not_a_runtime_certificate(self):
        report = reports.inspect_serialized_graph(self.payload)
        self.assertEqual(report['issue_count'], 0)
        self.assertEqual(report['scope'], 'static_structure')
        self.assertNotIn('runtime_validated', report)

    def test_untyped_target_is_visible(self):
        self.payload['graph']['nodes'][0].pop('node_type')
        report = reports.inspect_serialized_graph(self.payload)
        self.assertEqual(report['counts']['untyped_node'], 1)
        self.assertEqual(report['counts']['unresolved_endpoint'], 1)
        self.assertEqual(report['counts']['acl_without_model'], 1)

    def test_wrong_target_type_is_visible(self):
        self.payload['graph']['nodes'][1]['node_type'] = 'Group'
        self.assertEqual(reports.inspect_serialized_graph(self.payload)['counts']['unresolved_endpoint'], 1)

    def test_missing_node_does_not_get_created(self):
        self.payload['graph']['nodes'].pop(0)
        report = reports.inspect_serialized_graph(self.payload)
        self.assertEqual(report['node_count'], 1)
        self.assertEqual(report['counts']['unresolved_endpoint'], 1)

    def test_acl_without_model(self):
        self.payload['graph']['links'] = []
        self.assertEqual(reports.inspect_serialized_graph(self.payload)['counts']['acl_without_model'], 1)

    def test_untyped_edge(self):
        self.payload['graph']['links'][0].pop('edge_type')
        self.assertEqual(reports.inspect_serialized_graph(self.payload)['counts']['untyped_edge'], 1)

    def test_self_extension_is_reported_as_graph_structure(self):
        self.payload['graph']['links'].append({'source': 'model:demo.item', 'target': 'model:demo.item', 'edge_type': 'EXTENDS'})
        self.assertEqual(reports.inspect_serialized_graph(self.payload)['counts']['self_inheritance'], 1)

    def test_legacy_unwrapped_payload(self):
        self.assertEqual(reports.inspect_serialized_graph(self.payload['graph'])['issue_count'], 0)

    def test_legacy_graph_metadata_is_not_mistaken_for_a_wrapper(self):
        data = self.payload['graph']
        data['graph'] = {'unresolved_references': [{'symbol_ref': 'missing.item'}]}
        report = reports.inspect_serialized_graph(data)
        self.assertEqual(report['unresolved_reference_count'], 1)
        self.assertEqual(report['issue_count'], 0)

    def test_current_edges_key(self):
        data = self.payload['graph']
        data['edges'] = data.pop('links')
        self.assertEqual(reports.inspect_serialized_graph(self.payload)['issue_count'], 0)

    def test_diagnostics_do_not_mutate_the_graph(self):
        before = copy.deepcopy(self.payload)
        reports.inspect_serialized_graph(self.payload)
        self.assertEqual(self.payload, before)

    def test_duplicate_nodes_are_rejected(self):
        self.payload['graph']['nodes'].append(self.payload['graph']['nodes'][0])
        with self.assertRaises(ValueError):
            reports.inspect_serialized_graph(self.payload)

    def test_malformed_node_link_rows_are_rejected(self):
        for data in ({}, {'nodes': [], 'links': None}, {'nodes': [{}], 'links': []},
                     {'nodes': [], 'links': [{}]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                reports.inspect_serialized_graph(data)


if __name__ == '__main__':
    unittest.main()
