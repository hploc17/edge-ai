@echo off
title WebGIS Smart Traffic Operations Center
echo ==============================================================================
echo       SMART TRAFFIC MONITORING - WEBGIS OPERATIONS CENTER
echo ==============================================================================
echo.
echo [1/4] Kiem tra moi truong Python va Node.js...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Khong tim thay Python! Vui long cai dat Python va them vao PATH.
    pause
    exit /b 1
)

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Khong tim thay Node.js! Vui long cai dat Node.js va them vao PATH.
    pause
    exit /b 1
)

echo.
echo [2/4] Kiem tra thu vien phu thuoc...
python -m pip install -r "%~dp0webgis\backend\requirements.txt" --quiet

if not exist "%~dp0webgis\auth-service\node_modules\" (
    echo [INFO] Dang cai dat Auth Service dependencies...
    pushd "%~dp0webgis\auth-service"
    call npm install
    call npx prisma generate
    popd
)

if not exist "%~dp0webgis\frontend\node_modules\" (
    echo [INFO] Dang cai dat Frontend dependencies...
    pushd "%~dp0webgis\frontend"
    call npm install
    popd
)

echo.
echo [3/4] Kiem tra MediaMTX Streaming Server...
netstat -ano | findstr :8554 >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] MediaMTX Streaming Server da san sang tren cong 8554.
) else (
    docker info >nul 2>&1
    if %errorlevel% equ 0 (
        echo [INFO] Dang khoi dong MediaMTX Container qua Docker...
        docker compose -f "%~dp0deploy\mediamtx\docker-compose.yml" up -d >nul 2>&1
    ) else if exist "%~dp0deploy\mediamtx\mediamtx.exe" (
        echo [INFO] Dang khoi dong MediaMTX Binary...
        start "WebGIS MediaMTX Server" cmd /k "cd /d %~dp0deploy\mediamtx && mediamtx.exe mediamtx.yml"
    )
)

echo.
echo [4/4] Khoi dong cac dich vu WebGIS:
echo   - Auth Service (Express):         http://localhost:5000
echo   - Backend GIS Hub (FastAPI):      http://localhost:8000 (Swagger: /docs)
echo   - Frontend WebGIS Dashboard:     http://localhost:5173
echo.
echo ==============================================================================
echo Dang mo 3 cua so tien trinh rieng biet...
echo ==============================================================================

start "WebGIS Auth Service" cmd /k "cd /d %~dp0webgis\auth-service && npm run dev"
start "WebGIS Backend" cmd /k "cd /d %~dp0webgis\backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
start "WebGIS Frontend" cmd /k "cd /d %~dp0webgis\frontend && npm run dev"

echo.
echo ==============================================================================
echo [THANH CONG] Toan bo he thong WebGIS dang duoc khoi dong!
echo Mo trinh duyet tai: http://localhost:5173
echo ==============================================================================
echo.
pause
