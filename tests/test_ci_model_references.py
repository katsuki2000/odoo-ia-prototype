"""Dependency-free model-reference regression tests."""

import importlib.util
from pathlib import Path
import unittest

modulePath = Path(__file__).resolve().parents[1] / 'code_intelligence/model_references.py'
spec = importlib.util.spec_from_file_location('ci_model_references', modulePath)
references = importlib.util.module_from_spec(spec)
spec.loader.exec_module(references)


class ModelReferenceTests(unittest.TestCase):
    def setUp(self):
        self.index = references.build_model_xmlref_index(['sale.order', 'ir.config_parameter', 'ir.actions.act_window', 'custom.model_data'])

    def test_generated_suffix_preserves_underscores(self):
        self.assertEqual(references.resolve_model_ref('model_ir_config_parameter', self.index), 'ir.config_parameter')

    def test_module_qualified_reference(self):
        self.assertEqual(references.resolve_model_ref('base.model_ir_actions_act_window', self.index), 'ir.actions.act_window')

    def test_known_technical_name(self):
        self.assertEqual(references.resolve_model_ref('sale.order', self.index), 'sale.order')

    def test_technical_name_containing_model_prefix(self):
        self.assertEqual(references.resolve_model_ref('custom.model_data', self.index), 'custom.model_data')

    def test_absent_xml_reference_is_not_guessed(self):
        self.assertIsNone(references.resolve_model_ref('model_unknown_thing', self.index))

    def test_absent_technical_name_is_not_accepted(self):
        self.assertIsNone(references.resolve_model_ref('unknown.thing', self.index))

    def test_colliding_suffix_is_ambiguous(self):
        index = references.build_model_xmlref_index(['a.b_c', 'a_b.c'])
        self.assertIsNone(references.resolve_model_ref('model_a_b_c', index))
        self.assertIsNone(references.resolve_model_ref('demo.model_a_b_c', index))
        self.assertEqual(references.resolve_model_ref('a.b_c', index), 'a.b_c')

    def test_duplicates_do_not_create_false_ambiguity(self):
        index = references.build_model_xmlref_index(['sale.order', 'sale.order'])
        self.assertEqual(references.resolve_model_ref('model_sale_order', index), 'sale.order')

    def test_empty_and_non_string_references(self):
        for value in (None, '', ' ', [], 1):
            with self.subTest(value=value):
                self.assertIsNone(references.resolve_model_ref(value, self.index))

    def test_index_is_deterministic(self):
        names = ['z.item', 'a.b_c', 'a_b.c']
        self.assertEqual(references.build_model_xmlref_index(names), references.build_model_xmlref_index(reversed(names)))

    def test_reference_namespace_collision_is_not_guessed(self):
        index = references.build_model_xmlref_index(['model_a_b', 'a.b'])
        self.assertIsNone(references.resolve_model_ref('model_a_b', index))


if __name__ == '__main__':
    unittest.main()
