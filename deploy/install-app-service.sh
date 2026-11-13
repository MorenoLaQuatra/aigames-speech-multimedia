#!/usr/bin/env bash
# Installs the webapp as a system service, ai-games.service, that runs
# ./start.sh as the invoking user. Then:
#   sudo systemctl start ai-games      # activate
#   sudo systemctl stop ai-games       # deactivate (model workers stop too, GPU freed)
#   systemctl status ai-games          # state
#   journalctl -u ai-games -f          # log (worker logs stay in logs/worker-<name>.log)
# It is NOT enabled at boot (the GPU is shared): `sudo systemctl enable ai-games`
# if you ever want that.
#
# Run once with sudo from your own account:
#   sudo /home/mlaquatra/apps/ai-games-platform/deploy/install-app-service.sh

set -euo pipefail

APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
RUN_USER="${SUDO_USER:-}"
SERVICE_NAME="ai-games.service"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}"

if [[ "${EUID}" -ne 0 || -z "${RUN_USER}" ]]; then
  echo "Run this with sudo from your own account:"
  echo "  sudo ${APP_DIR}/deploy/install-app-service.sh"
  exit 1
fi
if [[ ! -x "${APP_DIR}/start.sh" ]]; then
  echo "Missing or not executable: ${APP_DIR}/start.sh" >&2
  exit 1
fi

echo "Installing ${UNIT_PATH} (runs ${APP_DIR}/start.sh as ${RUN_USER})"
cat > "${UNIT_PATH}" <<UNIT
[Unit]
Description=AI Games (UKE) webapp - ${APP_DIR}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/start.sh
# Stopping kills the whole control group: gunicorn and its model workers.
KillMode=control-group
TimeoutStopSec=60
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload

echo
echo "Installed (not enabled at boot). Use:"
echo "  sudo systemctl start ai-games"
echo "  sudo systemctl stop ai-games"
