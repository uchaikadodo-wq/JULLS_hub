#!/usr/bin/env python3
"""Decrypt on the VPS with a key streamed over SSH, restore SQL into a disposable isolated MySQL."""
import importlib.util
import json
from pathlib import Path
import shlex

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('deploy', ROOT/'scripts/deploy-vps.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)

def main():
    record = json.loads((deploy.PRIVATE/'encrypted-backup-verification.json').read_text())
    backup = record['encrypted_backup']
    if not backup.startswith('/opt/lookin-base/backups/encrypted/') or not backup.endswith('.tar.gz.age'):
        raise RuntimeError('Unexpected backup path')
    key = deploy.ACCESS/'recovery/backup-age-identity.txt'
    work = deploy.remote('sudo -n mktemp -d /opt/lookin-base/backups/.restore-check-XXXXXXXX', capture=True).stdout.strip()
    if not work.startswith('/opt/lookin-base/backups/.restore-check-'):
        raise RuntimeError('Unexpected temporary directory')
    try:
        digest = deploy.remote('sudo -n sha256sum '+shlex.quote(backup), capture=True).stdout.split()[0]
        if digest != record['sha256']:
            raise RuntimeError('Encrypted archive checksum mismatch')
        # The recovery key never becomes a file on the VPS.
        command = 'set -o pipefail; sudo -n age -d -i /dev/stdin '+shlex.quote(backup)+' | sudo -n tar -xzf - -C '+shlex.quote(work)
        deploy.remote(command, data=key.read_text(), capture=True)
        program = r'''
import hashlib,json,pathlib,re,subprocess,sys,tarfile,time,uuid
work=pathlib.Path(sys.argv[1]); manifest=json.loads((work/'manifest.json').read_text())
def run(args,**kw):
    kw.setdefault('stdout',subprocess.PIPE);kw.setdefault('stderr',subprocess.PIPE)
    return subprocess.run(args,check=True,timeout=120,**kw)
for name,digest in manifest['sha256'].items():
    assert name in ('database.sql','uploads.tar.gz','configuration.tar.gz')
    h=hashlib.sha256()
    with (work/name).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    assert h.hexdigest()==digest
with tarfile.open(work/'uploads.tar.gz') as archive:
    for m in archive:
        assert not m.name.startswith('/') and '..' not in pathlib.PurePosixPath(m.name).parts
        assert m.isfile() or m.isdir()
with tarfile.open(work/'configuration.tar.gz') as archive:
    env=archive.extractfile('secrets/app.env').read().decode()
    assert re.search(r'^APP_KEY=.+',env,re.M)
image='mysql:8.4.13@sha256:a0225d1ea6631c8bc2385dc4c2faba17bbf1834ecf369e1659a9a382bd8d5dd7'
name='lookin-backup-check-'+uuid.uuid4().hex[:12]
created=False
try:
    run(['docker','run','-d','--name',name,'--network','none','--read-only',
        '--tmpfs','/var/lib/mysql:uid=999,gid=999,mode=0700,size=512m',
        '--tmpfs','/var/run/mysqld:uid=999,gid=999,size=16m','--tmpfs','/tmp:size=32m',
        '--cap-drop','ALL','--cap-add','CHOWN','--cap-add','DAC_OVERRIDE','--cap-add','FOWNER',
        '--cap-add','SETGID','--cap-add','SETUID','--security-opt','no-new-privileges:true',
        '--memory','512m','--pids-limit','128','-e','MYSQL_ALLOW_EMPTY_PASSWORD=yes','-e','MYSQL_DATABASE=bookstack',
        image,'--innodb-buffer-pool-size=64M','--performance-schema=OFF','--mysqlx=OFF','--max-connections=10'])
    created=True
    base=['docker','exec','-i',name,'mysql','-h','127.0.0.1','-uroot','-N','-B','bookstack']
    for attempt in range(60):
        try:
            run(base,input=b'SELECT 1;');break
        except subprocess.CalledProcessError:time.sleep(1)
    else:raise RuntimeError('Isolated restore database not ready')
    with (work/'database.sql').open('rb') as f:run(base,stdin=f)
    expected=manifest['table_counts']
    assert all(re.fullmatch(r'[A-Za-z0-9_]+',n) for n in expected)
    sql='\n'.join("SELECT '%s',COUNT(*) FROM `%s`;"%(n,n) for n in expected)
    rows=run(base,input=sql.encode()).stdout.decode().splitlines()
    actual={r.split('\t')[0]:int(r.split('\t')[1]) for r in rows}
    assert actual==expected
    print(json.dumps({'decryption':'PASS','archive_checksums':'PASS','uploads_archive_safety':'PASS',
        'app_key_present':'PASS','mysql_restore_and_all_table_counts':'PASS','tables':len(actual),
        'production_database_modified':False,'offsite_roundtrip_tested':False,'full_application_restore_tested':False}))
finally:
    if created:run(['docker','rm','-f',name])
'''
        result = deploy.remote('sudo -n python3 - '+shlex.quote(work), data=program, capture=True)
        report = json.loads(result.stdout)
        (ROOT/'local-dev/vps-encrypted-backup-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally:
        deploy.remote('sudo -n python3 -c '+shlex.quote('import shutil; shutil.rmtree('+repr(work)+')'), capture=True)

if __name__ == '__main__':
    main()
