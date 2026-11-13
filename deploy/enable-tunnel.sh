#!/usr/bin/env bash
# Adds this app's public hostname (configs/app.yaml: deploy.hostname) to the
# shared Cloudflare Tunnel, pointing at the configured server.port (both read
# from the YAML, never hardcoded here), restarts cloudflared, then creates the
# DNS route - see
# knowledge/personal-obsidian-knowledge/linux-guides/add-cloudflare-tunnel.md
# (steps 4-6) and apps/openslot/deploy/install-openslot-systemd-cloudflare.sh,
# which the config.yml editing here mirrors.
#
# Run with sudo (it edits a root-owned file and restarts a system service):
#   sudo /home/mlaquatra/apps/ai-games-platform/deploy/enable-tunnel.sh
#
# The `cloudflared tunnel route dns` step deliberately runs as the invoking
# user, not root - it reads that user's own ~/.cloudflared/cert.pem to talk
# to the Cloudflare API, which doesn't exist for root.

set -euo pipefail

APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
CONFIG_YAML="${APP_DIR}/configs/app.yaml"
CLOUDFLARED_CONFIG="/etc/cloudflared/config.yml"
TUNNEL_NAME="annotations"   # this machine's single shared tunnel - see `cloudflared tunnel list`
ROUTE_DNS_USER="${SUDO_USER:-mlaquatra}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this with sudo:"
  echo "  sudo ${APP_DIR}/deploy/enable-tunnel.sh"
  exit 1
fi

if [[ ! -f "${CONFIG_YAML}" ]]; then
  echo "Missing ${CONFIG_YAML}" >&2
  exit 1
fi
if [[ ! -f "${CLOUDFLARED_CONFIG}" ]]; then
  echo "Missing ${CLOUDFLARED_CONFIG}" >&2
  exit 1
fi

LOCAL_PORT=$(awk '/^server:/{f=1; next} f && /^[a-zA-Z]/{f=0} f && /port:/{print $2; exit}' "${CONFIG_YAML}" | tr -d '"')
if [[ -z "${LOCAL_PORT}" ]]; then
  echo "Could not read server.port from ${CONFIG_YAML}" >&2
  exit 1
fi
LOCAL_SERVICE="http://127.0.0.1:${LOCAL_PORT}"

HOSTNAME_VALUE=$(awk '/^deploy:/{f=1; next} f && /^[a-zA-Z]/{f=0} f && /hostname:/{print $2; exit}' "${CONFIG_YAML}" | tr -d '"')
if [[ -z "${HOSTNAME_VALUE}" ]]; then
  echo "Could not read deploy.hostname from ${CONFIG_YAML}" >&2
  exit 1
fi

if ! curl -sf -o /dev/null "http://127.0.0.1:${LOCAL_PORT}/login"; then
  echo "Note: nothing is answering on ${LOCAL_SERVICE} right now (./start.sh not running?)."
  echo "That's fine if you're wiring the tunnel ahead of time - continuing anyway."
fi

echo "Adding ${HOSTNAME_VALUE} -> ${LOCAL_SERVICE} to ${CLOUDFLARED_CONFIG}"

python3 - "${CLOUDFLARED_CONFIG}" "${HOSTNAME_VALUE}" "${LOCAL_SERVICE}" <<'PY'
import pathlib
import shutil
import sys
import time

config_path = pathlib.Path(sys.argv[1])
hostname = sys.argv[2]
local_service = sys.argv[3]

text = config_path.read_text()
if f"hostname: {hostname}" in text:
    print(f"{hostname} already exists in {config_path} - leaving it as is")
    sys.exit(0)

lines = text.splitlines()
insert_at = None
for index, line in enumerate(lines):
    if line.strip() == "- service: http_status:404":
        insert_at = index
        break

if insert_at is None:
    raise SystemExit("Could not find the final '- service: http_status:404' rule")

entry = [
    f"  - hostname: {hostname}",
    f"    service: {local_service} # ai-games-platform (UKE AI Games)",
]

backup_path = config_path.with_suffix(config_path.suffix + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
shutil.copy2(config_path, backup_path)
lines[insert_at:insert_at] = entry
config_path.write_text("\n".join(lines) + "\n")
print(f"Updated {config_path}; backup saved to {backup_path}")
PY

echo
echo "Creating the DNS route (as ${ROUTE_DNS_USER}, not root)..."
# Idempotent: if the route already points here, cloudflared just says so and
# exits non-zero - that's not a real failure, so don't let `set -e` kill the
# script over it.
sudo -u "${ROUTE_DNS_USER}" cloudflared tunnel route dns "${TUNNEL_NAME}" "${HOSTNAME_VALUE}" || true

echo "Restarting cloudflared..."
systemctl restart cloudflared
systemctl --no-pager --full status cloudflared | head -10

echo
echo "Done. https://${HOSTNAME_VALUE} should now proxy to ${LOCAL_SERVICE}."
echo "Make sure ./start.sh is running before relying on it."
