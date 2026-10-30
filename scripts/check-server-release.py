#!/usr/bin/env python3
"""Render the production configuration, then test an isolated amd64 copy on loopback only."""
import base64
import datetime
import http.cookiejar
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent

def main():
    os.umask(0o077)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = ROOT / 'local-dev/private/server-preparation-2026-10-30' / ('run-' + stamp)
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    password, root_password = secrets.token_hex(24), secrets.token_hex(24)
    (target / 'db-password').write_text(password)
    (target / 'db-root-password').write_text(root_password)
    env = (ROOT / 'server/app.env.example').read_text().replace('__PRESERVE_EXISTING_APP_KEY_WHEN_RESTORING__', 'base64:' + base64.b64encode(secrets.token_bytes(32)).decode())
    env = env.replace('__NEW_SERVER_DB_PASSWORD_MATCHING_SECRET_FILE__', password).replace('__SET_SENDER_EMAIL__', 'release@example.test')
    env = env.replace('APP_URL=https://base.lookin.team', 'APP_URL=http://127.0.0.1:8082').replace('SESSION_SECURE_COOKIE=true', 'SESSION_SECURE_COOKIE=false')
    (target / 'app.env').write_text(env)
    compose_env = (ROOT / 'server/deploy.env.example').read_text().replace('__SET_OPERATIONS_EMAIL__', 'release@example.test')
    compose_env = compose_env.replace('/opt/lookin-base/secrets/app.env', str(target / 'app.env')).replace('/opt/lookin-base/secrets/db-password', str(target / 'db-password')).replace('/opt/lookin-base/secrets/db-root-password', str(target / 'db-root-password'))
    (target / 'compose.env').write_text(compose_env)
    def command(args, **kwargs):
        return subprocess.run(args, cwd=ROOT, check=True, text=True, **kwargs)
    production = json.loads(command(['docker', 'compose', '--env-file', str(target / 'compose.env'), '-f', 'server/compose.yaml', 'config', '--format', 'json'], capture_output=True).stdout)
    services = production['services']
    assert set(services) == {'app', 'db', 'web'}
    assert not services['app'].get('ports') and not services['db'].get('ports')
    assert {int(p['published']) for p in services['web']['ports']} == {80, 443}
    assert all(p['target'] == int(p['published']) for p in services['web']['ports'])
    assert all(s['read_only'] and s['restart'] == 'unless-stopped' for s in services.values())
    assert all(v['type'] == 'volume' for s in services.values() for v in s.get('volumes', []))
    assert production['networks']['database']['internal'] and production['networks']['application']['internal']
    assert services['app']['environment']['APP_ENV'] == 'production'
    assert services['app']['environment']['APP_DEBUG'] == 'false'
    assert 'ingress' not in services['app']['networks'] and 'ingress' not in services['db']['networks']
    # Never start the rendered production publications during a local check.
    project = 'lookin-release-check-' + stamp.lower()
    production['name'] = project
    for item in production['networks'].values():
        item.pop('name', None)
    for item in production['volumes'].values():
        item.pop('name', None)
    for service in services.values():
        service.pop('build', None)
        service['platform'] = 'linux/amd64'
    services['web']['ports'] = [{'host_ip': '127.0.0.1', 'published': '8082', 'target': 80, 'protocol': 'tcp'}]
    services['web']['environment']['SITE_ADDRESS'] = 'http://:80'
    config = target / 'compose.verify.json'
    config.write_text(json.dumps(production))
    compose = ['docker', 'compose', '-p', project, '-f', str(config)]
    log = (target / 'operations.log').open('a')
    def run(*args, **kwargs):
        kwargs.setdefault('stderr', log)
        if 'capture_output' not in kwargs:
            kwargs.setdefault('stdout', log)
        return command(compose + list(args), **kwargs)
    def php(script):
        result = run('exec', '-T', 'app', 'php', input=script, stdout=subprocess.PIPE)
        return result.stdout
    report = {'date': '2026-10-30', 'project': project, 'production_static_checks': 'PASS',
        'architecture_tested': 'linux/amd64 under Docker Desktop emulation', 'vps_untouched': True}
    try:
        run('up', '-d', '--wait', 'db', 'app')
        run('exec', '-T', 'app', 'php', 'artisan', 'migrate', '--force')
        fixture_output = php((ROOT / 'server/tests/fixtures.php').read_text())
        (target / 'fixture-output.log').write_text(fixture_output)
        fixture = json.loads(fixture_output)
        run('exec', '-T', 'app', 'php', '/opt/lookin/release-check.php')
        # A restricted read-only filesystem must not carry credentials/build dependencies.
        run('exec', '-T', 'app', 'sh', '-ec', 'test ! -e /app/.env; test ! -e /app/node_modules; test ! -e /app/vendor/bin/phpunit; test ! -e /app/local-dev/private; test ! -e /app/.git; test ! -w /app/app; test -w /app/storage')
        run('exec', '-T', 'app', 'php', '-r', 'require "/app/vendor/autoload.php"; try {new Symfony\\Component\\Mime\\Header\\ParameterizedHeader("Content-Type", "text/plain", ["bad\\r\\nHeader"=>"value"]); exit(1);} catch (Symfony\\Component\\Mime\\Exception\\RfcComplianceException $e) {echo "MIME header protection PASS\\n";}')
        run('up', '-d', 'web')
        base = 'http://127.0.0.1:8082'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def fetch(path, status=200, data=None, headers=None, client=None, method=None):
            request = urllib.request.Request(base + path, data=data, headers=headers or {}, method=method)
            try:
                with (client or opener).open(request, timeout=30) as response:
                    actual, body = response.status, response.read()
            except urllib.error.HTTPError as error:
                actual, body = error.code, error.read()
            if actual != status:
                raise RuntimeError(f'Unexpected status at {path}: {actual}; response withheld')
            return body
        for attempt in range(30):
            try:
                login = fetch('/login').decode()
                assert 'name="_token"' in login
                break
            except (OSError, AssertionError, RuntimeError):
                time.sleep(1)
        else:
            raise RuntimeError('Release HTTP readiness failed')
        fetch('/.env', 404)
        fetch('/uploads/anything.php', 404)
        auth = {'Authorization': 'Token ' + fixture['token_id'] + ':' + fixture['token_secret'], 'Content-Type': 'application/json'}
        data = json.loads(fetch('/api/pages/' + str(fixture['page_id']), headers=auth))
        assert 'Синтетические данные' in data['raw_html']
        attachment = json.loads(fetch('/api/attachments/' + str(fixture['attachment_id']), headers=auth))
        assert base64.b64decode(attachment['content']) == b'Lookin release synthetic attachment\n'
        for format_name in ('html', 'plaintext', 'markdown', 'zip'):
            export = fetch(f"/api/pages/{fixture['page_id']}/export/{format_name}", headers=auth)
            assert export
            if format_name == 'zip':
                with zipfile.ZipFile(io.BytesIO(export)) as archive:
                    assert archive.testzip() is None
        fetch('/api/books', 401)
        for path in ('users', 'roles'):
            fetch('/api/' + path, 403, headers=auth)
        for method, path, payload in [
            ('POST', '/api/pages', {'book_id': fixture['book_id'], 'name': 'Forbidden', 'html': '<p>Forbidden</p>'}),
            ('PUT', '/api/pages/' + str(fixture['page_id']), {'name': 'Forbidden'}),
            ('DELETE', '/api/pages/' + str(fixture['page_id']), {})]:
            fetch(path, 403, data=json.dumps(payload).encode(), headers=auth, method=method)
        jar = http.cookiejar.CookieJar()
        browser = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
        login = fetch('/login', client=browser).decode()
        csrf = re.search(r'name="_token"\s+value="([^"]+)"', login).group(1)
        form = urllib.parse.urlencode({'email': fixture['admin_email'], 'password': fixture['admin_password'], '_token': csrf}).encode()
        homepage = fetch('/login', data=form, client=browser).decode()
        assert 'Lookin.Team Base' in homepage
        fetch('/books', client=browser)
        fetch('/search?term=test', client=browser)
        fetch('/licenses', client=browser)
        theme = fetch('/theme/lookin-base/lookin.css', client=browser)
        assert b'Prata' in theme
        # Simulate a code-container replacement: database and uploads must persist.
        run('up', '-d', '--force-recreate', 'app')
        for attempt in range(20):
            try:
                assert 'Синтетические данные' in json.loads(fetch('/api/pages/' + str(fixture['page_id']), headers=auth))['raw_html']
                break
            except (OSError, AssertionError, RuntimeError):
                time.sleep(1)
        else:
            raise RuntimeError('Application did not recover after container replacement')
        attachment = json.loads(fetch('/api/attachments/' + str(fixture['attachment_id']), headers=auth))
        assert base64.b64decode(attachment['content']) == b'Lookin release synthetic attachment\n'
        report.update(result='PASS', migrations='PASS', php_fpm_caddy_http='PASS',
            private_access='PASS', login_theme_search='PASS', api_reader_no_write='PASS',
            original_attachment_download='PASS', article_exports='PASS',
            persistence_after_app_replacement='PASS', mime_header_protection='PASS',
            no_credentials_in_images='PASS', local_web_port='127.0.0.1:8082 only')
        (ROOT / 'local-dev/server-release-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        # Preserve test data for review; never delete or touch the working project's volumes.
        run('down')
        log.close()

if __name__ == '__main__':
    main()
