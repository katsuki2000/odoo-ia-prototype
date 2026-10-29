"""Structural guards; these do not replace FastAPI integration tests."""

import ast
from pathlib import Path
import unittest

root_path = Path(__file__).resolve().parents[1]


def load_tree(relative_path):
    return ast.parse((root_path / relative_path).read_text(encoding='utf-8'))


def find_function(tree, function_name):
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name)


class ErrorRouteStructureTests(unittest.TestCase):
    def test_detailed_health_requires_administrator(self):
        function = find_function(load_tree('api/routes_system.py'), 'health_check_v1')
        decorator = function.decorator_list[0]
        dependencies = next(keyword.value for keyword in decorator.keywords if keyword.arg == 'dependencies')
        self.assertIsInstance(dependencies, ast.List)
        self.assertEqual(len(dependencies.elts), 1)
        dependency = dependencies.elts[0]
        self.assertEqual(dependency.func.id, 'Depends')
        self.assertEqual(dependency.args[0].id, 'require_admin')

    def test_public_liveness_does_not_check_private_services(self):
        function = find_function(load_tree('api/routes_system.py'), 'health_check')
        self.assertFalse(any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(function)))
        self.assertFalse(any(keyword.arg == 'dependencies' for keyword in function.decorator_list[0].keywords))
        self.assertEqual(ast.literal_eval(function.body[-1].value), {'status': 'ok', 'service': 'miro-rag-api'})

    def test_detailed_health_does_not_expose_llm_endpoint(self):
        function = find_function(load_tree('api/routes_system.py'), 'health_check_v1')
        self.assertNotIn('LLM_BASE_URL', ast.unparse(function))
        self.assertNotIn('local endpoint:', ast.unparse(function))
        self.assertIn('not checked', ast.unparse(function))

    def test_unexpected_failures_use_common_error_boundary(self):
        functions = [('api/routes_ask.py', '_answer_question')]
        for relative_path, function_name in functions:
            with self.subTest(function_name=function_name):
                function = find_function(load_tree(relative_path), function_name)
                handlers = [node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name) and node.type.id == 'Exception']
                self.assertEqual(len(handlers), 1)
                handler = handlers[0]
                self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'public_error_details' for node in ast.walk(handler)))
                raise_node = handler.body[-1]
                self.assertIsInstance(raise_node, ast.Raise)
                self.assertIsInstance(raise_node.cause, ast.Constant)
                self.assertIsNone(raise_node.cause.value)
                detail_node = next(keyword.value for keyword in raise_node.exc.keywords if keyword.arg == 'detail')
                self.assertIsInstance(detail_node, ast.Name)
                self.assertEqual(detail_node.id, 'detail')
                self.assertFalse(any(isinstance(node, ast.JoinedStr) for node in ast.walk(handler)))

    def test_question_validation_http_exceptions_are_preserved(self):
        function = find_function(load_tree('api/routes_ask.py'), '_answer_question')
        handler = next(node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name) and node.type.id == 'HTTPException')
        self.assertEqual(len(handler.body), 1)
        self.assertIsInstance(handler.body[0], ast.Raise)
        self.assertIsNone(handler.body[0].exc)


if __name__ == '__main__':
    unittest.main()
