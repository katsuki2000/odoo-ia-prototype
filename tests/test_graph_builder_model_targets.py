"""Model-reference graph construction regressions."""

from types import SimpleNamespace
import unittest

from code_intelligence.graph.builder import OdooGraphBuilder
from code_intelligence.graph.nodes import ParsedModule, ResolvedSymbolRegistry


def declaration(name, inherit=(), inherits=None, fields=()):
    return SimpleNamespace(name=name, inherit=list(inherit), inherits=inherits or {}, fields=list(fields),
                           methods=[], description=None, filepath='models/demo.py')


def relation_field(target, compute=''):
    return SimpleNamespace(name='link_id', field_type='Many2one', comodel_name=target,
                           inverse_name=None, compute=compute, related=None, store=True, string='Link')


def build(declarations):
    registry = ResolvedSymbolRegistry(models=declarations, model_modules={name: ['demo'] * len(items) for name, items in declarations.items()})
    graph = OdooGraphBuilder(registry, {'demo': ParsedModule(manifest=None)}).build_graph()
    return graph, registry


class GraphBuilderModelTargetTests(unittest.TestCase):
    def test_unknown_inheritance_delegation_and_relation_are_not_model_nodes(self):
        graph, registry = build({'demo.item': [declaration('demo.item', inherit=['missing.parent'],
                                                        inherits={'missing.delegate': 'delegate_id'},
                                                        fields=[relation_field('missing.relation')])]})
        for name in ('missing.parent', 'missing.delegate', 'missing.relation'):
            self.assertNotIn('model:' + name, graph)
        self.assertEqual(len(registry.unresolved_references), 3)
        self.assertEqual(graph.graph['integrity_report']['unresolved_reference_count'], 3)
        self.assertTrue(all(item.source_file == 'models/demo.py' for item in registry.unresolved_references))

    def test_later_declared_parent_and_comodel_keep_edges(self):
        graph, registry = build({'demo.item': [declaration('demo.item', inherit=['other.item'], fields=[relation_field('other.item')])],
                                 'other.item': [declaration('other.item')]})
        self.assertTrue(graph.has_edge('model:demo.item', 'model:other.item'))
        self.assertTrue(graph.has_edge('field:demo.item.link_id', 'model:other.item'))
        self.assertEqual(graph.nodes['model:other.item']['node_type'], 'Model')
        self.assertEqual(registry.unresolved_references, [])
        self.assertEqual(graph.graph['integrity_report']['issue_count'], 0)

    def test_in_place_extension_does_not_make_a_self_inheritance_edge(self):
        graph, registry = build({'demo.item': [declaration('demo.item', inherit=['demo.item'])]})
        self.assertFalse(graph.has_edge('model:demo.item', 'model:demo.item'))
        self.assertEqual(graph.nodes['model:demo.item']['inherits_list'], ['demo.item'])
        self.assertEqual(registry.unresolved_references, [])

    def test_remaining_unresolved_compute_method_is_reported_not_invented(self):
        graph, registry = build({'demo.item': [declaration('demo.item', fields=[relation_field('', compute='_compute_link')])]})
        report = graph.graph['integrity_report']
        self.assertEqual(report['counts']['untyped_node'], 1)
        self.assertEqual(report['counts']['unresolved_endpoint'], 1)
        self.assertNotIn('node_type', graph.nodes['method:demo.item._compute_link'])

    def test_repeated_missing_parent_is_deduplicated_by_provenance(self):
        graph, registry = build({'demo.item': [declaration('demo.item', inherit=['missing.item']),
                                               declaration('demo.item', inherit=['missing.item'])]})
        self.assertEqual(len(registry.unresolved_references), 1)
        self.assertNotIn('model:missing.item', graph)


if __name__ == '__main__':
    unittest.main()
