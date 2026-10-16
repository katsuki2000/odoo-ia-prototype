"""Graph regressions for indexed model targets and unresolved references."""

from types import SimpleNamespace
import unittest
import networkx as nx

from code_intelligence.graph.nodes import ParsedModule, ResolvedSymbolRegistry, add_security_group_nodes, add_menu_nodes
from code_intelligence.agent.tool_helpers import find_server_action_nodes


def make_acl(reference):
    return SimpleNamespace(xml_id='access_demo', name='Demo', filepath='security/ir.model.access.csv',
                           model_id=reference, group_id=None, all_authenticated=True,
                           perm_read=True, perm_write=False, perm_create=False, perm_unlink=False)


def make_action(reference):
    return SimpleNamespace(name='Demo action', filepath='data/actions.xml', model_id=reference,
                           state='code', code='records.check_access()')


def make_menu(action):
    return SimpleNamespace(xml_id='menu_demo', name='Demo', filepath='views/menu.xml', action=action,
                           groups=[], parent='', sequence=1)


class ModelGraphReferenceTests(unittest.TestCase):
    def setUp(self):
        self.graph = nx.DiGraph()
        self.registry = ResolvedSymbolRegistry(models={'ir.config_parameter': []})
        self.graph.add_node('model:ir.config_parameter', node_type='Model', name='ir.config_parameter')
        self.module = ParsedModule(manifest=None)
        self.modules = {'demo': self.module}

    def build_security(self):
        add_security_group_nodes(self.graph, self.registry, self.modules, lambda domain: False)

    def test_acl_underscore_target_has_no_dotted_phantom(self):
        self.module.acl_entries = [make_acl('base.model_ir_config_parameter')]
        self.build_security()
        self.assertTrue(self.graph.has_edge('model:ir.config_parameter', 'acl:demo.access_demo'))
        self.assertNotIn('model:ir.config.parameter', self.graph)
        self.assertEqual(self.registry.unresolved_references, [])

    def test_rule_uses_the_same_index(self):
        rule = SimpleNamespace(name='Demo rule', filepath='security/rules.xml', lineno=1,
                               model_id='model_ir_config_parameter', domain_force='[]', groups_id=[],
                               perm_read=True, perm_write=True, perm_create=True, perm_unlink=True)
        self.registry.rules = {'demo.rule_demo': rule}
        self.build_security()
        self.assertTrue(self.graph.has_edge('model:ir.config_parameter', 'rule:demo.rule_demo'))
        self.assertNotIn('model:ir.config.parameter', self.graph)

    def test_actions_and_automations_store_resolved_targets(self):
        self.registry.server_actions = {'demo.action_demo': make_action('model_ir_config_parameter')}
        self.registry.base_automations = {'demo.automation_demo': SimpleNamespace(
            name='Demo automation', filepath='data/automations.xml', model_id='model_ir_config_parameter',
            trigger='on_write', action_server_ids=[])}
        self.build_security()
        self.assertEqual(self.graph.nodes['server_action:demo.action_demo']['target_model'], 'ir.config_parameter')
        self.assertEqual(self.graph.nodes['automation:demo.automation_demo']['target_model'], 'ir.config_parameter')
        self.assertEqual(len(find_server_action_nodes(self.graph, 'ir.config_parameter')), 1)

    def test_unknown_acl_reference_is_recorded_without_a_model_node(self):
        self.module.acl_entries = [make_acl('model_unknown_thing')]
        self.build_security()
        self.assertNotIn('model:unknown.thing', self.graph)
        self.assertNotIn('model:None', self.graph)
        self.assertEqual(len(self.registry.unresolved_references), 1)
        self.assertEqual(self.registry.unresolved_references[0].symbol_ref, 'model_unknown_thing')
        self.assertEqual(self.registry.unresolved_references[0].source_file, 'security/ir.model.access.csv')

    def test_empty_acl_reference_does_not_create_an_empty_model(self):
        self.module.acl_entries = [make_acl('')]
        self.build_security()
        self.assertNotIn('model:', self.graph)
        self.assertNotIn('model:None', self.graph)

    def test_ambiguous_action_is_not_reinferred_by_the_query_helper(self):
        self.registry.models.update({'a.b_c': [], 'a_b.c': [], 'a.b.c': []})
        for modelName in ('a.b_c', 'a_b.c', 'a.b.c'):
            self.graph.add_node('model:' + modelName, node_type='Model', name=modelName)
        self.registry.server_actions = {'demo.action_demo': make_action('model_a_b_c')}
        self.build_security()
        self.assertEqual(self.graph.nodes['server_action:demo.action_demo']['target_model'], '')
        self.assertEqual(find_server_action_nodes(self.graph, 'a.b.c'), [])
        self.assertEqual(len(self.registry.unresolved_references), 1)

    def test_menu_server_action_preserves_model_underscores(self):
        self.registry.server_actions = {'demo.action_demo': make_action('model_ir_config_parameter')}
        self.module.menuitems = [make_menu('action_demo')]
        add_menu_nodes(self.graph, self.registry, self.modules)
        self.assertTrue(self.graph.has_edge('menu:demo.menu_demo', 'model:ir.config_parameter'))
        self.assertNotIn('model:ir.config.parameter', self.graph)

    def test_unknown_window_action_target_does_not_create_a_phantom(self):
        self.registry.actions = {'demo.action_demo': SimpleNamespace(res_model='missing.item', name='Demo', domain='[]', action_type='act_window', tag='')}
        self.module.menuitems = [make_menu('action_demo')]
        add_menu_nodes(self.graph, self.registry, self.modules)
        self.assertNotIn('model:missing.item', self.graph)
        self.assertEqual(len(self.registry.unresolved_references), 1)

    def test_cache_refreshes_after_same_size_key_replacement(self):
        self.assertEqual(self.registry.resolve_model_ref('model_ir_config_parameter'), 'ir.config_parameter')
        del self.registry.models['ir.config_parameter']
        self.registry.models['new.model_name'] = []
        self.assertIsNone(self.registry.resolve_model_ref('model_ir_config_parameter'))
        self.assertEqual(self.registry.resolve_model_ref('model_new_model_name'), 'new.model_name')

    def test_unresolved_diagnostics_are_not_duplicated(self):
        for _ in range(2):
            self.registry.resolve_model_ref_or_record('model_missing', 'demo', 'data/actions.xml')
        self.assertEqual(len(self.registry.unresolved_references), 1)

    def test_unrelated_edge_is_not_a_server_action_target(self):
        self.graph.add_node('server_action:demo.action_demo', node_type='ServerAction', model_id='model_ir_config_parameter')
        self.graph.add_edge('server_action:demo.action_demo', 'model:ir.config_parameter', edge_type='UNRELATED')
        self.assertEqual(find_server_action_nodes(self.graph, 'ir.config_parameter'), [])


if __name__ == '__main__':
    unittest.main()
