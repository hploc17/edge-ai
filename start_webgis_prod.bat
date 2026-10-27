@echo off
chcp 65001 >nul
title Khởi động WebGIS Production (Cổng đơn 8000)
echo ==============================================================================
echo   WEBGIS OPERATIONS CENTER (CHẾ ĐỘ STANDALONE / PRODUCTION - PORT 8000)
echo ==============================================================================
echo.
echo [1/3] Kiểm tra bản build Frontend...
if not exist "%~dp0webgis\frontend\dist\index.html" (
    echo [INFO] Chưa tìm thấy bản build Frontend. Đang build từ mã nguồn...
    pushd "%~dp0webgis\frontend"
    if not exist "node_modules\" call npm install
    call npm run build
    popd
)

echo [2/3] Bản build Frontend đã sẵn sàng tại webgis\frontend\dist.
echo.
echo [3/3] Khởi động WebGIS Hub (FastAPI phục vụ cả Web UI và Backend API)...
echo   - 🌐 Giao diện WebGIS:     http://localhost:8000/
echo   - 📑 Tài liệu API Swagger:  http://localhost:8000/docs
echo   - 📡 WebSocket Realtime:   ws://localhost:8000/ws
echo ==============================================================================
echo.
cd /d "%~dp0webgis\backend"
python -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
