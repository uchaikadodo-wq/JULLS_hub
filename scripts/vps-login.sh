#!/bin/sh
# Owner's interactive SSH login; the private key remains outside the app bind mount.
set -eu
lt_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
lt_access_dir=$(CDPATH= cd -- "$lt_script_dir/../../.server-access" && pwd)
exec ssh -i "$lt_access_dir/lookin-base-194.135.23.218-ed25519" \
  -o IdentitiesOnly=yes -o IdentityAgent=none -o StrictHostKeyChecking=yes \
  -o "UserKnownHostsFile=\"$lt_access_dir/known_hosts\"" \
  -o HostKeyAlgorithms=ssh-ed25519 -o ConnectTimeout=10 ltadmin@194.135.23.218
