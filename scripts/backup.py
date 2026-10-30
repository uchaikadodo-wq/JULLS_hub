#!/usr/bin/env python3
"""Local BookStack backup: consistent SQL + application/files + .env, no secrets printed."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent.parent
DOCKER = shutil.which('docker') or '/Applications/Docker.app/Contents/Resources/bin/docker'
BASE = [DOCKER, 'compose', '-f', 'compose.local.yaml']

def command(*args, **kwargs):
    return subprocess.run([*BASE, *args], cwd=ROOT, check=True, **kwargs)

def counts():
    base = ['exec', '-T', 'db', 'sh', '-c', 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -N -B -u "$MYSQL_USER" "$MYSQL_DATABASE"']
    names = command(*base, input='SHOW TABLES;\n', text=True, capture_output=True).stdout.splitlines()
    if not all(re.fullmatch(r'[A-Za-z0-9_]+', n) for n in names):
        raise RuntimeError('Unexpected SQL table identifier')
    sql = '\n'.join(f"SELECT '{n}', COUNT(*) FROM `{n}`;" for n in names)
    rows = command(*base, input=sql, text=True, capture_output=True).stdout.splitlines()
    return {row.split('\t')[0]: int(row.split('\t')[1]) for row in rows}

def main():
    os.umask(0o077)
    env = (ROOT / '.env').read_text()
    if 'APP_ENV=local' not in env or 'APP_URL=http://127.0.0.1:8080' not in env:
        raise SystemExit('This script is restricted to the reviewed local environment.')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = ROOT / 'local-dev/private/backups' / stamp
    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    running = command('ps', '--status', 'running', '--services', text=True, capture_output=True).stdout.splitlines()
    pause = [name for name in ('web', 'app') if name in running]
    try:
        if pause:
            command('stop', *pause, stdout=subprocess.DEVNULL)
        with (target / 'database.sql').open('xb') as stream:
            command('exec', '-T', 'db', 'sh', '-c', 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump -u "$MYSQL_USER" --single-transaction --skip-lock-tables --no-tablespaces --set-gtid-purged=OFF --hex-blob "$MYSQL_DATABASE"', stdout=stream)
        table_counts = counts()
        shutil.copyfile(ROOT / '.env', target / 'environment.env')
        (target / 'environment.env').chmod(0o600)
        def include(info):
            rel = Path(info.name)
            parts = rel.parts
            if parts and parts[0] in ('.git', 'node_modules', '.env'):
                return None
            if parts[:2] == ('local-dev', 'private'):
                return None
            if parts[:2] == ('storage', 'logs') and len(parts) > 2 and parts[-1] != '.gitignore':
                return None
            if len(parts) > 3 and parts[:2] == ('storage', 'framework') and parts[2] in ('cache', 'sessions', 'views') and parts[-1] != '.gitignore':
                return None
            if info.issym() or info.islnk():
                raise RuntimeError('Archive unexpectedly contains a link: ' + info.name)
            return info
        # Dereference only links contained inside the project (e.g. vendor/bin tools).
        for path in ROOT.rglob('*'):
            if '.git' in path.parts or 'node_modules' in path.parts or ROOT / 'local-dev/private' in path.parents:
                continue
            if path.is_symlink() and not path.resolve().is_relative_to(ROOT):
                raise RuntimeError('Refusing an out-of-project symlink: ' + str(path))
        with tarfile.open(target / 'application.tar.gz', 'w:gz', dereference=True) as archive:
            for child in sorted(ROOT.iterdir()):
                archive.add(child, arcname=child.name, filter=include)
        hashes = {name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in ('database.sql', 'environment.env', 'application.tar.gz')}
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        manifest = {'format': 1, 'created_utc': stamp, 'git_base': revision, 'sha256': hashes, 'table_counts': table_counts, 'consistent_app_stop': pause, 'secrets_included': True, 'scope': 'local only; storage/uploads and public/uploads are inside application archive; node_modules, Git, caches, logs and private artifacts excluded'}
        (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(target)
    finally:
        if pause:
            command('start', *reversed(pause), stdout=subprocess.DEVNULL)

if __name__ == '__main__':
    main()
