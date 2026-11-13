#!/usr/bin/env bash
# Publishes the app through this machine's locally-managed Cloudflare tunnel
# (configs/app.yaml: deploy.tunnel, deploy.hostname -> server.port).
#
# Why not enable-tunnel.sh: that one edits /etc/cloudflared/config.yml, the
# old workstation's layout. Here the root cloudflared.service runs a
# token/dashboard-managed tunnel that is not ours, so this app uses its own
# locally-managed tunnel instead:
#   1. ~/.cloudflared/config.yml (owned by the user): tunnel + credentials +
#      ingress; the hostname is added before the catch-all rule, so other apps
#      can share the same file and tunnel;
#   2. a system service cloudflared-<tunnel>.service that runs the tunnel as
#      the user (starts at boot, no login needed);
#   3. the DNS route hostname -> tunnel (--overwrite-dns: the hostname may
#      still point at the old workstation's tunnel).
#
# Run once with sudo, with ./start.sh already running:
#   sudo /home/mlaquatra/apps/ai-games-platform/deploy/setup-local-tunnel.sh
# Idempotent: running it again keeps an existing ingress rule.

set -euo pipefail

APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
CONFIG_YAML="${APP_DIR}/configs/app.yaml"
CLOUDFLARED_BIN="/usr/local/bin/cloudflared"
RUN_USER="${SUDO_USER:-}"

if [[ "${EUID}" -ne 0 || -z "${RUN_USER}" ]]; then
  echo "Run this with sudo from your own account:"
  echo "  sudo ${APP_DIR}/deploy/setup-local-tunnel.sh"
  exit 1
fi
if [[ ! -x "${CLOUDFLARED_BIN}" ]]; then
  echo "Missing ${CLOUDFLARED_BIN}" >&2
  exit 1
fi

read_yaml() {  # read_yaml <section> <key>: a flat key of a top-level section
  awk -v section="$1:" -v key="$2:" '
    $0 == section {f=1; next}
    f && /^[a-zA-Z]/ {f=0}
    f && $1 == key {print $2; exit}' "${CONFIG_YAML}" | tr -d '"'
}

LOCAL_PORT="$(read_yaml server port)"
HOSTNAME_VALUE="$(read_yaml deploy hostname)"
TUNNEL_NAME="$(read_yaml deploy tunnel)"
for value in LOCAL_PORT HOSTNAME_VALUE TUNNEL_NAME; do
  if [[ -z "${!value}" ]]; then
    echo "Could not read ${value} from ${CONFIG_YAML}" >&2
    exit 1
  fi
done
LOCAL_SERVICE="http://127.0.0.1:${LOCAL_PORT}"

USER_HOME="$(getent passwd "${RUN_USER}" | cut -d: -f6)"
CF_DIR="${USER_HOME}/.cloudflared"
CF_CONFIG="${CF_DIR}/config.yml"
SERVICE_NAME="cloudflared-${TUNNEL_NAME}.service"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}"

as_user() { sudo -u "${RUN_USER}" -H "$@"; }

TUNNEL_ID="$(as_user "${CLOUDFLARED_BIN}" tunnel list --name "${TUNNEL_NAME}" --output json \
  | python3 -c 'import json, sys; tunnels = json.load(sys.stdin); assert len(tunnels) == 1, tunnels; print(tunnels[0]["id"])')"
CREDENTIALS="${CF_DIR}/${TUNNEL_ID}.json"
if [[ ! -f "${CREDENTIALS}" ]]; then
  echo "Missing tunnel credentials ${CREDENTIALS}" >&2
  exit 1
fi
echo "Tunnel ${TUNNEL_NAME} = ${TUNNEL_ID}"

if ! curl -sf -o /dev/null "${LOCAL_SERVICE}/login"; then
  echo "Note: nothing answers on ${LOCAL_SERVICE}/login (./start.sh not running?) - continuing."
fi

echo "Ingress ${HOSTNAME_VALUE} -> ${LOCAL_SERVICE} in ${CF_CONFIG}"
as_user python3 - "${CF_CONFIG}" "${TUNNEL_ID}" "${CREDENTIALS}" "${HOSTNAME_VALUE}" "${LOCAL_SERVICE}" <<'PY'
import pathlib
import shutil
import sys
import time

config_path = pathlib.Path(sys.argv[1])
tunnel_id, credentials, hostname, local_service = sys.argv[2:6]
rule = [f"  - hostname: {hostname}", f"    service: {local_service}  # ai-games-platform (UKE AI Games)"]

if not config_path.exists():
    lines = [f"tunnel: {tunnel_id}", f"credentials-file: {credentials}", "", "ingress:", *rule,
             "  - service: http_status:404"]
    config_path.write_text("\n".join(lines) + "\n")
    print(f"Created {config_path}")
    sys.exit(0)

text = config_path.read_text()
if f"tunnel: {tunnel_id}" not in text:
    raise SystemExit(f"{config_path} exists but is not for tunnel {tunnel_id} - fix it by hand")
if f"hostname: {hostname}" in text:
    print(f"{hostname} already in {config_path} - leaving it as is")
    sys.exit(0)
lines = text.splitlines()
catch_all = [i for i, line in enumerate(lines) if line.strip() == "- service: http_status:404"]
if len(catch_all) != 1:
    raise SystemExit(f"Expected exactly one '- service: http_status:404' rule in {config_path}")
backup = config_path.with_suffix(config_path.suffix + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
shutil.copy2(config_path, backup)
lines[catch_all[0]:catch_all[0]] = rule
config_path.write_text("\n".join(lines) + "\n")
print(f"Updated {config_path}; backup {backup}")
PY
as_user "${CLOUDFLARED_BIN}" tunnel --config "${CF_CONFIG}" ingress validate

echo "Installing ${UNIT_PATH}"
cat > "${UNIT_PATH}" <<UNIT
[Unit]
Description=Cloudflare Tunnel ${TUNNEL_NAME} (locally managed, ${CF_CONFIG})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
ExecStart=${CLOUDFLARED_BIN} --no-autoupdate --config ${CF_CONFIG} tunnel run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
sleep 5
systemctl --no-pager --full status "${SERVICE_NAME}" | head -8

echo
echo "DNS: ${HOSTNAME_VALUE} -> tunnel ${TUNNEL_NAME} (as ${RUN_USER}, overwriting the old route)"
as_user "${CLOUDFLARED_BIN}" tunnel route dns --overwrite-dns "${TUNNEL_NAME}" "${HOSTNAME_VALUE}"

echo
echo "Done: https://${HOSTNAME_VALUE} -> ${LOCAL_SERVICE}"
echo "Later hostnames: add a rule to ${CF_CONFIG}, then: sudo systemctl restart ${SERVICE_NAME}"
