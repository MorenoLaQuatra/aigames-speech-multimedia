#!/usr/bin/env bash
# The ONE thing to launch: starts the AI Games webapp under gunicorn. The
# webapp itself starts/stops the model processes as games need them
# (services/model_manager.py) - nothing else to open or close.
# Host, port, threads and timeout come from configs/app.yaml.

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

# shellcheck source=deploy/conda-env.sh
source deploy/conda-env.sh

eval "$(python - <<'PY'
from yaml_config_manager import load_config

config = load_config(config_path="configs/app.yaml", args=[])
if config.server.workers != 1:
    raise SystemExit("server.workers must be 1 (the model manager lives in the webapp process)")
print(f"BIND_HOST={config.server.host}")
print(f"BIND_PORT={config.server.port}")
print(f"THREADS={config.server.threads}")
print(f"TIMEOUT={config.server.timeout_seconds}")
PY
)"

mkdir -p logs
echo "Starting AI Games on http://${BIND_HOST}:${BIND_PORT}"

exec gunicorn \
    --workers 1 \
    --threads "$THREADS" \
    --worker-class gthread \
    --timeout "$TIMEOUT" \
    --graceful-timeout 30 \
    --pid logs/gunicorn.pid \
    --bind "${BIND_HOST}:${BIND_PORT}" \
    --access-logfile - \
    --error-logfile - \
    "app:build()"
