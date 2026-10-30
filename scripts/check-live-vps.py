#!/usr/bin/env python3
"""Validate the published VPS using protected credentials; never print passwords or article bodies."""
import http.cookiejar
import importlib.util
import json
from pathlib import Path
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent

def main():
    spec = importlib.util.spec_from_file_location('deploy', ROOT / 'scripts/deploy-vps.py')
    deploy = importlib.util.module_from_spec(spec); spec.loader.exec_module(deploy)
    state = json.loads((deploy.PRIVATE / 'state.json').read_text())
    host = 'base.lookin.team'
    context = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=15) as connection:
        with context.wrap_socket(connection, server_hostname=host) as tls:
            cert = tls.getpeercert()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    checks = []
    def fetch(path, expected=200, headers=None, data=None, client=None):
        request = urllib.request.Request('https://' + host + path, headers=headers or {}, data=data)
        try:
            with (client or opener).open(request, timeout=30) as response:
                code, body, url = response.status, response.read(), response.url
        except urllib.error.HTTPError as error:
            code, body, url = error.code, error.read(), error.url
        if code != expected:
            raise RuntimeError('Unexpected HTTP status; response withheld: ' + path + ' ' + str(code))
        checks.append({'path': path, 'status': code})
        return body, url
    login, final = fetch('/login')
    assert b'name="_token"' in login
    _, target = fetch('/books')
    assert urllib.parse.urlsplit(target).path == '/login'
    fetch('/api/books', 401)
    fetch('/.env', 404)
    fetch('/uploads/test.php', 404)
    try:
        with opener.open('http://' + host + '/login', timeout=20) as response:
            assert response.url.startswith('https://' + host + '/')
    except urllib.error.HTTPError as redirect:
        # Python 3.9 does not automatically follow HTTP 308.
        assert redirect.code == 308 and redirect.headers['Location'] == 'https://' + host + '/login'
    jar = http.cookiejar.CookieJar()
    browser = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
    login, _ = fetch('/login', client=browser)
    token = re.search(r'name="_token"\s+value="([^"]+)"', login.decode()).group(1)
    form = urllib.parse.urlencode({'email':state['admin_email'], 'password':state['admin_password'], '_token':token}).encode()
    home, home_url = fetch('/login', data=form, client=browser)
    assert urllib.parse.urlsplit(home_url).path != '/login'
    assert 'Lookin.Team Base' in home.decode()
    assert any(cookie.secure for cookie in jar if cookie.name == 'lookin_base_session')
    fetch('/books', client=browser)
    fetch('/user/local-administrator', client=browser)
    fetch('/search?term=%D0%94%D0%BE%D0%B4%D0%BE', client=browser)
    fetch('/licenses', client=browser)
    css, _ = fetch('/theme/lookin-base/lookin.css', client=browser)
    assert b'Prata' in css
    font, _ = fetch('/theme/lookin-base/fonts/Prata-Regular.ttf', client=browser)
    assert len(font) > 90000
    script = r'''<?php
require '/app/vendor/autoload.php'; $app=require '/app/bootstrap/app.php'; $app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$user=BookStack\Users\Models\User::where('email','pilot-reader@agents.example.test')->firstOrFail();
$secret=bin2hex(random_bytes(24));$token=(new BookStack\Api\ApiToken)->forceFill(['user_id'=>$user->id,'name'=>'Temporary VPS deployment validation','token_id'=>bin2hex(random_bytes(16)),'secret'=>Illuminate\Support\Facades\Hash::make($secret),'expires_at'=>now()->addDay()->format('Y-m-d')]);$token->save();
echo json_encode(['id'=>$token->id,'token_id'=>$token->token_id,'secret'=>$secret]);
'''
    credential = json.loads(deploy.remote(deploy.cp_command('exec -T app php'), data=script, capture=True).stdout)
    try:
        headers = {'Authorization':'Token ' + credential['token_id'] + ':' + credential['secret']}
        books, _ = fetch('/api/books', headers=headers)
        pages, _ = fetch('/api/pages', headers=headers)
        books, pages = json.loads(books), json.loads(pages)
        for page in pages['data']:
            body, _ = fetch('/api/pages/' + str(page['id']), headers=headers)
            assert json.loads(body)['id'] == page['id']
        fetch('/api/users', 403, headers=headers)
        fetch('/api/roles', 403, headers=headers)
        assert books['total'] == 1 and pages['total'] == 2
    finally:
        code = r'''<?php
require '/app/vendor/autoload.php'; $app=require '/app/bootstrap/app.php'; $app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
BookStack\Api\ApiToken::where('id',TOKEN_ID)->where('name','Temporary VPS deployment validation')->delete();
'''.replace('TOKEN_ID',str(int(credential['id'])))
        deploy.remote(deploy.cp_command('exec -T app php'), data=code, capture=True)
    fetch('/api/books', 401, headers=headers)
    ports = {}
    for port in [3306, 8080, 9000, 2019]:
        try:
            with socket.create_connection((deploy.VPS.HOST,port),timeout=2):
                ports[str(port)] = 'unexpectedly open'
        except (TimeoutError, ConnectionRefusedError, socket.timeout):
            ports[str(port)] = 'not reachable from this Mac'
    assert all(v != 'unexpectedly open' for v in ports.values())
    report={'date':'2026-10-30','url':'https://'+host,'result':'PASS',
        'tls_verified':True,'certificate_expires':cert['notAfter'],
        'http_redirects_to_https':True,'admin_login_and_secure_cookie':'PASS',
        'homepage_profile_search_fonts':'PASS','api_reader_can_read':'PASS',
        'api_administration_denied':'PASS','temporary_validation_token_revoked':True,
        'published_books':books['total'],'published_pages':pages['total'],
        'private_ports':ports,'checks':checks,'content_and_credentials_not_recorded':True,
        'live_write_tests':'not performed on real articles; tested on isolated release copy'}
    (ROOT/'local-dev/vps-deployment-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
