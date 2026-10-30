#!/usr/bin/env python3
"""Check only the agreed VPS: SSH positive/negative login and selected TCP ports."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import socket

ROOT = Path(__file__).resolve().parent.parent

def main():
    spec = importlib.util.spec_from_file_location('vps', ROOT / 'scripts/vps-prepare.py')
    vps = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vps)
    # Verify authenticated access before the negative probe, so a network failure
    # cannot be mistaken for an authentication denial.
    success = vps.ssh('ltadmin', 'id -un', capture=True)
    assert success.stdout.strip() == 'ltadmin'
    denied = vps.ssh('root', 'true', check=False, capture=True)
    assert denied.returncode == 255 and 'Permission denied (publickey)' in denied.stderr
    def probe(port):
        try:
            with socket.create_connection((vps.HOST, port), timeout=3):
                return port, 'open'
        except socket.timeout:
            return port, 'no_connection_timeout'
        except ConnectionRefusedError:
            return port, 'no_connection_refused'
    with ThreadPoolExecutor(max_workers=5) as pool:
        ports = dict(pool.map(probe, [22, 80, 443, 3306, 8080]))
    assert ports[22] == 'open'
    assert all(ports[port] != 'open' for port in (80, 443, 3306, 8080))
    report = {'result': 'PASS', 'target': vps.HOST, 'ltadmin_key_login': 'PASS',
        'direct_root_login': 'DENIED', 'ports_from_this_mac': ports,
        'scope': 'Selected TCP connections only; timeout does not identify which firewall dropped a packet.'}
    (ROOT / 'local-dev/vps-network-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
