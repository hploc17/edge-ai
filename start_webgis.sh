#!/usr/bin/env bash
# Script khoi dong WebGIS Operations Center tren Linux / macOS / Jetson
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/webgis/backend"
FRONTEND_DIR="${SCRIPT_DIR}/webgis/frontend"
AUTH_DIR="${SCRIPT_DIR}/webgis/auth-service"

echo "=============================================================================="
echo "      HE THONG GIAM SAT GIAO THONG THONG MINH - WEBGIS OPERATIONS CENTER"
echo "=============================================================================="

# 1. Kiem tra python3
if ! command -v python3 &> /dev/null; then
    echo "[LOI] Khong tim thay python3! Vui long cai dat python3."
    exit 1
fi

# 2. Kiem tra Auth Service dependencies
if [ -d "${AUTH_DIR}" ] && [ ! -d "${AUTH_DIR}/node_modules" ]; then
    echo "[INFO] Dang cai dat Auth Service dependencies..."
    cd "${AUTH_DIR}" && npm install && npx prisma generate
    cd "${SCRIPT_DIR}"
fi

# 3. Kiem tra Frontend dependencies
if [ -d "${FRONTEND_DIR}" ] && [ ! -d "${FRONTEND_DIR}/node_modules" ]; then
    echo "[INFO] Dang cai dat Frontend dependencies..."
    cd "${FRONTEND_DIR}" && npm install
    cd "${SCRIPT_DIR}"
fi

# 4. Kiem tra MediaMTX Docker
if command -v docker &> /dev/null && docker info &> /dev/null; then
    echo "[INFO] Dang khoi dong MediaMTX qua Docker..."
    docker compose -f "${SCRIPT_DIR}/deploy/mediamtx/docker-compose.yml" up -d 2>/dev/null || true
fi

echo "=============================================================================="
echo "Dang khoi dong cac tien trinh:"
echo "  [Auth Service]: http://localhost:5000"
echo "  [Backend API] : http://localhost:8000 (Docs: http://localhost:8000/docs)"
echo "  [Frontend Web]: http://localhost:5173"
echo "  [MediaMTX]    : http://localhost:8889 (RTSP: :8554)"
echo "Nhan Ctrl+C de dung tat ca tien trinh."
echo "=============================================================================="

# Chay Auth Service
cd "${AUTH_DIR}"
npm run dev &
AUTH_PID=$!

# Chay Backend API
cd "${BACKEND_DIR}"
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Chay Frontend
cd "${FRONTEND_DIR}"
npm run dev &
FRONTEND_PID=$!

trap "kill ${AUTH_PID} ${BACKEND_PID} ${FRONTEND_PID} 2>/dev/null || true; exit 0" INT TERM EXIT

wait
