@echo off
chcp 65001 >nul
title Khởi động WebGIS Smart Traffic Operations Center
echo ==============================================================================
echo       HỆ THỐNG GIÁM SÁT GIAO THÔNG THÔNG MINH - WEBGIS OPERATIONS CENTER
echo ==============================================================================
echo.
echo [1/3] Kiểm tra môi trường...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [LỖI] Không tìm thấy Python! Vui lòng cài đặt Python >= 3.10 và thêm vào PATH.
    pause
    exit /b 1
)

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [LỖI] Không tìm thấy Node.js! Vui lòng cài đặt Node.js LTS (>= 18) và thêm vào PATH.
    pause
    exit /b 1
)

echo [2/3] Kiểm tra thư viện Backend & Frontend...
if not exist "%~dp0webgis\frontend\node_modules\" (
    echo [INFO] Thư mục node_modules chưa có. Đang cài đặt frontend dependencies...
    pushd "%~dp0webgis\frontend"
    call npm install
    popd
)

echo.
echo [3/3] Khởi động các dịch vụ:
echo   - Backend API & WebSockets: http://localhost:8000 (Swagger: http://localhost:8000/docs)
echo   - Frontend Vite Dashboard:  http://localhost:5173
echo.
echo ==============================================================================
echo Đang mở 2 cửa sổ tiến trình riêng biệt cho Backend và Frontend...
echo ==============================================================================

:: Khởi động Backend Hub FastAPI
start "WebGIS Backend (FastAPI Hub :8000)" cmd /k "cd /d "%~dp0webgis\backend" && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

:: Khởi động Frontend Vite React
start "WebGIS Frontend (Vite React :5173)" cmd /k "cd /d "%~dp0webgis\frontend" && npm run dev"

echo.
echo ✅ Cả 2 dịch vụ đã được khởi chạy thành công!
echo    Vui lòng truy cập trình duyệt tại: http://localhost:5173
echo.
pause
