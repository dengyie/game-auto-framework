#!/usr/bin/env bash
# ==============================================================================
# Enterprise VPS Installer for game-auto-framework
# Modes:
#   1. docker  - Standalone Docker container with ADB bridge
#   2. redroid - Docker + Redroid Headless Android Cloud Farm
#   3. systemd - Native Bare-Metal Systemd Daemon via astral/uv
# ==============================================================================

set -euo pipefail

DEPLOY_MODE="${1:-docker}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=========================================================="
echo "   game-auto-framework Enterprise VPS Installer           "
echo "   Target Mode: ${DEPLOY_MODE}                            "
echo "=========================================================="

detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    else
        echo "unknown"
    fi
}

OS_TYPE="$(detect_os)"
echo "[*] Detected OS: ${OS_TYPE}"

case "${DEPLOY_MODE}" in
    docker)
        echo "[+] Launching in Standard Docker Container mode..."
        if ! command -v docker >/dev/null 2>&1; then
            echo "[!] Docker not found. Installing docker via official get.docker.com..."
            curl -fsSL https://get.docker.com | sh
        fi
        cd "${PROJECT_ROOT}"
        docker compose -f deploy/docker-compose.yml up -d --build
        echo "[✓] Docker deployment initiated."
        ;;

    redroid)
        echo "[+] Launching in Redroid Headless Cloud Phone mode..."
        # Load necessary Android kernel modules on Linux VPS
        if [ "$(uname -s)" = "Linux" ]; then
            echo "[*] Loading binder_linux and ashmem_linux kernel modules..."
            modprobe binder_linux devices="binder,hwbinder,vndbinder" || true
            modprobe ashmem_linux || true
        fi
        cd "${PROJECT_ROOT}"
        docker compose -f deploy/docker-compose.redroid.yml up -d --build
        echo "[✓] Redroid Cloud Phone farm initiated."
        ;;

    systemd)
        echo "[+] Installing as Native Systemd Service..."
        if ! command -v uv >/dev/null 2>&1; then
            echo "[*] Installing astral-sh/uv package manager..."
            curl -LsSf https://astral.sh/uv/install.sh | sh
            export PATH="$HOME/.cargo/bin:$PATH"
        fi
        cd "${PROJECT_ROOT}"
        uv sync

        SERVICE_FILE="/etc/systemd/system/game-auto.service"
        echo "[*] Registering systemd service at ${SERVICE_FILE}..."
        sed "s|/opt/game-auto-framework|${PROJECT_ROOT}|g" "${SCRIPT_DIR}/game-auto.service" > "${SERVICE_FILE}"
        systemctl daemon-reload
        systemctl enable --now game-auto
        echo "[✓] Systemd service game-auto enabled and started."
        ;;

    *)
        echo "Usage: $0 [docker|redroid|systemd]"
        exit 1
        ;;
esac

echo ""
echo "[*] Waiting 5 seconds for service startup..."
sleep 5

echo "[*] Testing healthcheck endpoint: http://localhost:8000/health"
if command -v curl >/dev/null 2>&1; then
    curl -s http://localhost:8000/health || echo "[!] Health check pending, check logs for details."
fi

echo ""
echo "=========================================================="
echo "   Deployment Complete!                                   "
echo "   Web Dashboard: http://<YOUR_VPS_IP>:8000/dashboard    "
echo "   REST API Docs: http://<YOUR_VPS_IP>:8000/docs         "
echo "=========================================================="
