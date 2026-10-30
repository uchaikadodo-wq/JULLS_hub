#!/usr/bin/env python3
"""Read-only HTTP smoke check of the local pilot. Never prints tokens or content."""
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def main():
    credentials = json.loads((ROOT / 'local-dev/private/agents/pilot-reader.json').read_text())
    base = credentials['base_url']
    if base != 'http://127.0.0.1:8080':
        raise SystemExit('Only reviewed local pilot is supported')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    results = []
    def get(path, expected=200, authenticated=True):
        headers = {'Accept': 'application/json'}
        if authenticated:
            headers['Authorization'] = 'Token ' + credentials['token_id'] + ':' + credentials['token_secret']
        request = urllib.request.Request(base + '/api/' + path, headers=headers, method='GET')
        try:
            with opener.open(request, timeout=30) as response:
                code, data = response.status, response.read()
        except urllib.error.HTTPError as error:
            code, data = error.code, error.read()
        if code != expected:
            raise RuntimeError(f'{path}: expected HTTP {expected}, received {code}; response withheld')
        results.append({'endpoint': path, 'status': code, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        return data
    def listing(kind):
        offset = 0
        rows = []
        while True:
            result = json.loads(get(f'{kind}?count=100&offset={offset}'))
            rows.extend(result['data'])
            offset += len(result['data'])
            if offset >= result['total']:
                return rows
            if not result['data']:
                raise RuntimeError('Pagination stalled')
    counts = {}
    for kind in ['shelves', 'books', 'chapters', 'pages', 'attachments', 'image-gallery']:
        rows = listing(kind)
        counts[kind] = len(rows)
        for row in rows:
            get(f"{kind}/{row['id']}")
            if kind == 'pages':
                for format_name in ['plaintext', 'markdown', 'html', 'zip']:
                    get(f"pages/{row['id']}/export/{format_name}")
    get('search?query=%D0%94%D0%BE%D0%B4%D0%BE')
    get('books', expected=401, authenticated=False)
    for kind in ['users', 'roles', 'audit-log', 'recycle-bin']:
        get(kind, expected=403)
    report = {'result': 'PASS', 'local_only': True, 'read_only_requests': True,
              'counts': counts, 'checks': results, 'no_content_or_credentials_recorded': True}
    destination = ROOT / 'local-dev/private/agent-access-2026-10-29/http-reader-check.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    destination.chmod(0o600)
    print(json.dumps({'result': 'PASS', 'http_checks': len(results), 'counts': counts}, indent=2))

if __name__ == '__main__':
    main()
