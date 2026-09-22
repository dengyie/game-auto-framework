#!/usr/bin/env bash
# ==============================================================================
# 24-Hour Production Soak Test Launcher for game-auto-framework
# Usage:
#   ./deploy/run_soak_test.sh [duration_hours] [instances] [device_type]
# Example:
#   ./deploy/run_soak_test.sh 24 5 virtual
# ==============================================================================

set -euo pipefail

DURATION_HOURS="${1:-24.0}"
NUM_INSTANCES="${2:-5}"
DEVICE_TYPE="${3:-virtual}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}"
SOAK_LOG="${LOG_DIR}/soak_test_24h.log"
REPORT_JSON="${LOG_DIR}/soak_test_report.json"
REPORT_MD="${LOG_DIR}/soak_test_report.md"

echo "=========================================================="
echo "   game-auto-framework 24h Soak Test Production Suite     "
echo "   Duration: ${DURATION_HOURS} Hours | Instances: ${NUM_INSTANCES}       "
echo "   Device Backend: ${DEVICE_TYPE}                         "
echo "   Log Output: ${SOAK_LOG}                                "
echo "=========================================================="

cd "${PROJECT_ROOT}"

# Check python environment
if command -v uv >/dev/null 2>&1; then
    PY_CMD="uv run python"
elif [ -f "${PROJECT_ROOT}/.venv/bin/python" ]; then
    PY_CMD="${PROJECT_ROOT}/.venv/bin/python"
else
    PY_CMD="python3"
fi

echo "[*] Using Python runtime: ${PY_CMD}"

# Background launch with nohup and logging
echo "[*] Launching 24h soak test in background..."
nohup ${PY_CMD} scripts/soak_test_24h.py \
    --duration-hours "${DURATION_HOURS}" \
    --sample-interval-sec 10.0 \
    --instances "${NUM_INSTANCES}" \
    --device-type "${DEVICE_TYPE}" \
    --report "${REPORT_JSON}" > "${SOAK_LOG}" 2>&1 &

PID=$!
echo "${PID}" > "${LOG_DIR}/soak_test.pid"

echo "[✓] Soak test successfully spawned in background! (PID: ${PID})"
echo ""
echo "Useful Commands:"
echo "  - Live Logs Stream : tail -f ${SOAK_LOG}"
echo "  - Check Status     : ps aux | grep soak_test_24h"
echo "  - Stop Gracefully  : kill -TERM \$(cat ${LOG_DIR}/soak_test.pid)"
echo "  - View Final Report: cat ${REPORT_MD}"
echo "=========================================================="
