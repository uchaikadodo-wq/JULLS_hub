import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

SPEC = importlib.util.spec_from_file_location('reader', Path(__file__).with_name('server.py'))
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)

class FakeAPI:
    base = 'http://127.0.0.1:8080'
    def __init__(self):
        self.paths = []
    def json(self, path, query=None):
        self.paths.append((path, query))
        if path.startswith('pages/'):
            return {'id': 7, 'name': 'Статья', 'html': 'Привет мир', 'markdown': '# Привет'}
        if path == 'attachments/7':
            return {'id': 7, 'name': 'sample.bin', 'extension': 'bin', 'external': False, 'content': base64.b64encode(b'\x00\xffabc').decode()}
        if path == 'attachments/8':
            return {'id': 8, 'name': 'Drive', 'external': True, 'content': 'https://example.test/private'}
        return {'data': [{'id': 7}], 'total': 1}
    def get(self, path, query=None):
        self.paths.append((path, query))
        return b'\x00\xffabc', 'application/octet-stream'

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.server = reader.Server(self.api)

    def request(self, method, params=None, identity=1):
        return self.server.handle({'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params or {}})

    def initialize(self):
        result = self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}})
        self.assertEqual(result['result']['protocolVersion'], '2025-06-18')
        self.assertIsNone(self.server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))

    def test_lifecycle_and_methods(self):
        self.assertIn('error', self.request('tools/list'))
        self.initialize()
        self.assertEqual(len(self.request('tools/list')['result']['tools']), 7)
        self.assertEqual(self.request('ping')['result'], {})
        self.assertEqual(self.request('resources/read')['error']['code'], -32601)
        self.assertIn('error', self.request('initialize'))

    def test_rejects_write_tools_and_argument_escape_without_request(self):
        self.initialize()
        cases = [('delete_page', {'id': 7}), ('http_request', {'method': 'POST', 'path': 'pages'}),
            ('read_page', {'id': '../users'}), ('read_page', {'id': True}),
            ('read_page', {'id': 7, 'url': 'https://example.test'}),
            ('export_content', {'kind': 'users', 'id': 7, 'format': 'zip'}),
            ('export_content', {'kind': 'pages', 'id': 7, 'format': '../users'}),
            ('list_content', {'kind': 'pages', 'count': 101}),
            ('read_attachment', {'id': 7, 'length': 65537})]
        for name, arguments in cases:
            response = self.request('tools/call', {'name': name, 'arguments': arguments})
            self.assertTrue(response['result']['isError'])
        self.assertEqual(self.api.paths, [])

    def test_page_chunks_have_no_loss(self):
        first = self.server.call('read_page', {'id': 7, 'length': 4})
        last = self.server.call('read_page', {'id': 7, 'offset': first['next_offset']})
        self.assertEqual(first['text'] + last['text'], 'Привет мир')
        self.assertIsNone(last['next_offset'])
        self.assertEqual(first['url'], 'http://127.0.0.1:8080/link/7')

    def test_binary_chunks_and_external_link_no_fetch(self):
        first = self.server.call('read_attachment', {'id': 7, 'length': 2})
        chunks = [first] + [self.server.call('read_attachment', {'id': 7, 'offset': n, 'length': 2, 'snapshot': first['snapshot']}) for n in (2, 4)]
        self.assertEqual(b''.join(base64.b64decode(c['data']) for c in chunks), b'\x00\xffabc')
        self.assertIsNone(chunks[-1]['next_offset'])
        self.assertTrue(self.server.call('read_attachment', {'id': 8})['external'])
        self.assertFalse(any('https:' in path for path, _ in self.api.paths))

    def test_snapshot_checks_fresh_permissions_and_cannot_switch_object(self):
        first = self.server.call('export_content', {'kind': 'pages', 'id': 7, 'format': 'zip', 'length': 2})
        args = {'kind': 'pages', 'id': 7, 'format': 'zip', 'offset': 2, 'snapshot': first['snapshot']}
        with patch.object(self.api, 'json', side_effect=reader.SafeError('Access denied')):
            with self.assertRaises(reader.SafeError):
                self.server.call('export_content', args)
        with self.assertRaises(reader.SafeError):
            self.server.call('export_content', dict(args, id=8))
        self.server.snapshot['expires'] = 0
        with self.assertRaises(reader.SafeError):
            self.server.call('export_content', args)

    def test_image_export_and_pagination_dispatch(self):
        for name, args, path in [
            ('search', {'query': 'договоры & кадровые', 'offset': 5}, 'search'),
            ('list_content', {'kind': 'pages', 'offset': 50}, 'pages'),
            ('read_section', {'kind': 'books', 'id': 7}, 'books/7'),
            ('read_image', {'id': 7}, 'image-gallery/7/data'),
            ('export_content', {'kind': 'pages', 'id': 7, 'format': 'zip'}, 'pages/7/export/zip')]:
            self.server.call(name, args)
            self.assertEqual(self.api.paths[-1][0], path)

    def test_credentials_protection_and_invalid_origins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'key.json'
            def write(base):
                path.write_text(json.dumps({'base_url': base, 'token_id': 'syntheticID', 'token_secret': 'syntheticSECRET'}))
                path.chmod(0o600)
            write('http://127.0.0.1:8080')
            self.assertEqual(reader.load_credentials(path)[0], 'http://127.0.0.1:8080')
            path.chmod(0o644)
            with self.assertRaises(reader.SafeError):
                reader.load_credentials(path)
            for origin in ['http://example.test', 'https://example.test/api', 'https://user:pass@example.test', 'https://example.test?token=secret', 'file:///tmp/data']:
                write(origin)
                with self.assertRaises(reader.SafeError):
                    reader.load_credentials(path)
            write('https://example.test')
            linked = Path(directory) / 'linked.json'
            linked.symlink_to(path)
            with self.assertRaises(reader.SafeError):
                reader.load_credentials(linked)

    def test_http_uses_get_fixed_origin_and_refuses_redirects_and_errors(self):
        api = reader.BookStack('http://127.0.0.1:8080', 'syntheticID', 'syntheticSECRET')
        for code in (302, 401, 403, 404, 429, 500):
            api.next_request = 0
            api.opener = Mock()
            api.opener.open.side_effect = urllib.error.HTTPError('http://127.0.0.1:8080', code, 'syntheticSECRET', {}, io.BytesIO(b'syntheticSECRET'))
            with self.assertRaises(reader.SafeError) as context:
                api.get('pages', {'count': 10})
            self.assertNotIn('syntheticSECRET', str(context.exception))
            request = api.opener.open.call_args[0][0]
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.full_url, 'http://127.0.0.1:8080/api/pages?count=10')
        for path in ('../users', 'https://example.test/', '/users', 'pages?x=1'):
            with self.assertRaises(reader.SafeError):
                api.get(path)
        self.assertIsNone(reader.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.test'))

    def test_stdio_subprocess_protocol_and_no_secret_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'key.json'
            path.write_text(json.dumps({'base_url': 'http://127.0.0.1:8080', 'token_id': 'syntheticID', 'token_secret': 'syntheticSECRET'}))
            path.chmod(0o600)
            messages = [
                {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'delete_page', 'arguments': {'id': 7}}},
            ]
            process = subprocess.run([sys.executable, str(Path(reader.__file__)), '--credentials-file', str(path)],
                input='\n'.join(json.dumps(m) for m in messages) + '\n', text=True, capture_output=True, timeout=5)
            self.assertEqual(process.returncode, 0)
            responses = [json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual(len(responses), 3)
            self.assertTrue(responses[-1]['result']['isError'])
            self.assertNotIn('syntheticSECRET', process.stdout + process.stderr)
            self.assertEqual(process.stderr, '')

if __name__ == '__main__':
    unittest.main()
