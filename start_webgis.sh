#!/usr/bin/env bash
# Script khoi dong WebGIS Operations Center tren Linux / macOS / Jetson
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/webgis/backend"
FRONTEND_DIR="${SCRIPT_DIR}/webgis/frontend"

echo "=============================================================================="
echo "      HE THONG GIAM SAT GIAO THONG THONG MINH - WEBGIS OPERATIONS CENTER"
echo "=============================================================================="

# 1. Kiem tra python & dependencies
if ! command -v python3 &> /dev/null; then
    echo "[LOI] Khong tim thay python3! Vui long cai dat python3."
    exit 1
fi

# 2. Kiem tra frontend node_modules
if [ ! -d "${FRONTEND_DIR}/node_modules" ]; then
    echo "[INFO] Dang cai dat frontend dependencies..."
    cd "${FRONTEND_DIR}"
    npm install
    cd "${SCRIPT_DIR}"
fi

echo "Dang khoi dong cac tien trinh:"
echo "  [Backend API] : http://localhost:8000 (Docs: http://localhost:8000/docs)"
echo "  [Frontend Web]: http://localhost:5173"
echo "Nhan Ctrl+C de dung tat ca tien trinh."
echo "=============================================================================="

# Chay backend ngam
cd "${BACKEND_DIR}"
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Chay frontend
cd "${FRONTEND_DIR}"
npm run dev &
FRONTEND_PID=$!

trap "kill ${BACKEND_PID} ${FRONTEND_PID} 2>/dev/null || true; exit 0" INT TERM EXIT

wait
