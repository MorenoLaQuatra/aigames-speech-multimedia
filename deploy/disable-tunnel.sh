#!/usr/bin/env bash
# Removes this app's hostname (configs/app.yaml: deploy.hostname) ingress rule from the shared Cloudflare
# Tunnel and restarts cloudflared. Counterpart to enable-tunnel.sh.
#
# Deliberately does NOT touch the DNS CNAME record enable-tunnel.sh created
# (`cloudflared tunnel route dns`): the cloudflared CLI has no command to
# remove a DNS route it created - route dns/lb/ip only ever add one, and
# actually deleting the record means calling the Cloudflare API directly
# with a DNS-edit API token, which this script doesn't have. Once this
# script removes the ingress rule and restarts cloudflared, the hostname
# still resolves but just falls through to the `http_status:404` catch-all -
# harmless to leave in place, and matches how
# knowledge/personal-obsidian-knowledge/linux-guides/add-cloudflare-tunnel.md's
# own "remove the app" steps work (they don't clean up the DNS route either).
#
# Run with sudo (it edits a root-owned file and restarts a system service):
#   sudo /home/mlaquatra/apps/ai-games-platform/deploy/disable-tunnel.sh

set -euo pipefail

APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
CLOUDFLARED_CONFIG="/etc/cloudflared/config.yml"
HOSTNAME_VALUE=$(awk '/^deploy:/{f=1; next} f && /^[a-zA-Z]/{f=0} f && /hostname:/{print $2; exit}' "${APP_DIR}/configs/app.yaml" | tr -d '"')
if [[ -z "${HOSTNAME_VALUE}" ]]; then
  echo "Could not read deploy.hostname from configs/app.yaml" >&2
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this with sudo:"
  echo "  sudo ${APP_DIR}/deploy/disable-tunnel.sh"
  exit 1
fi

if [[ ! -f "${CLOUDFLARED_CONFIG}" ]]; then
  echo "Missing ${CLOUDFLARED_CONFIG}" >&2
  exit 1
fi

echo "Removing ${HOSTNAME_VALUE} from ${CLOUDFLARED_CONFIG}"

python3 - "${CLOUDFLARED_CONFIG}" "${HOSTNAME_VALUE}" <<'PY'
import pathlib
import shutil
import sys
import time

config_path = pathlib.Path(sys.argv[1])
hostname = sys.argv[2]
entry_marker = f"- hostname: {hostname}"

text = config_path.read_text()
if entry_marker not in text:
    print(f"{hostname} not found in {config_path} - nothing to remove")
    sys.exit(0)

lines = text.splitlines()
new_lines = []
removed = False
i = 0
while i < len(lines):
    line = lines[i]
    if line.strip() == entry_marker:
        removed = True
        i += 1
        # Also drop the "service:" line right under it that belongs to this entry.
        if i < len(lines) and lines[i].strip().startswith("service:"):
            i += 1
        continue
    new_lines.append(line)
    i += 1

if not removed:
    raise SystemExit(f"Could not find an ingress entry for {hostname}")

backup_path = config_path.with_suffix(config_path.suffix + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
shutil.copy2(config_path, backup_path)
config_path.write_text("\n".join(new_lines) + "\n")
print(f"Removed {hostname} from {config_path}; backup saved to {backup_path}")
PY

echo "Restarting cloudflared..."
systemctl restart cloudflared
systemctl --no-pager --full status cloudflared | head -10

echo
echo "Done. ${HOSTNAME_VALUE} is no longer routed by the tunnel."
