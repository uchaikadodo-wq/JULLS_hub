#!/usr/bin/env python3
"""Check pilot readers over HTTPS. Keep credentials/content out of output and Git."""
import html
import http.cookiejar
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT.parent/'.server-access/colleagues'
BASE = 'https://base.lookin.team'
PAGE = '/books/iuridiceskoe/page/dogovora-arendy-dodo-picca'

def fetch(client, path, expected=200, data=None):
    # BookStack redirects HTML permission failures to the homepage. JSON requests
    # expose the actual 403, so a followed redirect cannot hide the denial result.
    headers = {'Accept':'application/json'} if expected == 403 else {}
    request = urllib.request.Request(BASE+path, data=data, headers=headers)
    try:
        with client.open(request, timeout=25) as response:
            code, body, url = response.status, response.read(2*1024*1024), response.url
    except urllib.error.HTTPError as error:
        code, body, url = error.code, error.read(2*1024*1024), error.url
    if code != expected:
        raise RuntimeError('Access check failed: '+path+' status '+str(code))
    return body, url

def token(body):
    return html.unescape(re.search(r'name="_token"\s+value="([^"]+)"', body.decode()).group(1))

def main():
    people = json.loads((PRIVATE/'pilot-20261030.json').read_text())['people']
    results = []
    for person in people:
        jar = http.cookiejar.CookieJar()
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
        signed_in = False
        try:
            body, _ = fetch(client, '/login')
            form = urllib.parse.urlencode({'_token':token(body),'email':person['email'],'password':person['password']}).encode()
            body, url = fetch(client, '/login', data=form)
            if urllib.parse.urlsplit(url).path == '/login':
                raise RuntimeError('Login failed; account data withheld')
            signed_in = True
            fetch(client, '/books')
            fetch(client, '/search?term='+urllib.parse.quote('Додо'))
            fetch(client, PAGE)
            fetch(client, PAGE+'/export/plaintext')
            for path in ['/create-book', '/books/iuridiceskoe/edit', PAGE+'/edit', PAGE+'/delete',
                         PAGE+'/permissions', '/settings/users', '/settings/roles']:
                fetch(client, path, 403)
            results.append({'login':'PASS','published_content_search_export':'PASS',
                            'create_edit_delete_permissions_and_admin_forms_denied':'PASS'})
        finally:
            if signed_in:
                body, _ = fetch(client, '/')
                fetch(client, '/logout', data=urllib.parse.urlencode({'_token':token(body)}).encode())
    report = {'result':'PASS','accounts_checked':len(results),'checks':results,
              'real_content_write_requests_performed':False,'api_tokens_issued':False,'emails_sent':False}
    (PRIVATE/'web-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    main()
