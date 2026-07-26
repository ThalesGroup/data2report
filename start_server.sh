#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set -a
# shellcheck source=/dev/null
source "$SCRIPT_DIR/config/aws.env.list"
set +a

# Allow caller to override APP_PORT after env file is sourced
APP_PORT="${APP_PORT:-5001}"

# Kill any existing instance
pkill -f "data2report_rest.py" 2>/dev/null || true
lsof -ti :"$APP_PORT" | xargs kill -9 2>/dev/null || true

LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/server-$(date +%Y%m%d-%H%M%S).log"

echo "Starting data2report REST server on port $APP_PORT..."
echo "Logs: $LOG_FILE"

cd "$SCRIPT_DIR"
APP_PORT="$APP_PORT" PYTHONPATH="$SCRIPT_DIR/src" python src/rest/data2report_rest.py \
  2>&1 | tee "$LOG_FILE"
