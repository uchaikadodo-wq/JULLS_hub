#!/usr/bin/env python3
"""Verify a local backup in a new directory/project/DB volume; never overwrite the live DB."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
DOCKER = shutil.which('docker') or '/Applications/Docker.app/Contents/Resources/bin/docker'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    parser.add_argument('--keep-running', action='store_true', help='Keep only this isolated restored project running after successful checks.')
    args = parser.parse_args()
    os.umask(0o077)
    backup = args.backup.resolve()
    manifest = json.loads((backup / 'manifest.json').read_text())
    if manifest.get('format') != 1:
        raise SystemExit('Unsupported backup format')
    for name in ('application.tar.gz', 'environment.env', 'database.sql'):
        if hashlib.sha256((backup / name).read_bytes()).hexdigest() != manifest['sha256'][name]:
            raise SystemExit('Backup checksum mismatch: ' + name)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 8081))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = ROOT / 'local-dev/private/restore-runs' / stamp
    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    files_checked = 0
    with tarfile.open(backup / 'application.tar.gz', 'r:gz') as archive:
        for item in archive:
            destination = (target / item.name).resolve()
            if not destination.is_relative_to(target) or item.issym() or item.islnk():
                raise SystemExit('Unsafe archive path: ' + item.name)
            if item.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            elif item.isfile():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(item) as source, destination.open('xb') as stream:
                    shutil.copyfileobj(source, stream)
                destination.chmod(item.mode & 0o777 & ~0o6000)
                files_checked += 1
            else:
                raise SystemExit('Unsupported archive entry: ' + item.name)
    env = (backup / 'environment.env').read_text()
    if 'APP_ENV=local' not in env or 'APP_URL=http://127.0.0.1:8080' not in env:
        raise SystemExit('Only reviewed local backups are supported')
    (target / '.env').write_text(env.replace('APP_URL=http://127.0.0.1:8080', 'APP_URL=http://127.0.0.1:8081'))
    (target / '.env').chmod(0o600)
    compose = (target / 'compose.local.yaml').read_text()
    if compose.count('127.0.0.1:8080:8080') != 1:
        raise SystemExit('Unexpected web publication')
    (target / 'compose.local.yaml').write_text(compose.replace('127.0.0.1:8080:8080', '127.0.0.1:8081:8080'))
    project = 'bookstack-restore-' + stamp.lower()
    base = [DOCKER, 'compose', '-p', project, '-f', 'compose.local.yaml']
    def run(*args, **kwargs):
        return subprocess.run([*base, *args], cwd=target, check=True, **kwargs)
    report = {'backup': str(backup), 'restored_root': str(target), 'project': project, 'archive_checksums': 'PASS', 'extracted_files': files_checked, 'original_database_untouched': True}
    try:
        run('config', '--quiet')
        run('up', '-d', '--wait', 'db', stdout=subprocess.DEVNULL)
        with (backup / 'database.sql').open('rb') as stream:
            run('exec', '-T', 'db', 'sh', '-c', 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u "$MYSQL_USER" "$MYSQL_DATABASE"', stdin=stream, stdout=subprocess.DEVNULL)
        names = manifest['table_counts']
        if not all(re.fullmatch(r'[A-Za-z0-9_]+', n) for n in names):
            raise RuntimeError('Invalid table identifier')
        sql = '\n'.join(f"SELECT '{n}',COUNT(*) FROM `{n}`;" for n in names)
        result = run('exec', '-T', 'db', 'sh', '-c', 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -N -B -u "$MYSQL_USER" "$MYSQL_DATABASE"', input=sql, text=True, capture_output=True)
        actual = {line.split('\t')[0]: int(line.split('\t')[1]) for line in result.stdout.splitlines()}
        if actual != names:
            raise RuntimeError('Restored table counts differ from snapshot')
        report['all_table_row_counts'] = 'PASS'
        report['tables_checked'] = len(actual)
        run('up', '-d', 'app', 'web', stdout=subprocess.DEVNULL)
        # Application readiness is bounded; no arbitrary fixed sleep.
        import time
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        last = None
        for attempt in range(20):
            try:
                with opener.open('http://127.0.0.1:8081/login', timeout=3) as response:
                    body = response.read().decode()
                    if response.status == 200 and 'name="_token"' in body:
                        report['restored_login_page'] = 'PASS'
                        break
            except Exception as error:
                last = error
            time.sleep(1)
        else:
            raise RuntimeError('Restored HTTP readiness failed') from last
        report['result'] = 'PASS'
        print(json.dumps(report, indent=2))
        (target / 'RESTORE-RESULT.json').write_text(json.dumps(report, indent=2) + '\n')
    finally:
        if not args.keep_running:
            # No volumes are deleted. Only this unique test project is shut down.
            run('down', stdout=subprocess.DEVNULL)

if __name__ == '__main__':
    main()
