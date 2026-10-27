@echo off
title WebGIS Smart Traffic Operations Center
echo ==============================================================================
echo       SMART TRAFFIC MONITORING - WEBGIS OPERATIONS CENTER
echo ==============================================================================
echo.
echo [1/3] Kiem tra moi truong Python va Node.js...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Khong tim thay Python! Vui long cai dat Python >= 3.10 va them vao PATH.
    pause
    exit /b 1
)

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Khong tim thay Node.js! Vui long cai dat Node.js >= 18 va them vao PATH.
    pause
    exit /b 1
)

echo.
echo [2/3] Kiem tra va cai dat thu vien (Backend, Auth-Service, Frontend)...

echo [INFO] Kiem tra thu vien Python Backend...
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
echo [3/3] Khoi dong cac dich vu:
echo   - Auth Service (Express):         http://localhost:5000
echo   - Backend GIS Hub (FastAPI):      http://localhost:8000 (Swagger: /docs)
echo   - Frontend WebGIS Dashboard:     http://localhost:5173
echo.
echo ==============================================================================
echo Dang mo 3 cua so tien trinh rieng biet...
echo ==============================================================================

:: Khoi dong Auth Service (Express :5000)
start "WebGIS Auth Service (:5000)" cmd /k "cd /d %~dp0webgis\auth-service && npm run dev"

:: Khoi dong Backend Hub FastAPI (:8000)
start "WebGIS Backend (:8000)" cmd /k "cd /d %~dp0webgis\backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

:: Khoi dong Frontend Vite React (:5173)
start "WebGIS Frontend (:5173)" cmd /k "cd /d %~dp0webgis\frontend && npm run dev"

echo.
echo [OK] Ca 3 dich vu dang duoc khoi dong trong cac cua so rieng biet.
echo Truy cap trinh duyet tai: http://localhost:5173
echo.
pause
