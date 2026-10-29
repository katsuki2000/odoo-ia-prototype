"""Dependency-free checks for the public error boundary."""

import errno
import importlib.util
from pathlib import Path
import sys
import unittest
from xmlrpc.client import Fault, ProtocolError

module_path = Path(__file__).resolve().parents[1] / 'api/public_errors.py'
spec = importlib.util.spec_from_file_location('api_public_errors', module_path)
errors = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = errors
spec.loader.exec_module(errors)


class PublicErrorTests(unittest.TestCase):
    def test_private_exception_text_is_not_returned(self):
        private_text = 'password=private-token https://private-host/secret /private/path'
        self.assertEqual(errors.public_error_details(ValueError(private_text)), (500, 'Internal server error.'))

    def test_message_keywords_do_not_determine_status(self):
        for text in ('timeout', 'connection', 'xmlrpc', 'connection validation failed'):
            with self.subTest(text=text):
                self.assertEqual(errors.public_error_details(ValueError(text))[0], 500)

    def test_timeout_is_service_unavailable(self):
        self.assertEqual(errors.public_error_details(TimeoutError('private-host')), (503, 'Service temporarily unavailable.'))

    def test_connection_error_is_service_unavailable(self):
        self.assertEqual(errors.public_error_details(ConnectionError('private-token'))[0], 503)

    def test_network_os_errors_are_service_unavailable(self):
        for error_number in (errno.ECONNREFUSED, errno.ECONNRESET, errno.ETIMEDOUT, errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EPIPE):
            with self.subTest(error_number=error_number):
                self.assertEqual(errors.public_error_details(OSError(error_number, 'private-host'))[0], 503)

    def test_local_filesystem_errors_are_internal_errors(self):
        self.assertEqual(errors.public_error_details(FileNotFoundError('/private/path'))[0], 500)
        self.assertEqual(errors.public_error_details(PermissionError('/private/path'))[0], 500)

    def test_xmlrpc_unavailable_is_sanitized(self):
        for status_code in (429, 500, 502, 503):
            with self.subTest(status_code=status_code):
                self.assertEqual(errors.public_error_details(ProtocolError('private-host', status_code, 'private-token', {})), (503, 'Service temporarily unavailable.'))

    def test_xmlrpc_application_fault_is_not_assumed_to_be_an_outage(self):
        self.assertEqual(errors.public_error_details(Fault(1, 'AccessError: private-token'))[0], 500)

    def test_xmlrpc_client_error_is_not_assumed_to_be_an_outage(self):
        self.assertEqual(errors.public_error_details(ProtocolError('private-host', 403, 'private-token', {}))[0], 500)

    def test_explicit_causal_chain_is_followed(self):
        wrapper = RuntimeError('private-token')
        wrapper.__cause__ = TimeoutError('private-host')
        self.assertEqual(errors.public_error_details(wrapper)[0], 503)

    def test_implicit_causal_chain_is_followed(self):
        wrapper = RuntimeError('private-token')
        wrapper.__context__ = ConnectionError('private-host')
        self.assertEqual(errors.public_error_details(wrapper)[0], 503)

    def test_suppressed_context_is_not_used(self):
        wrapper = RuntimeError('private-token')
        wrapper.__context__ = ConnectionError('private-host')
        wrapper.__suppress_context__ = True
        self.assertEqual(errors.public_error_details(wrapper)[0], 500)

    def test_causal_cycle_terminates(self):
        first = RuntimeError('private-token')
        second = ValueError('private-host')
        first.__cause__, second.__cause__ = second, first
        self.assertEqual(errors.public_error_details(first)[0], 500)

    def test_sanitization_does_not_format_the_exception(self):
        class UnprintableError(Exception):
            def __str__(self):
                raise AssertionError('Private exception text must not be formatted')
        self.assertEqual(errors.public_error_details(UnprintableError())[0], 500)


if __name__ == '__main__':
    unittest.main()
