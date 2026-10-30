#!/usr/bin/env python3
"""Agreed preparation of one verified, empty VPS. Does not deploy BookStack or open web ports."""
import argparse
import hashlib
import base64
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
ACCESS = ROOT.parent / '.server-access'
KEY = ACCESS / 'lookin-base-194.135.23.218-ed25519'
HOST = '194.135.23.218'
BACKUP = '/root/lookin-prep-20261029'

def ssh(user, command, script=None, check=True, capture=False):
    return subprocess.run(['ssh', '-T', '-i', str(KEY), '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
        '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'UserKnownHostsFile="' + str(ACCESS / 'known_hosts') + '"',
        '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'ConnectTimeout=10',
        user + '@' + HOST, command], input=script, text=True, check=check, capture_output=capture)

GUARD = '''set -eu
test "$(id -u)" = 0
test "$(hostname -s)" = v3291312
test -d /root/lookin-prep-20261029
'''

UPDATE = GUARD + '''
test ! -e /root/lookin-prep-20261029/update.sh
cat > /root/lookin-prep-20261029/update.sh <<'UPDATE_SCRIPT'
#!/bin/bash
set -eu
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
exec >> /root/lookin-prep-20261029/update.log 2>&1
apt-get -y -o Dpkg::Options::=--force-confold upgrade
apt-get install -y --no-install-recommends docker-compose-v2=2.40.3+ds1-0ubuntu1~24.04.1
docker compose version
dpkg --audit
date -u > /root/lookin-prep-20261029/update-complete
UPDATE_SCRIPT
chmod 700 /root/lookin-prep-20261029/update.sh
systemd-run --no-block --unit=lookin-base-update --property=Type=oneshot /bin/bash /root/lookin-prep-20261029/update.sh
'''

def admin_script():
    public = Path(str(KEY) + '.pub').read_text().strip()
    parts = public.split()
    digest = base64.b64encode(hashlib.sha256(base64.b64decode(parts[1])).digest()).decode().rstrip('=')
    if parts[0] != 'ssh-ed25519' or digest != 'VgNwo9kbRm36H6iu4mssYqgMz2rXSL6ZO3mPJhzAkNA':
        raise RuntimeError('Unexpected administrative public key')
    public = 'no-agent-forwarding,no-port-forwarding,no-X11-forwarding ' + public
    return GUARD + '''
test -e /root/lookin-prep-20261029/update-complete
if getent passwd ltadmin >/dev/null; then
  test -e /root/lookin-prep-20261029/admin-created
else
  adduser --disabled-password --gecos 'Lookin Base administrator' ltadmin
  touch /root/lookin-prep-20261029/admin-created
fi
test "$(getent passwd ltadmin | cut -d: -f6)" = /home/ltadmin
install -d -o ltadmin -g ltadmin -m 700 /home/ltadmin/.ssh
lt_public_key=''' + "'" + public + "'" + '''
{ grep -qxF "$lt_public_key" /home/ltadmin/.ssh/authorized_keys 2>/dev/null || printf '%s\\n' "$lt_public_key" >> /home/ltadmin/.ssh/authorized_keys; }
chown ltadmin:ltadmin /home/ltadmin/.ssh/authorized_keys
chmod 600 /home/ltadmin/.ssh/authorized_keys
printf '%s\\n' 'ltadmin ALL=(ALL:ALL) NOPASSWD: ALL' > /root/lookin-prep-20261029/sudoers-ltadmin
visudo -cf /root/lookin-prep-20261029/sudoers-ltadmin
test ! -e /etc/sudoers.d/90-lookin-admin || cmp -s /root/lookin-prep-20261029/sudoers-ltadmin /etc/sudoers.d/90-lookin-admin
install -o root -g root -m 440 /root/lookin-prep-20261029/sudoers-ltadmin /etc/sudoers.d/90-lookin-admin
visudo -c >/dev/null
echo 'Administrative account and key prepared'
'''

HARDEN = GUARD + '''
test -e /root/lookin-prep-20261029/admin-key-verified
test ! -e /etc/ssh/sshd_config.d/00-lookin-hardening.conf
test ! -e /root/lookin-prep-20261029/access-rollback.sh
test "$(ufw status | head -1)" = 'Status: inactive'
cat > /root/lookin-prep-20261029/access-rollback.sh <<'ROLLBACK'
#!/bin/bash
set -eu
# Preserve the failed configuration, then restore the exact previous snippets.
if test -f /etc/ssh/sshd_config.d/00-lookin-hardening.conf; then
  mv /etc/ssh/sshd_config.d/00-lookin-hardening.conf /root/lookin-prep-20261029/failed-ssh-hardening.conf
fi
ufw --force disable
cp -a /root/lookin-prep-20261029/ufw/. /etc/ufw/
/usr/sbin/sshd -t
systemctl reload ssh
ROLLBACK
chmod 700 /root/lookin-prep-20261029/access-rollback.sh
systemd-run --unit=lookin-access-rollback --on-active=5m /bin/bash /root/lookin-prep-20261029/access-rollback.sh
cat > /etc/ssh/sshd_config.d/00-lookin-hardening.conf <<'SSH_CONFIG'
# Managed preparation; previous configuration retained under /root/lookin-prep-20261029.
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers ltadmin
MaxAuthTries 3
LoginGraceTime 30
AllowAgentForwarding no
AllowTcpForwarding no
X11Forwarding no
SSH_CONFIG
/usr/sbin/sshd -t
systemctl reload ssh
ufw default deny incoming
ufw default allow outgoing
ufw limit 22/tcp comment 'SSH administrative access'
ufw --force enable
ufw status verbose
/usr/sbin/sshd -T | grep -E '^(permitrootlogin|passwordauthentication|pubkeyauthentication|allowusers) '
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['update', 'update-status', 'admin', 'verify-admin', 'harden', 'verify-access', 'finish-access', 'reboot', 'final-status', 'kernel-update', 'kernel-status'])
    args = parser.parse_args()
    if args.phase == 'update':
        ssh('root', 'bash -se', UPDATE)
    elif args.phase == 'update-status':
        ssh('root', "systemctl show lookin-base-update -p ActiveState -p SubState -p Result; tail -n 12 " + BACKUP + "/update.log; test ! -f /var/run/reboot-required || cat /var/run/reboot-required")
    elif args.phase == 'admin':
        ssh('root', 'bash -se', admin_script())
    elif args.phase == 'verify-admin':
        ssh('ltadmin', "test \"$(id -un)\" = ltadmin && sudo -n /usr/bin/id && sudo -n touch " + BACKUP + "/admin-key-verified")
    elif args.phase == 'harden':
        ssh('ltadmin', 'sudo -n bash -se', HARDEN)
    elif args.phase == 'verify-access':
        ssh('ltadmin', "sudo -n /usr/sbin/sshd -t && sudo -n ufw status verbose && sudo -n /usr/sbin/sshd -T | grep -E '^(permitrootlogin|passwordauthentication|pubkeyauthentication|allowusers) ' && sudo -n systemctl is-active ssh docker && docker compose version")
    elif args.phase == 'finish-access':
        ssh('ltadmin', 'sudo -n systemctl stop lookin-access-rollback.timer && sudo -n systemctl is-active ssh docker && echo "Fresh key login verified; automatic rollback cancelled"')
    elif args.phase == 'reboot':
        ssh('ltadmin', 'sudo -n systemd-run --unit=lookin-prep-reboot --on-active=5s /usr/bin/systemctl reboot')
    elif args.phase == 'kernel-update':
        ssh('ltadmin', 'sudo -n bash -se', GUARD + '''
test ! -e /root/lookin-prep-20261029/kernel-update.sh
apt-get -s --with-new-pkgs upgrade > /root/lookin-prep-20261029/kernel-preview.txt
if grep -q '^Remv ' /root/lookin-prep-20261029/kernel-preview.txt; then echo 'Unexpected package removals; aborting'; exit 1; fi
cat > /root/lookin-prep-20261029/kernel-update.sh <<'KERNEL_SCRIPT'
#!/bin/bash
set -eu
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
exec >> /root/lookin-prep-20261029/kernel-update.log 2>&1
apt-get -y --no-remove --with-new-pkgs -o Dpkg::Options::=--force-confold upgrade
dpkg --audit
date -u > /root/lookin-prep-20261029/kernel-update-complete
KERNEL_SCRIPT
chmod 700 /root/lookin-prep-20261029/kernel-update.sh
systemd-run --no-block --unit=lookin-kernel-update --property=Type=oneshot /bin/bash /root/lookin-prep-20261029/kernel-update.sh
''')
    elif args.phase == 'kernel-status':
        ssh('ltadmin', 'sudo -n systemctl show lookin-kernel-update -p ActiveState -p SubState -p Result; sudo -n tail -n 10 /root/lookin-prep-20261029/kernel-update.log; if sudo -n test -e /root/lookin-prep-20261029/kernel-update-complete; then echo COMPLETE; else echo PENDING; fi')
    elif args.phase == 'final-status':
        ssh('ltadmin', '''set -eu
printf 'BOOT\\n'; uptime -s; uname -r
printf 'ACCESS\\n'; id; sudo -n id
printf 'SERVICES\\n'; sudo -n systemctl is-active ssh docker containerd
printf 'COMPOSE\\n'; docker compose version
printf 'FIREWALL\\n'; sudo -n ufw status verbose
printf 'SSH\\n'; sudo -n /usr/sbin/sshd -t; sudo -n /usr/sbin/sshd -T | grep -E '^(permitrootlogin|passwordauthentication|pubkeyauthentication|allowusers) '
printf 'CONTAINERS\\n'; sudo -n docker ps --format 'table {{.Names}}\\t{{.Image}}\\t{{.Ports}}'
printf 'LISTENERS\\n'; sudo -n ss -lnt
printf 'PACKAGE_AUDIT\\n'; sudo -n dpkg --audit
printf 'PENDING_UPDATES\\n'; sudo -n apt-get -s upgrade | tail -4
printf 'REBOOT_REQUIRED\\n'; if test -f /var/run/reboot-required; then cat /var/run/reboot-required; else echo no; fi
printf 'AUTO_UPDATES\\n'; systemctl is-enabled unattended-upgrades
printf 'RESOURCES\\n'; free -h; df -h /
''')

if __name__ == '__main__':
    main()
