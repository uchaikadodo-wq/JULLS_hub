#!/usr/bin/env python3
"""Explicit first deployment to the agreed VPS. Secrets travel through stdin/SSH, never argv/logs."""
import argparse
import base64
import datetime
import hashlib
import importlib.util
import io
import json
import os
import re
import gzip
from pathlib import Path
import secrets
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
ACCESS = ROOT.parent / '.server-access'
PRIVATE = ACCESS / 'deployment'
SPEC = importlib.util.spec_from_file_location('vps', ROOT / 'scripts/vps-prepare.py')
VPS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VPS)
REMOTE = '/opt/lookin-base'
APP_IMAGE = 'lookin-base-app:v26.09.2-20261030-1'
WEB_IMAGE = 'lookin-base-web:v26.09.2-20261030-1'

def ssh_args(command):
    control_file = PRIVATE / 'ssh-control-path'
    if control_file.exists():
        control = control_file.read_text().strip()
    else:
        directory = tempfile.mkdtemp(prefix='lookin-vps-', dir='/private/tmp')
        control = str(Path(directory) / 'control')
        control_file.write_text(control)
    # Reuse one authenticated connection, preserving the SSH rate limit.
    return ['ssh', '-T', '-i', str(VPS.KEY), '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
        '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'UserKnownHostsFile="' + str(ACCESS / 'known_hosts') + '"',
        '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'ConnectTimeout=10',
        '-o', 'ServerAliveInterval=20', '-o', 'ControlMaster=auto', '-o', 'ControlPersist=300s',
        '-o', 'ControlPath=' + control, 'ltadmin@' + VPS.HOST, command]

def remote(command, data=None, binary=False, capture=False):
    return subprocess.run(ssh_args(command), input=data, text=not binary, check=True, capture_output=capture)

def cp_command(operation):
    return 'sudo -n docker compose --env-file /opt/lookin-base/deploy.env -f /opt/lookin-base/server/compose.yaml ' + operation

def prepare(email):
    os.umask(0o077)
    PRIVATE.mkdir(mode=0o700, exist_ok=False)
    backup = Path((ROOT / 'local-dev/private/server-preparation-2026-10-30/migration-backup-path.txt').read_text().strip())
    manifest = json.loads((backup / 'manifest.json').read_text())
    for name in ['database.sql', 'environment.env', 'application.tar.gz']:
        assert hashlib.sha256((backup / name).read_bytes()).hexdigest() == manifest['sha256'][name]
    source_env = {}
    for line in (backup / 'environment.env').read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1); source_env[k] = v.strip('"\'')
    key = source_env['APP_KEY']
    assert key.startswith('base64:') and len(base64.b64decode(key[7:], validate=True)) == 32
    db_password, db_root = secrets.token_hex(32), secrets.token_hex(32)
    admin_email = json.loads((ROOT / 'local-dev/private/admin.json').read_text())['email']
    admin_password = secrets.token_urlsafe(32)
    (PRIVATE / 'secrets').mkdir(mode=0o700)
    for name, content in [('db-password', db_password), ('db-root-password', db_root)]:
        (PRIVATE / 'secrets' / name).write_text(content + '\n')
    env = (ROOT / 'server/app.env.example').read_text().replace('__PRESERVE_EXISTING_APP_KEY_WHEN_RESTORING__', key)
    env = env.replace('__NEW_SERVER_DB_PASSWORD_MATCHING_SECRET_FILE__', db_password).replace('__SET_SENDER_EMAIL__', email)
    (PRIVATE / 'secrets/app.env').write_text(env)
    deploy = (ROOT / 'server/deploy.env.example').read_text().replace('__SET_OPERATIONS_EMAIL__', email)
    (PRIVATE / 'deploy.env').write_text(deploy)
    (PRIVATE / 'admin-login.txt').write_text('Сайт: https://base.lookin.team\nЛогин: ' + admin_email + '\nПароль: ' + admin_password + '\n\nСохраните пароль в менеджере паролей. Email администратора пока прежний; его можно изменить в профиле.\n')
    state = {'backup': str(backup), 'table_counts': manifest['table_counts'], 'admin_email': admin_email,
        'admin_password': admin_password, 'app_key_sha256': hashlib.sha256(key.encode()).hexdigest()}
    (PRIVATE / 'state.json').write_text(json.dumps(state))
    shutil.copyfile(backup / 'database.sql', PRIVATE / 'database.sql')
    with tarfile.open(backup / 'application.tar.gz') as original, tarfile.open(PRIVATE / 'uploads.tar.gz', 'w:gz') as output:
        for member in original:
            if member.name.startswith(('storage/uploads/', 'storage/fonts/', 'public/uploads/')):
                assert not member.issym() and not member.islnk() and '..' not in Path(member.name).parts
                member.uid = member.gid = 1000
                member.uname = member.gname = ''
                member.mode = 0o750 if member.isdir() else 0o640
                output.addfile(member, original.extractfile(member) if member.isfile() else None)
    print('Protected deployment files prepared. APP_KEY preserved; new server passwords generated.')

def upload():
    state = json.loads((PRIVATE / 'state.json').read_text())
    expected = json.loads((ROOT / 'local-dev/server-release-manifest.json').read_text())['images']
    for label, tag in [('app', APP_IMAGE), ('web', WEB_IMAGE)]:
        info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', tag], text=True))[0]
        assert info['Id'] == expected[label] and info['Architecture'] == 'amd64'
    images = PRIVATE / 'images.tar.gz'
    if not images.exists():
        export = subprocess.Popen(['docker', 'save', '--platform', 'linux/amd64', APP_IMAGE, WEB_IMAGE], stdout=subprocess.PIPE)
        with gzip.open(images, 'wb', compresslevel=3) as stream:
            shutil.copyfileobj(export.stdout, stream, length=1024 * 1024)
        export.stdout.close()
        if export.wait() != 0:
            raise RuntimeError('Image export failed')
    source = PRIVATE / 'source.tar'
    if not source.exists():
        with source.open('xb') as stream:
            subprocess.run(['git', 'archive', '--format=tar', 'HEAD'], cwd=ROOT, stdout=stream, check=True)
    package = PRIVATE / 'deployment.tar.gz'
    with tarfile.open(package, 'w:gz') as archive:
        for name in ['deploy.env', 'secrets', 'database.sql', 'uploads.tar.gz']:
            archive.add(PRIVATE / name, arcname=name)
        # Runtime configuration only. Full source provenance is recorded via the Git commit.
        archive.add(ROOT / 'server/compose.yaml', arcname='server/compose.yaml')
        archive.add(ROOT / 'local-dev/server-release-manifest.json', arcname='release-manifest.json')
        archive.add(source, arcname='source.tar')
        for name in ['server/app.env.example', 'server/deploy.env.example']:
            archive.add(ROOT / name, arcname=name)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    state['release_git_commit'] = revision
    state['image_layers'] = {kind: json.loads(subprocess.check_output(['docker','image','inspect',tag],text=True))[0]['RootFS']['Layers'] for kind,tag in [('app',APP_IMAGE),('web',WEB_IMAGE)]}
    hashes = {}
    for path in [images, package]:
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for part in iter(lambda: stream.read(1024 * 1024), b''): digest.update(part)
        hashes[path.name] = digest.hexdigest()
    (PRIVATE / 'transfer-sha256.json').write_text(json.dumps(hashes))
    (PRIVATE / 'state.json').write_text(json.dumps(state))
    remote("sudo -n bash -c 'set -eu; test ! -e /opt/lookin-base; install -d -o ltadmin -g ltadmin -m 700 /opt/lookin-base /opt/lookin-base/incoming'")
    for path in [images, package]:
        # Stream from protected files without loading the image archive into memory.
        command = 'umask 077; cat > /opt/lookin-base/incoming/' + path.name
        with path.open('rb') as stream:
            subprocess.run(ssh_args(command), stdin=stream, check=True)
        remote('test "$(sha256sum /opt/lookin-base/incoming/' + path.name + ' | cut -d\" \" -f1)" = ' + hashes[path.name])
    unpack()
    print('Archives transferred and checksums verified; website not started.')

def unpack():
    state=json.loads((PRIVATE/'state.json').read_text())
    hashes=json.loads((PRIVATE/'transfer-sha256.json').read_text())
    for name,digest in hashes.items():
        remote('test "$(sha256sum /opt/lookin-base/incoming/' + name + ' | cut -d\" \" -f1)" = ' + digest)
    remote('set -eu; test ! -e /opt/lookin-base/deploy.env; umask 077; tar -xzf /opt/lookin-base/incoming/deployment.tar.gz -C /opt/lookin-base; chmod 700 /opt/lookin-base/secrets; chmod 600 /opt/lookin-base/deploy.env /opt/lookin-base/secrets/*; printf %s ' + state['release_git_commit'] + ' > /opt/lookin-base/release-git-commit')
    print('Verified deployment package unpacked.')

def load():
    remote('sudo -n docker load -i /opt/lookin-base/incoming/images.tar.gz')
    state=json.loads((PRIVATE/'state.json').read_text())
    for kind,tag in [('app',APP_IMAGE),('web',WEB_IMAGE)]:
        info=json.loads(remote('sudo -n docker image inspect '+tag,capture=True).stdout)[0]
        assert info['Architecture']=='amd64' and info['RootFS']['Layers']==state['image_layers'][kind]
    remote(cp_command('config --quiet') + ' && ' + cp_command('up -d --wait db app'))

def restore():
    state = json.loads((PRIVATE / 'state.json').read_text())
    query = "MYSQL_PWD=\"$(cat /run/secrets/db_password)\" mysql -N -B -u bookstack bookstack"
    empty = remote(cp_command("exec -T db sh -c '" + query + " -e \"SHOW TABLES\"'"), capture=True).stdout.strip()
    if empty:
        raise RuntimeError('Database is not empty; restore refused')
    # Input is SQL through SSH stdin; the password is read only inside the container.
    with (PRIVATE / 'database.sql').open('rb') as stream:
        data = stream.read()
    remote(cp_command("exec -T db sh -c '" + query + "'"), data=data, binary=True, capture=True)
    names = state['table_counts']
    assert all(re.fullmatch(r'[A-Za-z0-9_]+', name) for name in names)
    sql = '\n'.join(f"SELECT '{name}',COUNT(*) FROM `{name}`;" for name in names)
    response = remote(cp_command("exec -T db sh -c '" + query + "'"), data=sql, capture=True).stdout
    counts = {line.split('\t')[0]: int(line.split('\t')[1]) for line in response.splitlines()}
    assert counts == names
    remote(cp_command('exec -T app tar -xzf - --no-same-owner -C /app'), data=(PRIVATE / 'uploads.tar.gz').read_bytes(), binary=True, capture=True)
    remote(cp_command('exec -T app php artisan migrate --force'))
    state['restored_table_counts_match'] = True
    (PRIVATE / 'state.json').write_text(json.dumps(state))
    print('Database and uploads restored. All table counts match the fresh snapshot.')

def configure():
    state = json.loads((PRIVATE / 'state.json').read_text())
    assert state.get('restored_table_counts_match')
    data = base64.b64encode(json.dumps({'email': state['admin_email'], 'password': state['admin_password']}).encode()).decode()
    script = '''<?php
require '/app/vendor/autoload.php'; $app=require '/app/bootstrap/app.php'; $app->make(Illuminate\\Contracts\\Console\\Kernel::class)->bootstrap();
if(config('app.env')!=='production'||config('app.url')!=='https://base.lookin.team')throw new RuntimeException('Unexpected target');
$data=json_decode(base64_decode(''' + "'" + data + "'" + '''),true);
$admin=BookStack\\Users\\Models\\User::where('email',$data['email'])->firstOrFail();
if(!$admin->hasSystemRole('admin'))throw new RuntimeException('Expected administrator');
$admin->password=Illuminate\\Support\\Facades\\Hash::make($data['password']); $admin->setRememberToken(Illuminate\\Support\\Str::random(60)); $admin->save();
$pilot=BookStack\\Users\\Models\\User::where('email','pilot-reader@agents.example.test')->first();
if($pilot){$pilot->apiTokens()->delete();}
setting()->put('app-public','false'); setting()->put('registration-enabled','false');
echo json_encode(['admin_password_rotated'=>true,'local_pilot_tokens_revoked'=>true,'app_key_sha256'=>hash('sha256',config('app.key'))]);
'''
    result = json.loads(remote(cp_command('exec -T app php'), data=script, capture=True).stdout)
    assert result['app_key_sha256'] == state['app_key_sha256']
    remote(cp_command('exec -T app php /opt/lookin/release-check.php'))
    state['configured'] = True
    (PRIVATE / 'state.json').write_text(json.dumps(state))
    print('Production access closed, admin password rotated, local pilot tokens revoked; APP_KEY matches source.')

def publish():
    assert json.loads((PRIVATE / 'state.json').read_text()).get('configured')
    remote("sudo -n ufw allow 80/tcp comment 'Lookin Base HTTP HTTPS challenge' && sudo -n ufw allow 443/tcp comment 'Lookin Base HTTPS'")
    remote(cp_command('up -d web'))
    print('Caddy started on agreed web ports; certificate and login still require verification.')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'upload', 'unpack', 'load', 'restore', 'configure', 'publish'])
    parser.add_argument('--acme-email')
    args = parser.parse_args()
    if args.phase == 'prepare':
        assert args.acme_email and re.fullmatch(r'[A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+', args.acme_email)
        prepare(args.acme_email)
    else:
        globals()[args.phase]()

if __name__ == '__main__':
    main()
