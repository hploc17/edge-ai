@echo off
title WebGIS Production Mode (Port 8000)
echo ==============================================================================
echo   WEBGIS OPERATIONS CENTER (PRODUCTION MODE - PORT 8000)
echo ==============================================================================
echo.
echo [1/4] Kiem tra ban build Frontend...
if not exist "%~dp0webgis\frontend\dist\index.html" (
    echo [INFO] Chua tim thay ban build Frontend. Dang build tu ma nguon...
    pushd "%~dp0webgis\frontend"
    if not exist "node_modules\" call npm install
    call npm run build
    popd
)
echo [OK] Ban build Frontend da san sang tai webgis\frontend\dist.

echo.
echo [2/4] Kiem tra MediaMTX Streaming Server...
netstat -ano | findstr :8554 >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] MediaMTX Streaming Server dang lang nghe tren cong 8554.
) else (
    docker info >nul 2>&1
    if %errorlevel% equ 0 (
        echo [INFO] Dang kich hoat MediaMTX qua Docker...
        docker compose -f "%~dp0deploy\mediamtx\docker-compose.yml" up -d >nul 2>&1
    )
)

echo.
echo [3/4] Khoi dong Auth Service (:5000)...
if not exist "%~dp0webgis\auth-service\node_modules\" (
    pushd "%~dp0webgis\auth-service"
    call npm install
    call npx prisma generate
    popd
)
start "WebGIS Auth Service" cmd /k "cd /d %~dp0webgis\auth-service && npm run dev"

echo.
echo [4/4] Khoi dong WebGIS Hub (FastAPI phuc vu ca Web UI va Backend API)...
echo   - Giao dien WebGIS:     http://localhost:8000/
echo   - Tai lieu API Swagger: http://localhost:8000/docs
echo   - WebSocket Realtime:   ws://localhost:8000/ws
echo ==============================================================================
echo.
cd /d "%~dp0webgis\backend"
python -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
