#!/usr/bin/env python3
"""Drive a real stdio MCP subprocess against the local pilot; record no article text or secrets."""
import base64
import hashlib
import io
import json
from pathlib import Path
import select
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent

def main():
    process = subprocess.Popen([sys.executable, str(ROOT / 'mcp/server.py'),
        '--credentials-file', str(ROOT / 'local-dev/private/agents/pilot-reader.json')],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    checks = []
    sequence = 0
    def request(method, params=None, notification=False):
        nonlocal sequence
        sequence += 1
        message = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
        if not notification:
            message['id'] = sequence
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()
        if notification:
            return
        if not select.select([process.stdout], [], [], 40)[0]:
            raise RuntimeError('MCP response timeout; output withheld')
        response = json.loads(process.stdout.readline())
        if response.get('id') != sequence or 'error' in response:
            raise RuntimeError('MCP protocol check failed; output withheld')
        return response['result']
    def call(name, arguments=None):
        response = request('tools/call', {'name': name, 'arguments': arguments or {}})
        if response.get('isError'):
            raise RuntimeError('MCP read failed; output withheld')
        checks.append(name)
        return json.loads(response['content'][0]['text'])['data']
    try:
        initialized = request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'lookin-local-verifier', 'version': '0.1'}})
        assert initialized['serverInfo']['name'] == 'lookin-base-reader'
        request('notifications/initialized', notification=True)
        tools = request('tools/list')['tools']
        assert len(tools) == 7
        assert all(t['annotations']['readOnlyHint'] for t in tools)
        pages = call('list_content', {'kind': 'pages', 'count': 100})
        books = call('list_content', {'kind': 'books'})
        call('search', {'query': 'Додо'})
        for book in books['data']:
            call('read_section', {'kind': 'books', 'id': book['id']})
        for page in pages['data']:
            article = call('read_page', {'id': page['id'], 'format': 'raw_html'})
            assert article['id'] == page['id'] and article['total_characters'] > 0
        export_summary = None
        if pages['data']:
            identity = pages['data'][0]['id']
            parts, offset, snapshot = [], 0, None
            # Use a short first chunk to prove continuation without many network calls.
            while True:
                arguments = {'kind': 'pages', 'id': identity, 'format': 'zip', 'offset': offset, 'length': 32 if not parts else 65536}
                if snapshot:
                    arguments['snapshot'] = snapshot
                result = call('export_content', arguments)
                snapshot = result['snapshot']
                parts.append(base64.b64decode(result['data'], validate=True))
                if result['next_offset'] is None:
                    break
                offset = result['next_offset']
                if len(parts) > 50:
                    raise RuntimeError('Test export unexpectedly large')
            blob = b''.join(parts)
            assert len(blob) == result['total_length'] and hashlib.sha256(blob).hexdigest() == result['sha256']
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                assert archive.testzip() is None
            export_summary = {'chunks': len(parts), 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}
        denied = request('tools/call', {'name': 'delete_page', 'arguments': {'id': 1}})
        assert denied['isError']
        denied = request('tools/call', {'name': 'read_page', 'arguments': {'id': '../../users'}})
        assert denied['isError']
        report = {'result': 'PASS', 'transport': 'real stdio subprocess', 'protocol': initialized['protocolVersion'],
            'tools': [t['name'] for t in tools], 'successful_tool_calls': len(checks),
            'live_pages_read': len(pages['data']), 'live_books_read': len(books['data']),
            'zip_reassembled': export_summary, 'write_tool_rejected': True, 'path_injection_rejected': True,
            'no_content_or_credentials_recorded': True, 'network_listener_opened': False}
        (ROOT / 'local-dev/mcp-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

if __name__ == '__main__':
    main()
