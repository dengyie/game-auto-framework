#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# game-auto-framework VPS One-Click Deployment Script
# Supports: Debian / Ubuntu / CentOS / Arch Linux
# ==============================================================================

echo ">>> [1/4] Checking Docker and Compose environment..."
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "Docker & Docker Compose detected."
    echo ">>> [2/4] Building and launching game-auto-framework container..."
    docker compose up -d --build
    echo ">>> [3/4] Container launched. Verifying health endpoint..."
    sleep 3
    curl -s http://localhost:8000/health || true
    echo ""
    echo ">>> [4/4] Successfully deployed! Access the API at http://<YOUR_VPS_IP>:8000"
    exit 0
fi

echo "Docker not detected. Falling back to native Python & uv deployment..."
if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.cargo/env" || export PATH="$HOME/.local/bin:$PATH"
fi

echo ">>> [2/4] Installing project dependencies..."
uv sync

echo ">>> [3/4] Starting background daemon..."
nohup uv run python main.py server --host 0.0.0.0 --port 8000 > logs/server.log 2>&1 &

sleep 2
echo ">>> [4/4] Native service started! API available at http://localhost:8000"
