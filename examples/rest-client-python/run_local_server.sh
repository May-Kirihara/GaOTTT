#!/usr/bin/env bash
# Boot a local GaOTTT REST server against an ISOLATED /tmp database.
#
# Production memory (~/.local/share/gaottt/) is never touched.
# The server stays in the foreground; Ctrl-C to stop.
#
# Usage:
#   bash examples/rest-client-python/run_local_server.sh
#   PORT=9000 bash examples/rest-client-python/run_local_server.sh
#
# Override the data dir to keep the demo DB around between runs:
#   DATA_DIR=/tmp/gaottt-demo bash examples/rest-client-python/run_local_server.sh

set -euo pipefail

PORT="${PORT:-8001}"
DATA_DIR="${DATA_DIR:-/tmp/gaottt-example-demo}"

# Resolve project root from this script's location so it works from anywhere.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "ERROR: ${PYTHON} not found." >&2
  echo "Create the venv first: uv sync   (from project root)" >&2
  exit 2
fi

mkdir -p "${DATA_DIR}"
echo "Data dir : ${DATA_DIR}"
echo "Port     : ${PORT}"
echo "Swagger  : http://localhost:${PORT}/docs"
echo "Stop     : Ctrl-C"
echo

GAOTTT_DATA_DIR="${DATA_DIR}" \
  exec "${PYTHON}" -m uvicorn gaottt.server.app:app \
    --host 127.0.0.1 --port "${PORT}"
