#!/usr/bin/env python3
"""Run on the VPS as root: consistent BookStack snapshot, age encryption, no upload yet."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path('/opt/lookin-base')
COMPOSE = ['docker', 'compose', '--env-file', str(ROOT/'deploy.env'), '-f', str(ROOT/'server/compose.yaml')]

def run(args, **kwargs):
    # Never send command output (which may contain data) to the system journal.
    kwargs.setdefault('stderr', subprocess.PIPE)
    kwargs.setdefault('stdout', subprocess.PIPE)
    return subprocess.run(args, check=True, timeout=180, **kwargs)

def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()

def main():
    if os.geteuid() != 0:
        raise SystemExit('Run on the VPS as root.')
    os.umask(0o077)
    destination = ROOT/'backups/encrypted'
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (ROOT/'backups/backup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recipient = (ROOT/'secrets/backup-recipient.txt').read_text().strip()
        if not re.fullmatch(r'age1[023456789acdefghjklmnpqrstuvwxyz]{58}', recipient):
            raise RuntimeError('Invalid backup recipient')
        if shutil.disk_usage(ROOT).free < 2*1024**3:
            raise RuntimeError('Less than 2 GiB free; backup refused')
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        work = ROOT/'backups'/('.work-'+stamp)
        partial = destination/(stamp+'.tar.gz.age.partial')
        final = destination/(stamp+'.tar.gz.age')
        running = run(COMPOSE+['ps','--status','running','--services'], text=True).stdout.splitlines()
        pause = [s for s in ('web','app') if s in running]
        if set(pause) != {'web','app'} or 'db' not in running:
            raise RuntimeError('Expected all production services to be running')
        work.mkdir(mode=0o700)
        try:
            try:
                run(COMPOSE+['stop','web','app'])
                mysql = 'MYSQL_PWD="$(cat /run/secrets/db_password)" '
                with (work/'database.sql').open('xb') as output:
                    run(COMPOSE+['exec','-T','db','sh','-c',mysql+'exec mysqldump -u bookstack --single-transaction --skip-lock-tables --no-tablespaces --set-gtid-purged=OFF --hex-blob bookstack'], stdout=output)
                query = COMPOSE+['exec','-T','db','sh','-c',mysql+'exec mysql -N -B -u bookstack bookstack']
                names = run(query, input='SHOW TABLES;\n', text=True).stdout.splitlines()
                if not names or not all(re.fullmatch(r'[A-Za-z0-9_]+', n) for n in names):
                    raise RuntimeError('Unexpected database schema')
                sql = '\n'.join(f"SELECT '{n}',COUNT(*) FROM `{n}`;" for n in names)
                rows = run(query, input=sql, text=True).stdout.splitlines()
                counts = {r.split('\t')[0]:int(r.split('\t')[1]) for r in rows}
                config = json.loads(run(COMPOSE+['config','--format','json'], text=True).stdout)
                app_image = config['services']['app']['image']
                with (work/'uploads.tar.gz').open('xb') as output:
                    run(['docker','run','--rm','--network','none','--read-only','--user','1000:1000','--cap-drop','ALL',
                         '--security-opt','no-new-privileges:true','--memory','128m','--pids-limit','32',
                         '-v','lookin-base_storage:/app/storage:ro','-v','lookin-base_public_uploads:/app/public/uploads:ro',
                         '--entrypoint','tar',app_image,'-czf','-','-C','/app',
                         '--exclude=storage/logs','--exclude=storage/framework/cache',
                         '--exclude=storage/framework/sessions','--exclude=storage/framework/views',
                         'storage','public/uploads'], stdout=output)
                with tarfile.open(work/'configuration.tar.gz','w:gz') as archive:
                    for name in ['deploy.env','server','secrets','release-git-commit','operations-git-commit']:
                        path = ROOT/name
                        if path.exists():
                            archive.add(path, arcname=name)
            finally:
                # Restore availability even if dumping or archiving fails.
                run(COMPOSE+['start','app','web'])
            manifest = {'format':'lookin-vps-1','created_utc':stamp,'table_counts':counts,
                        'consistent_app_stop':True,'app_key_included':True,
                        'sha256':{p.name:sha256(p) for p in work.iterdir() if p.is_file()}}
            (work/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            # Stream the outer archive into age; never make an unencrypted outer archive.
            encrypt = subprocess.Popen(['age','-r',recipient,'-o',str(partial)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                with tarfile.open(fileobj=encrypt.stdin,mode='w|gz') as archive:
                    for path in sorted(work.iterdir()):
                        archive.add(path,arcname=path.name)
                encrypt.stdin.close()
                error = encrypt.stderr.read()
                if encrypt.wait(timeout=180) != 0:
                    raise RuntimeError('Encryption failed')
            finally:
                if encrypt.poll() is None:
                    encrypt.kill(); encrypt.wait()
            partial.rename(final)
            digest = sha256(final)
            (destination/(final.name+'.sha256')).write_text(digest+'  '+final.name+'\n')
            # Deliberately no automatic deletion until offsite copies are verified.
            print(json.dumps({'encrypted_backup':str(final),'sha256':digest,'tables':len(counts),'offsite_upload':False}))
        finally:
            shutil.rmtree(work)
            partial.unlink(missing_ok=True)

if __name__ == '__main__':
    try:
        main()
    except Exception:
        # A failed dump/credential command must not leak its output into logs.
        raise SystemExit('Backup failed. Check service availability and protected backup configuration.')
