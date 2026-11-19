#!/usr/bin/env bash
# Adds an account to the AI Games platform (asks the password twice, hidden).
#   ./add-user.sh <username>            # instructor (runs matches and games)
#   ./add-user.sh <username> admin      # admin (also accounts, content, models)
# Works with the platform running or stopped. Existing accounts (password reset,
# role change, disable) are managed from Amministrazione in the web UI.

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: ./add-user.sh <username> [instructor|admin]" >&2
    exit 1
fi
USERNAME="$1"
ROLE="${2:-instructor}"

# shellcheck source=deploy/conda-env.sh
source deploy/conda-env.sh
flask --app "app:build" create-user --username "$USERNAME" --role "$ROLE"
